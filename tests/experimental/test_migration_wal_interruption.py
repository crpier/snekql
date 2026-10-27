"""Uncommitted WAL effects from frozen role work are not accepted after client death."""

import asyncio
import json
import os
import signal
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Literal

import aiosqlite
from snektest import Param, assert_eq, test

from snekql import sqlite
from snekql.experimental import migrations as m
from tests.experimental.test_migration_authoring_journey import _python
from tests.experimental.test_migration_role_interruption import (
    _apply,
    _finish,
    _go,
    _render,
    _start,
    _stop,
)

_WORKLOAD = 65_536


def _varint(data: bytes, offset: int) -> tuple[int, int]:
    """Read an actual SQLite record/cell varint; never interpret migration declarations."""
    value = 0
    for index in range(9):
        byte = data[offset]
        offset += 1
        if index == 8:
            return (value << 8) | byte, offset
        value = (value << 7) | (byte & 0x7F)
        if byte < 128:
            return value, offset
    message = "unreachable SQLite varint"
    raise AssertionError(message)


def _audit_rows(page: bytes) -> list[tuple[int, int]]:  # noqa: C901 - finite independent on-disk observer
    """Read only local leaf records matching the visible real audit schema/workload."""
    if page[0] != 13:
        return []
    count = int.from_bytes(page[3:5], "big")
    assert count <= (len(page) - 8) // 2
    result = []
    for index in range(count):
        cell = int.from_bytes(page[8 + index * 2 : 10 + index * 2], "big")
        size, position = _varint(page, cell)
        rowid, position = _varint(page, position)
        if size > len(page) - position:
            continue  # Not a local audit record; no overflow/general record reader.
        record = page[position : position + size]
        header, offset = _varint(record, 0)
        types = []
        while offset < header:
            serial, offset = _varint(record, offset)
            types.append(serial)
        if len(types) != 5 or not 1 <= rowid <= _WORKLOAD:
            continue
        values: list[object] = []
        offset = header
        for serial in types:
            if serial in (0, 8, 9):
                values.append(None if serial == 0 else serial - 8)
                continue
            if 1 <= serial <= 6:
                size = (1, 2, 3, 4, 6, 8)[serial - 1]
                values.append(
                    int.from_bytes(record[offset : offset + size], "big", signed=True)
                )
            elif serial >= 12 and serial % 2 == 0:
                size = (serial - 12) // 2
                values.append(record[offset : offset + size])
            else:
                break
            offset += size
        if (
            len(values) == 5
            and values[:3] == [None, 1, rowid]
            and values[3] == bytes(512)
            and values[4] in (1, 2)
        ):
            assert isinstance(values[4], int)
            result.append((rowid, values[4]))
    return result


def _checksum(
    data: bytes, byteorder: Literal["little", "big"], prior: tuple[int, int] = (0, 0)
) -> tuple[int, int]:
    """Independent SQLite WAL checksum over actual header/frame bytes."""
    assert len(data) % 8 == 0
    first, second = prior
    for offset in range(0, len(data), 8):
        first = (
            first + int.from_bytes(data[offset : offset + 4], byteorder) + second
        ) & 0xFFFFFFFF
        second = (
            second + int.from_bytes(data[offset + 4 : offset + 8], byteorder) + first
        ) & 0xFFFFFFFF
    return first, second


def _spill(path: Path) -> dict[str, object]:
    """Validate a stopped writer's real WAL prefix; never manufacture a commit marker."""
    data = path.read_bytes()
    magic = int.from_bytes(data[:4], "big")
    assert magic in (0x377F0682, 0x377F0683)
    byteorder = "little" if magic == 0x377F0682 else "big"
    page_size = int.from_bytes(data[8:12], "big")
    assert page_size == 4096
    prior = _checksum(data[:24], byteorder)
    assert prior == (
        int.from_bytes(data[24:28], "big"),
        int.from_bytes(data[28:32], "big"),
    )
    frames = 0
    rows = []
    commits = []
    for offset in range(32, len(data) - 23 - page_size, page_size + 24):
        frame = data[offset : offset + page_size + 24]
        if frame[8:16] != data[16:24]:
            break
        current = _checksum(frame[:8] + frame[24:], byteorder, prior)
        if current != (
            int.from_bytes(frame[16:20], "big"),
            int.from_bytes(frame[20:24], "big"),
        ):
            break  # SIGSTOP may interrupt a write; don't certify partial frame bytes.
        prior = current
        frames += 1
        if int.from_bytes(frame[4:8], "big"):
            commits.append(frames)
        rows.extend(_audit_rows(frame[24:]))
    assert rows, "no real audit records spilled from the role UPDATE"
    assert not commits, "window already contains a committed transaction"
    return {
        "bytes": len(data),
        "valid_frames": frames,
        "commit_frames": commits,
        "audit_rows": len(rows),
        "piece_min": min(r[0] for r in rows),
        "piece_max": max(r[0] for r in rows),
        "sync_values": sorted({r[1] for r in rows}),
    }


def _wal_size(path: Path) -> int:
    """Observe an actual owned file, not driver execution flags."""
    try:
        return path.stat().st_size
    except FileNotFoundError:
        return 0


def _stopped(pid: int) -> bool:
    """Require the whole owned process thread group to stop before reading its WAL."""
    states = [
        p.joinpath("status").read_text().split("State:\t", 1)[1][0]
        for p in Path(f"/proc/{pid}/task").iterdir()
    ]
    return bool(states) and all(state == "T" for state in states)


def _save_original(path: Path, wire: str) -> None:
    """Caller saves original evidence BEFORE execution; not host-loss certification."""
    temporary = path.with_suffix(".pending")
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as stream:
        stream.write(wire)
        stream.flush()
        os.fsync(stream.fileno())
    temporary.replace(path)
    directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)


@test(
    [
        Param[Literal["normal", "full"]](value="normal", name="normal"),
        Param[Literal["normal", "full"]](value="full", name="full"),
    ],
    mark="slow",
)
async def wal_role_writer_death_discards_real_uncommitted_spill_and_reuses_original(  # noqa: PLR0915 - keep physical window, original evidence and application visible
    durability: Literal["normal", "full"],
) -> None:
    """Pinned WAL reader sees old data while actual retained SQL audit spills role work."""
    sync = 1 if durability == "normal" else 2
    with TemporaryDirectory() as directory:
        root = Path(directory)
        deploy = await _render(root, "sqlite")
        source = Path(__file__).parent / "fixtures/wal-interruption/worker.py.in"
        await asyncio.to_thread(
            (deploy / "wal_worker.py").write_text, source.read_text()
        )
        path = root / "app.db"
        payload = {"database": str(path), "durability": durability}
        config = sqlite.Config(
            database=path,
            durability=durability,
            acquire_timeout=10,
            operation_timeout=20,
        )
        async with aiosqlite.connect(str(path), isolation_level=None) as outside:
            assert_eq(await outside.execute_fetchall("PRAGMA page_size=4096"), [])
            assert_eq(
                await outside.execute_fetchall("PRAGMA journal_mode=WAL"), [("wal",)]
            )
            await _apply(deploy, payload, "001_accounts.json")
            await outside.execute("INSERT INTO accounts VALUES(1,1),(2,0)")
            await _apply(deploy, payload, "002_expand.json")
            await outside.execute(
                "CREATE TABLE audit_workload(id INTEGER PRIMARY KEY) STRICT"
            )
            await outside.execute(
                f"INSERT INTO audit_workload WITH RECURSIVE n(id) AS (VALUES(1) UNION ALL SELECT id+1 FROM n WHERE id<{_WORKLOAD}) SELECT id FROM n"
            )
            await outside.execute(
                "CREATE TABLE role_audit(id INTEGER PRIMARY KEY,account_id INTEGER,piece INTEGER,detail BLOB,sync INTEGER) STRICT"
            )
            await outside.execute(
                "INSERT INTO role_audit VALUES(0,99,-1,x'6b657074',0)"
            )
            await outside.execute(
                "CREATE TRIGGER audit_role AFTER UPDATE OF role ON accounts WHEN NEW.id=1 AND NEW.role='user' BEGIN INSERT INTO role_audit SELECT id,NEW.id,id,zeroblob(512),(SELECT synchronous FROM pragma_synchronous) FROM audit_workload ORDER BY id; END"
            )
            roles = m.Package.load((deploy / "003_roles.json").read_text())
            packages = [p.read_bytes() for p in sorted(deploy.glob("*.json"))]
            async with m.connect(config) as target:
                original = await target.prepare(roles, preserve_unmanaged=True)
                wire = original.dump()
            await asyncio.to_thread(_save_original, deploy / "original-plan.json", wire)
            before = await outside.execute_fetchall(
                "SELECT * FROM snekql_experimental_migrations ORDER BY revision"
            )
            objects = await outside.execute_fetchall(
                "SELECT type,name,sql FROM sqlite_schema WHERE name IN ('role_audit','audit_workload','audit_role') ORDER BY name"
            )
            assert_eq(
                await outside.execute_fetchall("PRAGMA wal_checkpoint(TRUNCATE)"),
                [(0, 0, 0)],
            )
            await outside.execute("BEGIN")
            assert_eq(
                await outside.execute_fetchall(
                    "SELECT id,is_admin,role FROM accounts ORDER BY id"
                ),
                [(1, 1, None), (2, 0, None)],
            )
            worker = await _start(deploy / "wal_worker.py", payload)
            wal = Path(str(path) + "-wal")
            try:
                _go(worker)
                async with asyncio.timeout(10):
                    while await asyncio.to_thread(_wal_size, wal) < 131_072:
                        assert worker.returncode is None
                        await asyncio.sleep(0.001)
                os.kill(worker.pid, signal.SIGSTOP)
                async with asyncio.timeout(5):
                    while not await asyncio.to_thread(_stopped, worker.pid):  # noqa: ASYNC110 - actual OS process stop, no asyncio event exists
                        await asyncio.sleep(0.001)
                spill = await asyncio.to_thread(_spill, wal)
                assert_eq(spill["sync_values"], [sync])
                assert (
                    isinstance(spill["bytes"], int)
                    and spill["bytes"] < _WORKLOAD * 512 // 2
                )  # Stop in the early spill, not a completed audit.
                assert_eq(
                    await outside.execute_fetchall("SELECT COUNT(*) FROM role_audit"),
                    [(1,)],
                )
                async with aiosqlite.connect(
                    str(path), isolation_level=None
                ) as independent:
                    assert_eq(
                        await independent.execute_fetchall(
                            "SELECT id,is_admin,role FROM accounts ORDER BY id"
                        ),
                        [(1, 1, None), (2, 0, None)],
                    )
                    assert_eq(
                        await independent.execute_fetchall(
                            "SELECT * FROM snekql_experimental_migrations ORDER BY revision"
                        ),
                        before,
                    )
                worker.kill()
                await worker.wait()
                assert_eq(worker.returncode, -signal.SIGKILL)
                stdout, stderr = await worker.communicate()
                assert_eq(
                    stdout, b"", msg="interrupted caller already reported success"
                )
                assert b"ResourceWarning" not in stderr
            finally:
                await _stop(worker)
            async with aiosqlite.connect(
                str(path), isolation_level=None
            ) as independent:
                assert_eq(
                    await independent.execute_fetchall("PRAGMA journal_mode"),
                    [("wal",)],
                )
                assert_eq(
                    await independent.execute_fetchall("PRAGMA integrity_check"),
                    [("ok",)],
                )
                assert_eq(
                    await independent.execute_fetchall(
                        "SELECT id,is_admin,role FROM accounts ORDER BY id"
                    ),
                    [(1, 1, None), (2, 0, None)],
                )
                assert_eq(
                    await independent.execute_fetchall(
                        "SELECT * FROM snekql_experimental_migrations ORDER BY revision"
                    ),
                    before,
                )
                assert_eq(
                    await independent.execute_fetchall("SELECT * FROM role_audit"),
                    [(0, 99, -1, b"kept", 0)],
                )
            async with m.connect(config) as target:
                assert_eq(
                    sorted((p.revision, p.phase) for p in await target.status()),
                    [("001_accounts", "complete"), ("002_expand", "complete")],
                )
            fresh = await _start(deploy / "wal_worker.py", payload)
            _go(fresh)
            assert_eq((await _finish(fresh))["outcome"], "applied")
            # WAL readers don't block this writer COMMIT or gain new snapshot visibility.
            assert_eq(
                await outside.execute_fetchall(
                    "SELECT id,is_admin,role FROM accounts ORDER BY id"
                ),
                [(1, 1, None), (2, 0, None)],
            )
            await outside.rollback()
            assert_eq(
                await outside.execute_fetchall(
                    "SELECT COUNT(*),MIN(sync),MAX(sync) FROM role_audit WHERE id>0"
                ),
                [(_WORKLOAD, sync, sync)],
            )
            assert_eq(
                await outside.execute_fetchall(
                    "SELECT COUNT(*),MIN(id),MAX(id) FROM audit_workload"
                ),
                [(_WORKLOAD, 1, _WORKLOAD)],
            )
            assert_eq(
                await outside.execute_fetchall("SELECT * FROM role_audit WHERE id=0"),
                [(0, 99, -1, b"kept", 0)],
            )
            assert_eq(
                await outside.execute_fetchall(
                    "SELECT * FROM snekql_experimental_migrations WHERE revision IN ('001_accounts','002_expand') ORDER BY revision"
                ),
                before,
            )
            assert_eq(
                await outside.execute_fetchall(
                    "SELECT type,name,sql FROM sqlite_schema WHERE name IN ('role_audit','audit_workload','audit_role') ORDER BY name"
                ),
                objects,
            )
            async with m.connect(config) as target:
                assert_eq(await target.apply(m.Prepared.load(wire)), "already_applied")
                assert_eq(
                    sorted((p.revision, p.phase) for p in await target.status()),
                    [
                        ("001_accounts", "complete"),
                        ("002_expand", "complete"),
                        ("003_roles", "complete"),
                    ],
                )
            assert_eq(await outside.execute_fetchall("PRAGMA journal_mode"), [("wal",)])
        assert_eq(
            json.loads(await _python(deploy / "app.py", payload)),
            {"before": [[1, "admin"], [2, "user"]], "created": [3, "user"]},
        )
        assert_eq((deploy / "original-plan.json").read_text(), wire)
        assert_eq(
            [
                p.read_bytes()
                for p in sorted(deploy.glob("*.json"))
                if p.name != "original-plan.json"
            ],
            packages,
        )

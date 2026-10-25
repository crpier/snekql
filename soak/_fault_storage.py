"""Real ENOSPC in a bounded, process-owned private user/mount namespace."""

import asyncio
import errno
import json
import os
import sys
from dataclasses import asdict
from pathlib import Path
from sqlite3 import SQLITE_FULL
from tempfile import TemporaryDirectory
from typing import Any

from anyio import run_process

from snekql import sqlite
from soak._service_evidence import emit
from soak._service_workload import require

FILESYSTEM_BYTES = 4 * 1024 * 1024
PARENT_NAMESPACE_ARGUMENTS = 2


class NamespaceUnavailableError(RuntimeError):
    """Required isolation cannot be established; no storage pass is possible."""


def _namespaces() -> list[str]:
    return [
        str(Path("/proc/self/ns/user").readlink()),
        str(Path("/proc/self/ns/mnt").readlink()),
    ]


async def storage_full() -> dict[str, Any]:
    """Delegate to an owned kill-on-parent-exit namespace; never use host mounts."""
    command = [
        "unshare",
        "--user",
        "--map-root-user",
        "--mount",
        "--propagation",
        "private",
        "--fork",
        "--kill-child=KILL",
    ]
    try:
        probe = await run_process([*command, "true"], check=False)
    except FileNotFoundError as error:
        message = "unshare is required for the isolated storage drill"
        raise NamespaceUnavailableError(message) from error
    if probe.returncode != 0:
        message = "private user/mount namespaces unavailable"
        raise NamespaceUnavailableError(message)
    before = await asyncio.to_thread(_namespaces)
    async with asyncio.timeout(30):
        result = await run_process(
            [*command, sys.executable, "-m", "soak._fault_storage", *before],
            check=False,
        )
    records = [json.loads(line) for line in result.stdout.splitlines()]
    for record in records:
        if record["kind"] in ("fault", "engine"):
            print(json.dumps(record), flush=True)
    if result.returncode != 0:
        if records and records[-1].get("error_type") == "NamespaceUnavailableError":
            message = "private tmpfs mount unavailable"
            raise NamespaceUnavailableError(message)
        sys.stderr.buffer.write(result.stderr)
        message = "isolated storage child failed"
        raise RuntimeError(message)
    require(
        bool(records) and records[-1]["kind"] == "summary",
        "storage child lacked completion",
    )
    report = records[-1]
    require(report.pop("status") == "passed", "storage child did not pass")
    report.pop("kind")
    report.pop("schema_version")
    return report


async def _exercise(path: Path) -> dict[str, Any]:
    async with await sqlite.Database.initialize(
        sqlite.Config(
            database=path / "fault.db",
            pool_size=1,
            durability="full",
            operation_timeout=5,
        )
    ) as database:
        async with database.transaction() as setup:
            version = await setup.fetch_one(
                sqlite.raw("SELECT sqlite_version() AS version")
            )
            emit(
                "engine",
                backend="sqlite",
                version=version["version"],
                pool_size=1,
                transaction_timeout=5,
                acquire_timeout=30,
                durability="full",
            )
            await setup.execute(
                sqlite.raw(
                    "CREATE TABLE fault_storage (id INTEGER PRIMARY KEY, payload BLOB NOT NULL)"
                )
            )
            await setup.execute(
                sqlite.raw("INSERT INTO fault_storage VALUES (1, zeroblob(16))")
            )
        filler = path / "filler"
        os_errno = None
        with filler.open("wb", buffering=0) as handle:
            for _ in range(2 * FILESYSTEM_BYTES // 65536):
                try:
                    handle.write(b"f" * 65536)
                except OSError as error:
                    os_errno = error.errno
                    break
        require(os_errno == errno.ENOSPC, "filler did not observe real ENOSPC")
        filesystem = os.statvfs(path)
        require(filesystem.f_bavail == 0, "filesystem was not actually full")
        emit(
            "fault",
            scenario="sqlite-full",
            os_errno=os_errno,
            filesystem="tmpfs",
            filesystem_bytes=filesystem.f_blocks * filesystem.f_frsize,
            user_namespace_isolated=True,
            mount_namespace_isolated=True,
            child_pid=os.getpid(),
        )
        transaction = database.transaction()
        native_code = None
        try:
            async with transaction:
                await transaction.execute(
                    sqlite.raw(
                        "INSERT INTO fault_storage VALUES (2, zeroblob(1048576))"
                    )
                )
        except sqlite.DatabaseRuntimeError as error:
            native_code = error.failure.code if error.failure else None
        finally:
            filler.unlink()
        require(native_code == SQLITE_FULL, "SQLite did not report SQLITE_FULL")
        # Unsafe SQLite handles remain owned until detached physical close ends.
        async with asyncio.timeout(5):
            while database.pool_stats().occupied:  # noqa: ASYNC110 -- public stats have no completion event
                await asyncio.sleep(0.001)
        drained = database.pool_stats()
        require(drained.waiters == 0, "full-filesystem transaction did not drain")
        async with database.transaction() as observer:
            rows = await observer.fetch_all(
                sqlite.raw("SELECT id FROM fault_storage ORDER BY id")
            )
        require(rows == [{"id": 1}], "failed atomic write changed durable rows")
        async with database.transaction() as fresh:
            await fresh.execute(
                sqlite.raw("INSERT INTO fault_storage VALUES (3, zeroblob(16))")
            )
        async with database.transaction() as observer:
            recovered = await observer.fetch_all(
                sqlite.raw("SELECT id FROM fault_storage ORDER BY id")
            )
        require(
            recovered == [{"id": 1}, {"id": 3}],
            "fresh write did not persist after freeing space",
        )
    closed = database.pool_stats()
    require(closed.state == "closed", "storage pool did not close")
    return {
        "sqlite_errorcode": native_code,
        "commit_outcome": transaction.commit_outcome,
        "reconciled_ids": [row["id"] for row in rows],
        "recovered_ids": [row["id"] for row in recovered],
        "drained_pool": asdict(drained),
        "closed_pool": asdict(closed),
        "recovery_verified": True,
        "child_pid": os.getpid(),
    }


async def _child() -> None:
    require(
        len(sys.argv[1:]) == PARENT_NAMESPACE_ARGUMENTS,
        "private worker requires parent namespace identities",
    )
    identities = await asyncio.to_thread(_namespaces)
    require(
        identities[0] != sys.argv[1],
        "user namespace did not change",
    )
    require(
        identities[1] != sys.argv[2],
        "mount namespace did not change",
    )
    with TemporaryDirectory(prefix="snekql-private-full-") as directory:
        path = Path(directory)
        result = await run_process(
            ["mount", "-t", "tmpfs", "-o", "size=4m", "tmpfs", directory], check=False
        )
        if result.returncode != 0:
            message = "private tmpfs mount was refused"
            raise NamespaceUnavailableError(message)
        try:
            report = await _exercise(path)
        finally:
            await run_process(["umount", directory])
        emit("summary", status="passed", **report)


if __name__ == "__main__":
    try:
        asyncio.run(_child())
    except Exception as error:
        emit("failure", status="failed", error_type=type(error).__name__)
        raise

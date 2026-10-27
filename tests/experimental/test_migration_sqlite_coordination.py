"""Known SQLite writer refusal is not interrupted, unsafe driver I/O."""

import asyncio
import time
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Literal

import aiosqlite
import anyio
from snektest import Param, assert_eq, assert_raises, test

from snekql import sqlite
from snekql.errors import DatabaseOperationTimeoutError, MigrationLockTimeoutError
from snekql.experimental import migrations as m
from tests.experimental.test_migration_io_deadlines import (
    Account,
    _observe_physical_disposal,
)
from tests.experimental.test_migration_local_guard import _cancel_pending
from tests.experimental.test_migration_prepared_evidence import Initial


@test(
    [
        Param[Literal["refusal", "grant", "operation", "task", "scope"]](
            value="refusal", name="refusal"
        ),
        Param[Literal["refusal", "grant", "operation", "task", "scope"]](
            value="grant", name="grant"
        ),
        Param[Literal["refusal", "grant", "operation", "task", "scope"]](
            value="operation", name="operation"
        ),
        Param[Literal["refusal", "grant", "operation", "task", "scope"]](
            value="task", name="task"
        ),
        Param[Literal["refusal", "grant", "operation", "task", "scope"]](
            value="scope", name="scope"
        ),
    ],
    mark="medium",
)
async def writer_wait_disposition_preserves_original_role_evidence(  # noqa: PLR0915 - keep the consumer lifecycle and disposal ordering visible
    mode: Literal["refusal", "grant", "operation", "task", "scope"],
) -> None:
    """Known refusal permits reuse; interrupted waits require actual disposal."""
    with TemporaryDirectory() as directory:
        path = Path(directory) / "app.db"
        config = sqlite.Config(
            database=path,
            acquire_timeout=0.2 if mode == "refusal" else 2,
            operation_timeout=0.15 if mode == "operation" else 3,
        )
        fixed = Path(__file__).parent / "fixtures" / "role-interruption" / "sqlite"
        first = m.Package.load((fixed / "001_accounts.json").read_text())
        expansion = m.Package.load((fixed / "002_expand.json").read_text())
        roles = m.Package.load((fixed / "003_roles.json").read_text())
        originals = [p.dump() for p in (first, expansion, roles)]
        async with m.connect(config) as target:
            assert_eq(await target.apply(await target.prepare(first)), "applied")
        async with (
            await sqlite.Database.initialize(config) as app,
            app.transaction() as tx,
        ):
            await tx.execute(
                sqlite.insert_many(
                    Initial,
                    [Initial(id=1, is_admin=True), Initial(id=2, is_admin=False)],
                )
            )
        async with aiosqlite.connect(str(path), isolation_level=None) as writer:
            async with writer.execute("PRAGMA journal_mode=DELETE") as cursor:
                assert_eq(await cursor.fetchall(), [("delete",)])
            prior_threads = _thread_ids()
            async with m.connect(config) as target:
                threads = _thread_ids() - prior_threads
                assert_eq(len(threads), 1)
                worker = threads.pop()
                assert_eq(
                    await target.apply(await target.prepare(expansion)), "applied"
                )
                original = await target.prepare(roles)
                wire = original.dump()
                before = sorted(await target.status(), key=lambda p: p.revision)
                await writer.execute("BEGIN IMMEDIATE")
                scope = anyio.CancelScope()

                async def compete() -> str | None:
                    with scope:
                        return await target.apply(m.Prepared.load(wire))
                    return None

                started = time.perf_counter()
                applying = asyncio.create_task(compete())
                try:
                    await _wait_busy_worker(worker)
                    if mode == "grant":
                        await writer.rollback()
                        assert_eq(await applying, "applied")
                    elif mode == "refusal":
                        with assert_raises(MigrationLockTimeoutError) as refused:
                            await applying
                        elapsed = time.perf_counter() - started
                        assert "SQLite writer" in str(refused.exception)
                        assert elapsed >= 0.15, (
                            "SQLite writer acquisition budget truncated"
                        )
                        assert elapsed < 1, "SQLite writer acquisition budget ignored"
                        assert_eq(
                            sorted(await target.status(), key=lambda p: p.revision),
                            before,
                        )
                    else:
                        if mode == "operation":
                            with assert_raises(
                                DatabaseOperationTimeoutError
                            ) as expired:
                                await applying
                            assert_eq(expired.exception.operation, "migration execute")
                            assert_eq(expired.exception.timeout, 0.15)
                        elif mode == "task":
                            applying.cancel()
                            with assert_raises(asyncio.CancelledError):
                                await applying
                        else:
                            scope.cancel()
                            await applying
                            assert scope.cancelled_caught
                        with assert_raises(m.PackageError) as closed:
                            await target.status()
                        assert "migration target is closed" in str(closed.exception)
                    assert_eq(original.dump(), wire)
                finally:
                    await writer.rollback()
                    await _cancel_pending(applying)
                if mode in {"refusal", "grant"}:
                    assert_eq(
                        await target.apply(m.Prepared.load(wire)),
                        "already_applied" if mode == "grant" else "applied",
                    )
                    assert_eq(
                        await target.apply(m.Prepared.load(wire)), "already_applied"
                    )
        # Neither caller cancellation nor interrupt() proves the busy worker stopped.
        await _observe_physical_disposal(path)
        async with m.connect(config) as fresh:
            if mode not in {"refusal", "grant"}:
                assert_eq(
                    sorted(await fresh.status(), key=lambda p: p.revision), before
                )
                assert_eq(await fresh.apply(m.Prepared.load(wire)), "applied")
            assert_eq(await fresh.apply(m.Prepared.load(wire)), "already_applied")
            assert_eq(
                sorted((p.revision, p.phase) for p in await fresh.status()),
                [
                    ("001_accounts", "complete"),
                    ("002_expand", "complete"),
                    ("003_roles", "complete"),
                ],
            )
        async with (
            await sqlite.Database.initialize(config) as app,
            app.transaction() as tx,
        ):
            await tx.execute(sqlite.insert(Account(id=3, role="user")))
            rows = await tx.fetch_all(sqlite.select(Account).order_by(Account.id.asc()))
        assert_eq(
            [(r.id, r.role) for r in rows], [(1, "admin"), (2, "user"), (3, "user")]
        )
        assert_eq([p.dump() for p in (first, expansion, roles)], originals)


def _thread_ids() -> set[int]:
    """Observe actual Linux workers; never inspect the driver/target's private state."""
    return {int(path.name) for path in Path("/proc/self/task").iterdir()}


async def _wait_busy_worker(worker: int) -> None:
    """Observe the owned worker in SQLite busy-handler sleep, not a fake lock."""
    path = Path(f"/proc/self/task/{worker}/wchan")
    async with asyncio.timeout(1):
        while True:
            if (await asyncio.to_thread(path.read_text)).strip() == "hrtimer_nanosleep":
                return
            await asyncio.sleep(0.005)

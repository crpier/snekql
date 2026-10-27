"""Context exit must observe retained physical close without unsafe policy SQL."""

import asyncio
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Literal

import aiosqlite
import anyio
from snektest import Param, assert_eq, assert_raises, test

from snekql import sqlite
from snekql.experimental import migrations as m
from tests.experimental.test_migration_io_deadlines import Account
from tests.experimental.test_migration_local_guard import _cancel_pending
from tests.experimental.test_migration_prepared_evidence import Initial
from tests.experimental.test_migration_sqlite_coordination import (
    _thread_ids,
    _wait_busy_worker,
)


@test(
    [
        Param[Literal["finish", "deadline", "primary", "task", "scope"]](
            value=mode, name=mode
        )
        for mode in ("finish", "deadline", "primary", "task", "scope")
    ],
    mark="medium",
)
async def context_exit_joins_retained_sqlite_close_after_io_timeout(  # noqa: C901, PLR0912, PLR0915 - real worker/receipt/lifetime ordering
    mode: Literal["finish", "deadline", "primary", "task", "scope"],
) -> None:
    """Successful exit must not silently leave this Target's known close unobserved."""
    with TemporaryDirectory() as directory:
        path = Path(directory) / "app.db"
        config = sqlite.Config(database=path, acquire_timeout=3, operation_timeout=0.15)
        fixed = Path(__file__).parent / "fixtures/role-interruption/sqlite"
        packages = [
            m.Package.load((fixed / name).read_text())
            for name in ("001_accounts.json", "002_expand.json", "003_roles.json")
        ]
        first, expansion, roles = packages
        originals = [p.dump() for p in packages]
        async with m.connect(config) as target:
            await target.apply(await target.prepare(first))
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
        async with m.connect(config) as target:
            await target.apply(await target.prepare(expansion))
            original = await target.prepare(roles)
            wire = original.dump()
        async with aiosqlite.connect(str(path), isolation_level=None) as writer:
            await writer.execute("PRAGMA journal_mode=DELETE")
            before = list(
                await writer.execute_fetchall(
                    "SELECT * FROM snekql_experimental_migrations ORDER BY revision"
                )
            )
            await writer.execute("BEGIN IMMEDIATE")
            prior = _thread_ids()
            opened = asyncio.Future[m.Target]()
            failed = asyncio.Future[sqlite.DatabaseOperationTimeoutError]()
            leave = asyncio.Event()

            scope = anyio.CancelScope()
            lifetime = m.connect(config)

            async def context() -> None:
                """Caller chooses error handling; lifetime joins cleanup, not policy SQL."""
                with scope:
                    async with lifetime as target:
                        opened.set_result(target)
                        try:
                            await target.apply(m.Prepared.load(wire))
                        except sqlite.DatabaseOperationTimeoutError as error:
                            failed.set_result(error)
                            await leave.wait()
                            if mode == "primary":
                                raise

            closing = asyncio.create_task(context())
            target = await opened
            workers = _thread_ids() - prior
            assert_eq(len(workers), 1)
            worker = workers.pop()
            try:
                await _wait_busy_worker(worker)
                error = await asyncio.wait_for(failed, 2)
                assert_eq((error.operation, error.timeout), ("migration execute", 0.15))
                with assert_raises(m.PackageError):
                    await target.status()
                await _wait_busy_worker(worker)
                if mode == "scope":
                    scope.cancel()
                else:
                    leave.set()
                await asyncio.wait({closing}, timeout=0.03)
                assert_eq(
                    closing.done(),
                    False,
                    msg="context exit skipped retained physical cleanup",
                )
                if mode == "finish":
                    await writer.rollback()
                    await closing
                elif mode == "task":
                    closing.cancel()
                    with assert_raises(asyncio.CancelledError):
                        await closing
                elif mode == "scope":
                    await closing
                    assert scope.cancelled_caught
                else:
                    with assert_raises(sqlite.DatabaseOperationTimeoutError) as expired:
                        await closing
                    if mode == "primary":
                        assert expired.exception is error
                    else:
                        assert_eq(
                            (expired.exception.operation, expired.exception.timeout),
                            ("migration close", 0.15),
                        )
                if mode != "finish":
                    # Caller return/cleanup expiry is NOT physical worker quiescence.
                    await _wait_busy_worker(worker)
                    with assert_raises(sqlite.DatabaseOperationTimeoutError) as joined:
                        await lifetime.wait_closed()
                    assert_eq(
                        (joined.exception.operation, joined.exception.timeout),
                        ("migration close", 0.15),
                    )
                    await _wait_busy_worker(worker)
                waiting: asyncio.Task[None] | None = None
                if mode != "finish":
                    waiting = asyncio.create_task(lifetime.wait_closed())
                    cancelled = asyncio.create_task(lifetime.wait_closed())
                    await asyncio.wait({waiting, cancelled}, timeout=0.02)
                    assert not waiting.done() and not cancelled.done()
                    cancelled.cancel()
                    with assert_raises(asyncio.CancelledError):
                        await cancelled
                    if mode == "scope":
                        with anyio.CancelScope() as cancelled_wait:
                            cancelled_wait.cancel()
                            await lifetime.wait_closed()
                        assert cancelled_wait.cancelled_caught
                    assert not waiting.done(), "one waiter cancelled another's cleanup"
                await writer.rollback()
                if waiting is not None:
                    await waiting
                await lifetime.wait_closed()
                await lifetime.wait_closed()
                # Physical worker disappearance, not logical Target.closed or a sleep.
                async with asyncio.timeout(3):
                    while await asyncio.to_thread(  # noqa: ASYNC110 - observe external OS worker, no asyncio event exists
                        Path(f"/proc/self/task/{worker}").exists
                    ):
                        await asyncio.sleep(0.01)
                assert_eq(
                    list(
                        await writer.execute_fetchall(
                            "SELECT * FROM snekql_experimental_migrations ORDER BY revision"
                        )
                    ),
                    before,
                )
                assert_eq(
                    list(
                        await writer.execute_fetchall(
                            "SELECT id,is_admin,role FROM accounts ORDER BY id"
                        )
                    ),
                    [(1, 1, None), (2, 0, None)],
                )
            finally:
                leave.set()
                await writer.rollback()
                await _cancel_pending(closing)
        async with m.connect(config) as fresh:
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
        assert_eq(original.dump(), wire)
        assert_eq([p.dump() for p in packages], originals)

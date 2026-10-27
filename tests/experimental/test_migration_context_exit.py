"""Target context exit drains an active caller operation before physical close."""

import asyncio
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Literal

import aiomysql
import aiosqlite
from snektest import Param, assert_eq, assert_raises, load_fixture, test

from snekql import mariadb, sqlite
from snekql.experimental import migrations as m
from tests.experimental.test_migration_io_deadlines import (
    Account,
    NativeAccount,
    NativeInitial,
    _observe_physical_disposal,
)
from tests.experimental.test_migration_local_guard import _cancel_pending
from tests.experimental.test_migration_prepared_evidence import Initial
from tests.experimental.test_migration_role_interruption import (
    _wait_disconnected,
    _waiting_update,
)
from tests.experimental.test_migration_sqlite_coordination import (
    _thread_ids,
    _wait_busy_worker,
)
from tests.experimental.test_migration_targets import provide_package_server


@test(
    [
        Param[Literal["finish", "deadline", "task", "primary"]](
            value="finish", name="finish"
        ),
        Param[Literal["finish", "deadline", "task", "primary"]](
            value="deadline", name="deadline"
        ),
        Param[Literal["finish", "deadline", "task", "primary"]](
            value="task", name="task"
        ),
        Param[Literal["finish", "deadline", "task", "primary"]](
            value="primary", name="primary"
        ),
    ],
    mark="slow",
)
async def context_exit_drains_or_discards_original_role_work(  # noqa: PLR0915 - keep ownership and evidence lifecycle visible
    mode: Literal["finish", "deadline", "task", "primary"],
) -> None:
    """Closing admission must not abruptly disconnect a still-owned successful apply."""
    server = await load_fixture(provide_package_server())
    config = server.config()
    fixed = Path(__file__).parent / "fixtures" / "role-interruption" / "mariadb"
    packages = [
        m.Package.load((fixed / name).read_text())
        for name in ("001_accounts.json", "002_expand.json", "003_roles.json")
    ]
    first, expansion, roles = packages
    originals = [package.dump() for package in packages]
    async with m.connect(config) as target:
        await target.apply(await target.prepare(first, schema_writers_excluded=True))
    async with (
        await mariadb.Database.initialize(config) as app,
        app.transaction() as tx,
    ):
        await tx.execute(
            mariadb.insert_many(
                NativeInitial,
                [
                    NativeInitial(id=1, is_admin=True),
                    NativeInitial(id=2, is_admin=False),
                ],
            )
        )
    async with m.connect(config) as target:
        await target.apply(
            await target.prepare(expansion, schema_writers_excluded=True)
        )
        original = await target.prepare(roles, schema_writers_excluded=True)
        wire = original.dump()
    observer = await aiomysql.connect(
        unix_socket=str(config.unix_socket),
        user=config.user,
        password=config.password,
        db=config.database,
        autocommit=True,
    )
    blocker = await aiomysql.connect(
        unix_socket=str(config.unix_socket),
        user=config.user,
        password=config.password,
        db=config.database,
        autocommit=False,
    )
    applying: asyncio.Task[str] | None = None
    closing: asyncio.Task[None] | None = None
    opened = asyncio.Future[m.Target]()
    leave = asyncio.Event()
    primary = RuntimeError("caller primary failure")
    queued: asyncio.Task[tuple[m.Progress, ...]] | None = None

    async def context() -> None:
        """Caller owns the apply task; the context owns connection shutdown only."""
        async with m.connect(
            replace(
                config,
                acquire_timeout=0.15 if mode in {"deadline", "primary"} else 2,
                operation_timeout=10,
            )
        ) as target:
            opened.set_result(target)
            await leave.wait()
            if mode == "primary":
                raise primary

    try:
        async with observer.cursor() as cursor:
            await cursor.execute(
                "SELECT * FROM snekql_experimental_migrations ORDER BY revision"
            )
            before = await cursor.fetchall()
        async with blocker.cursor() as cursor:
            await cursor.execute("SELECT id FROM accounts WHERE id=2 FOR UPDATE")
        closing = asyncio.create_task(context())
        target = await opened
        applying = asyncio.create_task(target.apply(m.Prepared.load(wire)))
        observed = await _waiting_update(config)
        assert observed["modified"] >= 1
        if mode == "finish":
            queued = asyncio.create_task(target.status())
            await asyncio.sleep(0)
            assert_eq(queued.done(), False)
        leave.set()
        await asyncio.wait({closing}, timeout=0.05)
        assert_eq(
            closing.done(),
            False,
            msg="context exit discarded active original role work instead of draining",
        )
        assert_eq(applying.done(), False)
        with assert_raises(m.PackageError) as error:
            await target.status()
        assert "closing" in str(error.exception)
        if mode == "finish":
            assert_eq((await _waiting_update(config))["id"], observed["id"])
            await blocker.rollback()
            assert_eq(await applying, "applied")
            await closing
            assert queued is not None
            with assert_raises(m.PackageError) as queued_error:
                await queued
            assert "closing" in str(queued_error.exception)
        else:
            if mode == "task":
                closing.cancel()
                with assert_raises(asyncio.CancelledError):
                    await closing
                done, _ = await asyncio.wait({applying}, timeout=0.8)
                assert_eq(
                    bool(done),
                    True,
                    msg="cancelled shutdown left the active session admitted",
                )
            else:
                done, _ = await asyncio.wait({closing}, timeout=0.8)
                assert_eq(
                    bool(done),
                    True,
                    msg="context exit drain acquisition deadline ignored",
                )
                if mode == "primary":
                    with assert_raises(RuntimeError) as caller_error:
                        await closing
                    assert caller_error.exception is primary
                else:
                    with assert_raises(mariadb.PoolTimeoutError) as timeout:
                        await closing
                    assert "shutdown guard" in str(timeout.exception)
            result = await asyncio.gather(applying, return_exceptions=True)
            assert isinstance(result[0], Exception)
            assert_eq(applying.cancelled(), False)
        # Closing the client is not physical interruption of a server row-lock wait.
        await blocker.rollback()
        await _wait_disconnected(config, observed["id"])
        with assert_raises(m.PackageError):
            await target.status()
        async with m.connect(config) as fresh:
            if mode != "finish":
                progress = next(
                    p for p in await fresh.status() if p.revision == "003_roles"
                )
                assert_eq(
                    (progress.phase, progress.acknowledged_steps), ("uncertain", 0)
                )
                async with observer.cursor() as cursor:
                    await cursor.execute(
                        "SELECT id,is_admin,role FROM accounts ORDER BY id"
                    )
                    assert_eq(await cursor.fetchall(), ((1, 1, None), (2, 0, None)))
                with assert_raises(m.PackageError):
                    await fresh.apply(m.Prepared.load(wire))
                recovery = await fresh.inspect_recovery(
                    m.Prepared.load(wire), schema_writers_excluded=True
                )
                assert_eq(
                    (recovery.disposition, recovery.acknowledged_steps),
                    ("retry_remaining", 0),
                )
                assert_eq(
                    await fresh.resume(recovery, schema_writers_excluded=True),
                    "applied",
                )
            assert_eq(await fresh.apply(m.Prepared.load(wire)), "already_applied")
            assert_eq(
                sorted((p.revision, p.phase) for p in await fresh.status()),
                [
                    ("001_accounts", "complete"),
                    ("002_expand", "complete"),
                    ("003_roles", "complete"),
                ],
            )
        async with observer.cursor() as cursor:
            await cursor.execute(
                "SELECT * FROM snekql_experimental_migrations ORDER BY revision"
            )
            after = await cursor.fetchall()
            assert_eq(after[: len(before)], before)
        async with (
            await mariadb.Database.initialize(config) as app,
            app.transaction() as tx,
        ):
            await tx.execute(mariadb.insert(NativeAccount(id=3, role="user")))
            rows = await tx.fetch_all(
                mariadb.select(NativeAccount).order_by(NativeAccount.id.asc())
            )
        assert_eq(
            [(row.id, row.role) for row in rows],
            [(1, "admin"), (2, "user"), (3, "user")],
        )
        assert_eq(original.dump(), wire)
        assert_eq([package.dump() for package in packages], originals)
    finally:
        await blocker.rollback()
        await _cancel_pending(applying)
        await _cancel_pending(closing)
        await _cancel_pending(queued)
        leave.set()
        blocker.close()
        observer.close()


@test(mark="medium")
async def sqlite_context_exit_drains_original_role_work_before_worker_close() -> None:  # noqa: PLR0915 - real worker, unchanged plan, normal typed application
    """SQLite shutdown must drain the guard, not queue physical close behind active SQL."""
    with TemporaryDirectory() as directory:
        path = Path(directory) / "app.db"
        config = sqlite.Config(database=path, acquire_timeout=2, operation_timeout=10)
        fixed = Path(__file__).parent / "fixtures" / "role-interruption" / "sqlite"
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
            opened = asyncio.Future[m.Target]()
            leave = asyncio.Event()
            prior_threads = _thread_ids()

            async def context() -> None:
                """Caller owns the apply task; context exits while BEGIN really waits."""
                async with m.connect(config) as target:
                    opened.set_result(target)
                    await leave.wait()

            closing = asyncio.create_task(context())
            target = await opened
            workers = _thread_ids() - prior_threads
            assert_eq(len(workers), 1)
            applying = asyncio.create_task(target.apply(m.Prepared.load(wire)))
            try:
                await _wait_busy_worker(workers.pop())
                leave.set()
                await asyncio.wait({closing}, timeout=0.05)
                assert_eq(closing.done(), False)
                assert_eq(applying.done(), False)
                with assert_raises(m.PackageError) as error:
                    await target.status()
                assert "closing" in str(error.exception)
                await writer.rollback()
                assert_eq(await applying, "applied")
                await closing
                after = list(
                    await writer.execute_fetchall(
                        "SELECT * FROM snekql_experimental_migrations ORDER BY revision"
                    )
                )
                assert_eq(after[: len(before)], before)
            finally:
                await writer.rollback()
                leave.set()
                await _cancel_pending(applying)
                await _cancel_pending(closing)
        await _observe_physical_disposal(path)
        async with m.connect(config) as fresh:
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
            [(row.id, row.role) for row in rows],
            [(1, "admin"), (2, "user"), (3, "user")],
        )
        assert_eq(original.dump(), wire)
        assert_eq([p.dump() for p in packages], originals)

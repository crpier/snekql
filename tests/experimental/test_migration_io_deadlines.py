"""Configured migration driver deadlines preserve truthful stopped outcomes."""

import asyncio
from contextlib import suppress
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import ClassVar, Literal

import aiomysql
import aiosqlite
import anyio
from snektest import Param, assert_eq, assert_raises, load_fixture, test

from snekql import mariadb, sqlite
from snekql.experimental import migrations as m
from tests.experimental.test_migration_prepared_evidence import Initial
from tests.experimental.test_migration_role_interruption import (
    _wait_disconnected,
    _waiting_update,
)
from tests.experimental.test_migration_targets import provide_package_server


class Account[S = sqlite.Pending](sqlite.Model[S]):
    """An ordinary role mapping, independently selected for migration ownership."""

    __tablename__: ClassVar[str] = "accounts"
    __row_type__: ClassVar[sqlite.ReadType[Account[sqlite.Row]]]
    id: sqlite.Col[int] = sqlite.Integer(primary_key=True)
    role: sqlite.Col[str] = sqlite.Text()


@test(mark="medium")
async def blocked_sqlite_begin_times_out_discards_target_and_never_applies_later() -> (
    None
):
    """An expired waiter cannot resume package work when a competing writer releases."""
    with TemporaryDirectory() as directory:
        path = Path(directory) / "app.db"
        package = m.compile(m.generate("001_accounts", [Account], backend="sqlite"))
        config = sqlite.Config(database=path, acquire_timeout=3, operation_timeout=0.15)
        async with (
            aiosqlite.connect(str(path), isolation_level=None) as blocker,
            m.connect(config) as target,
        ):
            original = await target.prepare(package)
            wire = original.dump()
            await blocker.execute("BEGIN IMMEDIATE")
            applying = asyncio.create_task(target.apply(original))
            try:
                # A watchdog only detects missing library deadlines; it does NOT
                # cancel the worker or serve as proof of rollback/physical close.
                done, _ = await asyncio.wait({applying}, timeout=1)
                assert_eq(bool(done), True, msg="configured operation deadline ignored")
                with assert_raises(sqlite.DatabaseOperationTimeoutError):
                    await applying
                assert_eq(original.dump(), wire)
                with assert_raises(m.PackageError) as error:
                    await target.status()
                assert "closed" in str(error.exception)
                async with m.connect(config) as observer:
                    assert_eq(await observer.status(), ())
            finally:
                await blocker.rollback()
                await asyncio.gather(applying, return_exceptions=True)
        await _observe_physical_disposal(path)
        async with aiosqlite.connect(
            str(path), isolation_level=None, timeout=0
        ) as probe:
            await probe.execute("BEGIN IMMEDIATE")
            await probe.rollback()
        async with m.connect(config) as fresh:
            assert_eq(await fresh.status(), ())
            assert_eq(await fresh.apply(await fresh.prepare(package)), "applied")
            assert_eq(
                await fresh.apply(await fresh.prepare(package)), "already_applied"
            )
        async with (
            await sqlite.Database.initialize(config) as app,
            app.transaction() as tx,
        ):
            await tx.execute(sqlite.insert(Account(id=1, role="admin")))
            row = await tx.fetch_one(sqlite.select(Account))
        assert_eq((row.id, row.role), (1, "admin"))


def _database_files() -> set[Path]:
    """Observe actual Linux descriptors, not library/driver task flags."""
    opened: set[Path] = set()
    for descriptor in Path("/proc/self/fd").iterdir():
        with suppress(FileNotFoundError):
            opened.add(descriptor.readlink())
    return opened


async def _observe_physical_disposal(path: Path) -> None:
    """Do not tear down a fixture while its detached worker still owns the file."""
    async with asyncio.timeout(5):
        while True:
            if path not in await asyncio.to_thread(_database_files):
                break
            await asyncio.sleep(0.02)


@test(mark="medium")
async def sqlite_commit_deadline_requires_fresh_evidence_not_a_rollback_claim() -> None:
    """A blocked COMMIT can complete after timeout; no safe target reuse or blind replay."""
    with TemporaryDirectory() as directory:
        path = Path(directory) / "app.db"
        package = m.compile(m.generate("001_accounts", [Account], backend="sqlite"))
        config = sqlite.Config(database=path, acquire_timeout=3, operation_timeout=0.15)
        async with (
            aiosqlite.connect(str(path), isolation_level=None) as reader,
            m.connect(config) as target,
        ):
            await reader.execute("CREATE TABLE directory(id INTEGER)")
            async with reader.execute("PRAGMA journal_mode") as cursor:
                assert_eq(await cursor.fetchall(), [("delete",)])
            plan = await target.prepare(package)
            wire = plan.dump()
            await reader.execute("BEGIN")
            async with reader.execute("SELECT * FROM directory") as cursor:
                await cursor.fetchall()
            applying = asyncio.create_task(target.apply(plan))
            try:
                done, _ = await asyncio.wait({applying}, timeout=1)
                assert_eq(bool(done), True, msg="configured COMMIT deadline ignored")
                with assert_raises(sqlite.DatabaseOperationTimeoutError) as error:
                    await applying
                assert_eq(error.exception.operation, "migration commit")
                assert_eq(plan.dump(), wire)
                with assert_raises(m.PackageError):
                    await target.prepare(package)
                async with reader.execute(
                    "SELECT name FROM sqlite_schema WHERE type='table'"
                ) as cursor:
                    assert_eq(await cursor.fetchall(), [("directory",)])
            finally:
                await reader.rollback()
                await asyncio.gather(applying, return_exceptions=True)
        await _observe_physical_disposal(path)
        async with m.connect(config) as fresh:
            progress = await fresh.status()
            # The independent, post-disposal observation selects the next action.
            # Neither outcome is inferred from a cancelled COMMIT awaiter.
            if progress:
                assert_eq(
                    [(p.revision, p.phase) for p in progress],
                    [("001_accounts", "complete")],
                )
                assert_eq(
                    await fresh.apply(await fresh.prepare(package)), "already_applied"
                )
            else:
                assert_eq(await fresh.apply(await fresh.prepare(package)), "applied")
        async with (
            await sqlite.Database.initialize(config) as app,
            app.transaction() as tx,
        ):
            await tx.execute(sqlite.insert(Account(id=1, role="admin")))
            row = await tx.fetch_one(sqlite.select(Account))
        assert_eq((row.id, row.role), (1, "admin"))


class NativeInitial[S = mariadb.Pending](mariadb.Model[S]):
    """Application mapping for initial committed role-workflow packages."""

    __tablename__: ClassVar[str] = "accounts"
    __row_type__: ClassVar[mariadb.ReadType[NativeInitial[mariadb.Row]]]
    id: mariadb.Col[int] = mariadb.Integer(primary_key=True)
    is_admin: mariadb.Col[bool] = mariadb.Integer()


class NativeExpanded[S = mariadb.Pending](mariadb.Model[S]):
    """Independent typed observations of rollback, not a claimed new endpoint."""

    __tablename__: ClassVar[str] = "accounts"
    __row_type__: ClassVar[mariadb.ReadType[NativeExpanded[mariadb.Row]]]
    id: mariadb.Col[int] = mariadb.Integer(primary_key=True)
    is_admin: mariadb.Col[bool] = mariadb.Integer()
    role: mariadb.Col[str | None] = mariadb.Text(nullable=True)


class NativeAccount[S = mariadb.Pending](mariadb.Model[S]):
    """Current application contract after explicit original-plan recovery."""

    __tablename__: ClassVar[str] = "accounts"
    __row_type__: ClassVar[mariadb.ReadType[NativeAccount[mariadb.Row]]]
    id: mariadb.Col[int] = mariadb.Integer(primary_key=True)
    role: mariadb.Col[str] = mariadb.Text()


@test(mark="slow")
async def native_deadline_rolls_back_partial_backfill_but_retains_durable_uncertainty() -> (  # noqa: PLR0915 - keep the consumer lifecycle visible
    None
):
    """Socket disposal does not erase original recovery evidence or authorize blind retry."""
    server = await load_fixture(provide_package_server())
    config = server.config()
    fixed = Path(__file__).parent / "fixtures" / "role-interruption" / "mariadb"
    first = m.Package.load((fixed / "001_accounts.json").read_text())
    second = m.Package.load((fixed / "002_expand.json").read_text())
    roles = m.Package.load((fixed / "003_roles.json").read_text())
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
        await target.apply(await target.prepare(second, schema_writers_excluded=True))
    blocker = await aiomysql.connect(
        unix_socket=str(config.unix_socket),
        user=config.user,
        password=config.password,
        db=config.database,
        autocommit=False,
    )
    try:
        async with blocker.cursor() as cursor:
            await cursor.execute("SELECT id FROM accounts WHERE id=2 FOR UPDATE")
        async with m.connect(replace(config, operation_timeout=2)) as target:
            original = await target.prepare(roles, schema_writers_excluded=True)
            wire = original.dump()
            applying = asyncio.create_task(target.apply(original))
            try:
                observed = await _waiting_update(config)
                assert observed["modified"] >= 1
                done, _ = await asyncio.wait({applying}, timeout=4)
                assert_eq(bool(done), True, msg="native operation deadline ignored")
                with assert_raises(mariadb.DatabaseOperationTimeoutError):
                    await applying
                assert_eq(original.dump(), wire)
                with assert_raises(m.PackageError):
                    await target.status()
            finally:
                if not applying.done():
                    applying.cancel()
                await asyncio.gather(applying, return_exceptions=True)
    finally:
        await blocker.rollback()
        blocker.close()
    await _wait_disconnected(config, observed["id"])
    async with (
        await mariadb.Database.initialize(config) as app,
        app.transaction() as tx,
    ):
        rows = await tx.fetch_all(
            mariadb.select(NativeExpanded).order_by(NativeExpanded.id.asc())
        )
        assert_eq(
            [(r.id, r.is_admin, r.role) for r in rows],
            [(1, True, None), (2, False, None)],
        )
    async with m.connect(config) as fresh:
        progress = next(p for p in await fresh.status() if p.revision == "003_roles")
        assert_eq((progress.phase, progress.acknowledged_steps), ("uncertain", 0))
        with assert_raises(m.PackageError) as error:
            await fresh.prepare(roles, schema_writers_excluded=True)
        assert "inspect before recovery" in str(error.exception)
        saved = m.Prepared.load(wire)
        recovery = await fresh.inspect_recovery(saved, schema_writers_excluded=True)
        assert_eq(
            (recovery.disposition, recovery.acknowledged_steps), ("retry_remaining", 0)
        )
        assert_eq(await fresh.resume(recovery, schema_writers_excluded=True), "applied")
        assert_eq(saved.dump(), wire)
    async with (
        await mariadb.Database.initialize(config) as app,
        app.transaction() as tx,
    ):
        current = await tx.fetch_all(
            mariadb.select(NativeAccount).order_by(NativeAccount.id.asc())
        )
    assert_eq([(r.id, r.role) for r in current], [(1, "admin"), (2, "user")])


@test(mark="medium")
async def time_between_public_operations_does_not_consume_driver_deadlines() -> None:
    """The target context is not one whole-transaction/package wall-clock deadline."""
    with TemporaryDirectory() as directory:
        config = sqlite.Config(
            database=Path(directory) / "app.db", operation_timeout=0.2
        )
        package = m.compile(m.generate("001_accounts", [Account], backend="sqlite"))
        async with m.connect(config) as target:
            plan = await target.prepare(package)
            await asyncio.sleep(0.3)
            assert_eq(await target.apply(plan), "applied")
            await asyncio.sleep(0.3)
            assert_eq((await target.status())[0].phase, "complete")


@test(
    [
        Param[Literal["task", "scope"]](value="task", name="task"),
        Param[Literal["task", "scope"]](value="scope", name="scope"),
    ],
    mark="medium",
)
async def sqlite_cancelled_inspection_discards_the_interrupted_session(
    mode: Literal["task", "scope"],
) -> None:
    """Both cancellation styles stop admission without queuing cleanup SQL behind a lock."""
    with TemporaryDirectory() as directory:
        path = Path(directory) / "app.db"
        config = sqlite.Config(database=path, acquire_timeout=3)
        async with (
            aiosqlite.connect(str(path), isolation_level=None) as blocker,
            m.connect(config) as target,
        ):
            await blocker.execute("CREATE TABLE directory(id INTEGER)")
            await blocker.execute("BEGIN EXCLUSIVE")
            scope = anyio.CancelScope()

            async def inspect() -> None:
                if mode == "scope":
                    with scope:
                        await target.status()
                else:
                    await target.status()

            inspecting = asyncio.create_task(inspect())
            try:
                await asyncio.sleep(0.1)
                assert not inspecting.done()
                if mode == "task":
                    inspecting.cancel()
                    with assert_raises(asyncio.CancelledError):
                        await inspecting
                else:
                    scope.cancel()
                    await inspecting
                    assert scope.cancelled_caught
                with assert_raises(m.PackageError):
                    await target.status()
            finally:
                await blocker.rollback()
                if not inspecting.done():
                    inspecting.cancel()
                await asyncio.gather(inspecting, return_exceptions=True)
        await _observe_physical_disposal(path)
        async with m.connect(config) as fresh:
            assert_eq(await fresh.status(), ())


@test(mark="medium")
async def failed_rebuild_diagnostic_does_not_predeclare_a_cleanup_outcome() -> None:
    """Validation explains refusal; fresh evidence, not its text, proves rollback."""
    with TemporaryDirectory() as directory:
        path = Path(directory) / "app.db"
        config = sqlite.Config(database=path)
        fixed = Path(__file__).parent / "fixtures" / "role-interruption" / "sqlite"
        first = m.Package.load((fixed / "001_accounts.json").read_text())
        second = m.Package.load((fixed / "002_expand.json").read_text())
        roles = m.Package.load((fixed / "003_roles.json").read_text())
        async with m.connect(config) as target:
            await target.apply(await target.prepare(first))
        async with (
            await sqlite.Database.initialize(config) as app,
            app.transaction() as tx,
        ):
            await tx.execute(sqlite.insert(Initial(id=1, is_admin=True)))
        async with m.connect(config) as target:
            await target.apply(await target.prepare(second))
        async with aiosqlite.connect(str(path)) as external:
            await external.execute(
                "CREATE TABLE children(id INTEGER PRIMARY KEY, account_id INTEGER REFERENCES accounts(id))"
            )
            await external.execute("INSERT INTO children VALUES(99,999)")
            await external.commit()
        async with m.connect(config) as target:
            plan = await target.prepare(roles, preserve_unmanaged=True)
            with assert_raises(m.PackageError) as error:
                await target.apply(plan)
            assert_eq(
                "foreign-key validation" in str(error.exception),
                True,
                msg=str(error.exception),
            )
            assert_eq(
                "rolled back" in str(error.exception),
                False,
                msg=f"premature cleanup claim: {error.exception}",
            )
        async with m.connect(config) as observer:
            assert_eq(
                sorted(p.revision for p in await observer.status()),
                ["001_accounts", "002_expand"],
            )
        async with (
            await sqlite.Database.initialize(config) as app,
            app.transaction() as tx,
        ):
            row = await tx.fetch_one(sqlite.select(Initial))
        assert_eq((row.id, row.is_admin), (1, True))

"""Native backend execution through the experimental preparation seam."""

import asyncio
import os
import signal
from collections.abc import AsyncGenerator
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import ClassVar

from pymysql.err import IntegrityError, OperationalError
from snektest import assert_eq, assert_raises, fixture, load_fixture, test

from snekql import mariadb
from snekql.experimental import migrations
from snekql.testing.mariadb import TemporaryMariaDBServer, temporary_mariadb_server


@fixture(scope="session")
async def package_server_session() -> AsyncGenerator[TemporaryMariaDBServer]:
    """Own a unique data directory, including across concurrent test invocations."""
    await asyncio.to_thread(Path(".snektest").mkdir, exist_ok=True)
    with TemporaryDirectory(prefix="packages-", dir=".snektest") as directory:
        async with temporary_mariadb_server(
            data_directory=Path(directory) / "data"
        ) as server:
            yield server


@fixture
async def provide_package_server() -> AsyncGenerator[TemporaryMariaDBServer]:
    """Each scenario gets a clean schema on the independently owned server."""
    server = await load_fixture(package_server_session())
    await server.reset_database()
    yield server


class Entry[S = mariadb.Pending](mariadb.Model[S]):
    """An independently declared MariaDB table."""

    __row_type__: ClassVar[mariadb.ReadType[Entry[mariadb.Row]]]
    id: mariadb.Col[int] = mariadb.Integer(primary_key=True)
    title: mariadb.Col[str] = mariadb.Text()


@test(mark="slow")
async def mariadb_package_creates_usable_table_and_records_identity() -> None:
    """Frozen creation SQL executes without application imports during deployment."""
    server = await load_fixture(provide_package_server())
    package = migrations.compile(
        migrations.generate("001_entries", [Entry], backend="mariadb")
    )
    async with migrations.connect(server.config()) as target:
        prepared = await target.prepare(package, schema_writers_excluded=True)
        assert_eq(await target.apply(prepared), "applied")
        assert_eq(await target.apply(prepared), "already_applied")
    async with (
        await mariadb.Database.initialize(server.config()) as db,
        db.transaction() as tx,
    ):
        await tx.execute(mariadb.raw("INSERT INTO entry VALUES(1, 'kept')"))
        rows = await tx.fetch_all(mariadb.raw("SELECT title FROM entry"))
    assert_eq(rows, [{"title": "kept"}])


@test(mark="slow")
async def ordinary_autoincrement_activity_is_not_schema_drift() -> None:
    """MariaDB's changing AUTO_INCREMENT counter is not a schema definition."""

    class Generated[S = mariadb.Pending](mariadb.Model[S]):
        """Table whose next identity changes with ordinary writes."""

        __row_type__: ClassVar[mariadb.ReadType[Generated[mariadb.Row]]]
        id: mariadb.GenCol[int] = mariadb.Integer(
            primary_key=True, auto_increment=True, default=mariadb.PENDING_GENERATION
        )

    server = await load_fixture(provide_package_server())
    package = migrations.compile(
        migrations.generate("001", [Generated], backend="mariadb")
    )
    async with migrations.connect(server.config()) as target:
        await target.apply(await target.prepare(package, schema_writers_excluded=True))
        await server.run_sql("INSERT INTO generated VALUES(100)")
        prepared = await target.prepare(package, schema_writers_excluded=True)
        assert_eq(await target.apply(prepared), "already_applied")


class MissingParent[S = mariadb.Pending](mariadb.Model[S]):
    """External prerequisite intentionally absent from the test database."""

    __row_type__: ClassVar[mariadb.ReadType[MissingParent[mariadb.Row]]]
    id: mariadb.Col[int] = mariadb.Integer(primary_key=True)


class Dependent[S = mariadb.Pending](mariadb.Model[S]):
    """Creation fails when its externally owned prerequisite does not exist."""

    __row_type__: ClassVar[mariadb.ReadType[Dependent[mariadb.Row]]]
    id: mariadb.Col[int] = mariadb.Integer(primary_key=True)
    parent_id: mariadb.FKCol[MissingParent, int] = mariadb.ForeignKey(
        MissingParent.id, nullable=False
    )


@test(mark="slow")
async def partial_mariadb_ddl_reports_progress_and_refuses_blind_retry() -> None:
    """A later server rejection leaves earlier DDL and an explicit uncertain state."""

    server = await load_fixture(provide_package_server())
    package = migrations.compile(
        migrations.generate("001", [Entry, Dependent], backend="mariadb")
    )
    async with migrations.connect(server.config()) as target:
        prepared = await target.prepare(package, schema_writers_excluded=True)
        with assert_raises(OperationalError):
            await target.apply(prepared)
        progress = await target.status()
        assert_eq(progress[0].phase, "uncertain")
        assert_eq(progress[0].acknowledged_steps, 1)
        with assert_raises(migrations.PackageError):
            await target.apply(prepared)
    async with (
        await mariadb.Database.initialize(server.config()) as db,
        db.transaction() as tx,
    ):
        rows = await tx.fetch_all(mariadb.raw("SELECT COUNT(*) AS n FROM entry"))
    assert_eq(rows, [{"n": 0}])


@test(mark="slow")
async def competing_mariadb_runners_recheck_history_under_advisory_lock() -> None:
    """Both workers prepare before either executes the non-idempotent package."""

    server = await load_fixture(provide_package_server())
    package = migrations.compile(migrations.generate("001", [Entry], backend="mariadb"))
    async with (
        migrations.connect(server.config()) as first,
        migrations.connect(server.config()) as second,
    ):
        a = await first.prepare(package, schema_writers_excluded=True)
        b = await second.prepare(package, schema_writers_excluded=True)
        results = await asyncio.gather(first.apply(a), second.apply(b))
    assert_eq(sorted(results), ["already_applied", "applied"])


@test(mark="slow")
async def uncertain_progress_survives_native_server_kill_and_restart() -> None:
    """A real process crash does not erase acknowledged partial DDL evidence."""

    package = migrations.compile(
        migrations.generate("001", [Entry, Dependent], backend="mariadb")
    )
    with TemporaryDirectory() as directory:
        data = Path(directory) / "data"
        socket = Path(directory) / "server.sock"
        async with temporary_mariadb_server(
            data_directory=data, socket_path=socket
        ) as server:
            async with migrations.connect(server.config()) as target:
                plan = await target.prepare(package, schema_writers_excluded=True)
                with assert_raises(OperationalError) as original:
                    await target.apply(plan)
            pid = int(await asyncio.to_thread(server.pid_path.read_text))
            os.kill(pid, signal.SIGKILL)
        async with (
            temporary_mariadb_server(
                data_directory=data, socket_path=socket
            ) as restarted,
            migrations.connect(restarted.config()) as target,
        ):
            progress = await target.status()
            assert_eq(progress[0].phase, "uncertain")
            assert_eq(progress[0].acknowledged_steps, 1)
            with assert_raises(migrations.PackageError):
                await target.prepare(package, schema_writers_excluded=True)
            assessment = await target.inspect_recovery(
                plan, schema_writers_excluded=True
            )
            assert_eq(assessment.disposition, "retry_remaining")
            with assert_raises(OperationalError) as retried:
                await target.resume(assessment, schema_writers_excluded=True)
            assert_eq(retried.exception.args[0], original.exception.args[0])
            assert_eq((await target.status())[0].acknowledged_steps, 1)


@test(mark="slow")
async def older_applied_revision_cannot_hide_later_uncertainty() -> None:
    """Checking an ancestor still reports an incomplete later application."""
    server = await load_fixture(provide_package_server())
    first = migrations.compile(migrations.generate("001", [Entry], backend="mariadb"))
    second = migrations.compile(
        migrations.generate(
            "002_0", [Entry, Dependent], backend="mariadb", previous=first
        )
    )
    async with migrations.connect(server.config()) as target:
        initial = await target.prepare(first, schema_writers_excluded=True)
        await target.apply(initial)
        pending = await target.prepare(second, schema_writers_excluded=True)
        with assert_raises(OperationalError):
            await target.apply(pending)
        with assert_raises(migrations.PackageError) as error:
            await target.apply(initial)
        assert_eq("uncertain progress" in str(error.exception), True)


class EntryWithNote[S = mariadb.Pending](mariadb.Model[S]):
    """Expanded historical shape for a native typed backfill."""

    __tablename__ = "entry"
    __row_type__: ClassVar[mariadb.ReadType[EntryWithNote[mariadb.Row]]]
    id: mariadb.Col[int] = mariadb.Integer(primary_key=True)
    title: mariadb.Col[str] = mariadb.Text()
    note: mariadb.Col[str | None] = mariadb.Text(nullable=True)


@test(mark="slow")
async def mariadb_typed_backfill_uses_frozen_bindings() -> None:
    """The MariaDB execution package binds the reviewed historical query values."""
    server = await load_fixture(provide_package_server())
    first = migrations.compile(migrations.generate("001", [Entry], backend="mariadb"))
    draft = migrations.generate(
        "002", [EntryWithNote], backend="mariadb", previous=first
    )
    draft = draft.model_copy(
        update={
            "operations": (*draft.operations, migrations.Checkpoint(name="backfill"))
        }
    )
    change = migrations.DataChange.from_query(
        mariadb.update(EntryWithNote)
        .set(EntryWithNote.note.to("reviewed"))
        .where(EntryWithNote.note.is_null()),
        checkpoint="backfill",
        contract_digest=migrations.contract_digest(draft, point="backfill"),
    )
    second = migrations.compile(
        draft.model_copy(update={"operations": (*draft.operations, change)})
    )
    async with migrations.connect(server.config()) as target:
        await target.apply(await target.prepare(first, schema_writers_excluded=True))
        await server.run_sql("INSERT INTO entry VALUES(1, 'kept')")
        await target.apply(await target.prepare(second, schema_writers_excluded=True))
    async with (
        await mariadb.Database.initialize(server.config()) as db,
        db.transaction() as tx,
    ):
        rows = await tx.fetch_all(mariadb.raw("SELECT note FROM entry"))
    assert_eq(rows, [{"note": "reviewed"}])


class RequiredEntry[S = mariadb.Pending](mariadb.Model[S]):
    """Final native contraction after the nullable-note backfill."""

    __tablename__ = "entry"
    __row_type__: ClassVar[mariadb.ReadType[RequiredEntry[mariadb.Row]]]
    id: mariadb.Col[int] = mariadb.Integer(primary_key=True)
    note: mariadb.Col[str] = mariadb.Text()


@test(mark="slow")
async def contraction_rejects_nulls_before_starting_and_preserves_native_data() -> None:
    """Data preconditions fail without falsely recording ambiguous DDL progress."""
    server = await load_fixture(provide_package_server())
    first = migrations.compile(
        migrations.generate("001", [EntryWithNote], backend="mariadb")
    )
    draft = migrations.generate(
        "002", [RequiredEntry], backend="mariadb", previous=first
    )
    second = migrations.compile(
        draft.resolve(migrations.DropColumn(table_name="entry", column_name="title"))
    )
    async with migrations.connect(server.config()) as target:
        await target.apply(await target.prepare(first, schema_writers_excluded=True))
        await server.run_sql("INSERT INTO entry VALUES(1,'old',NULL)")
        plan = await target.prepare(second, schema_writers_excluded=True)
        with assert_raises(migrations.PackageError):
            await target.apply(plan)
        assert_eq([p.revision for p in await target.status()], ["001"])
        await server.run_sql("UPDATE entry SET note='kept'")
        assert_eq(await target.apply(plan), "applied")
    async with (
        await mariadb.Database.initialize(server.config()) as db,
        db.transaction() as tx,
    ):
        rows = await tx.fetch_all(mariadb.raw("SELECT * FROM entry"))
    assert_eq(rows, [{"id": 1, "note": "kept"}])
    invalid = await server.run_sql(
        "INSERT INTO entry(id,note) VALUES(2,NULL)", check=False
    )
    assert_eq(invalid.returncode, 1)


class Counter[S = mariadb.Pending](mariadb.Model[S]):
    """A non-idempotent transformation followed by an independently failing update."""

    __row_type__: ClassVar[mariadb.ReadType[Counter[mariadb.Row]]]
    id: mariadb.Col[int] = mariadb.Integer(primary_key=True)
    count: mariadb.Col[int] = mariadb.Integer()


@test(mark="slow")
async def recovery_resumes_rolled_back_data_without_replaying_acknowledged_work() -> (
    None
):
    """A failed transactional update may be retried, but the prior increment may not."""

    server = await load_fixture(provide_package_server())
    first = migrations.compile(migrations.generate("001", [Counter], backend="mariadb"))
    draft = migrations.generate(
        "002", [Counter], backend="mariadb", previous=first
    ).then(migrations.Checkpoint(name="work"))
    contract = migrations.contract_digest(draft, point="work")
    second = migrations.compile(
        draft.then(
            migrations.DataChange.from_query(
                mariadb.update(Counter)
                .set(Counter.count.to_expr(Counter.count.add(1)))
                .all(),
                checkpoint="work",
                contract_digest=contract,
            ),
            migrations.DataChange.from_query(
                mariadb.update(Counter).set(Counter.id.to(42)).all(),
                checkpoint="work",
                contract_digest=contract,
            ),
        )
    )
    async with migrations.connect(server.config()) as target:
        await target.apply(await target.prepare(first, schema_writers_excluded=True))
        await server.run_sql("INSERT INTO counter VALUES(1,0),(2,0)")
        plan = await target.prepare(second, schema_writers_excluded=True)
        with assert_raises(IntegrityError):
            await target.apply(plan)
        assessment = await target.inspect_recovery(plan, schema_writers_excluded=True)
        assert_eq(assessment.disposition, "retry_remaining")
        assert_eq(assessment.acknowledged_steps, 1)
        await server.run_sql(
            "CREATE TRIGGER side_effect BEFORE UPDATE ON counter FOR EACH ROW SET @touched=1"
        )
        assert_eq(
            (
                await target.inspect_recovery(plan, schema_writers_excluded=True)
            ).disposition,
            "ambiguous",
        )
        with assert_raises(migrations.PackageError):
            await target.resume(assessment, schema_writers_excluded=True)
        await server.run_sql("DROP TRIGGER side_effect")
        await server.run_sql("DELETE FROM counter WHERE id=2")
        assert_eq(
            await target.resume(assessment, schema_writers_excluded=True), "applied"
        )
        assert_eq(await target.apply(plan), "already_applied")
    async with (
        await mariadb.Database.initialize(server.config()) as db,
        db.transaction() as tx,
    ):
        rows = await tx.fetch_all(mariadb.raw("SELECT * FROM counter"))
    assert_eq(rows, [{"id": 42, "count": 1}])


@test(mark="slow")
async def committed_contraction_without_acknowledgement_stays_ambiguous() -> None:
    """A schema endpoint is not permission to invent a missing execution receipt."""
    server = await load_fixture(provide_package_server())
    first = migrations.compile(
        migrations.generate("001", [EntryWithNote], backend="mariadb")
    )
    second = migrations.compile(
        migrations.generate(
            "002", [RequiredEntry], backend="mariadb", previous=first
        ).resolve(migrations.DropColumn(table_name="entry", column_name="title"))
    )
    async with migrations.connect(server.config()) as target:
        await target.apply(await target.prepare(first, schema_writers_excluded=True))
        await server.run_sql("INSERT INTO entry VALUES(1,'old','kept')")
        await server.run_sql(
            "CREATE TRIGGER fail_receipt BEFORE UPDATE ON snekql_experimental_migrations FOR EACH ROW SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='receipt unavailable'"
        )
        plan = await target.prepare(second, schema_writers_excluded=True)
        with assert_raises(OperationalError):
            await target.apply(plan)
        await server.run_sql("DROP TRIGGER fail_receipt")
        assessment = await target.inspect_recovery(plan, schema_writers_excluded=True)
        assert_eq(assessment.disposition, "ambiguous")
        assert_eq(assessment.acknowledged_steps, 0)
        with assert_raises(migrations.PackageError):
            await target.resume(assessment, schema_writers_excluded=True)
    async with (
        await mariadb.Database.initialize(server.config()) as db,
        db.transaction() as tx,
    ):
        assert_eq(
            await tx.fetch_all(mariadb.raw("SELECT * FROM entry")),
            [{"id": 1, "note": "kept"}],
        )

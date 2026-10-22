"""Native backend execution through the experimental preparation seam."""

import asyncio
import os
import signal
from collections.abc import AsyncGenerator
from datetime import date
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import ClassVar
from uuid import UUID

import aiomysql
import anyio
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
        with assert_raises(migrations.PackageError):
            await target.reconcile(
                assessment,
                reason="Cannot infer a data update from schema",
                schema_writers_excluded=True,
            )
        with assert_raises(migrations.PackageError):
            await target.reconcile(
                assessment.model_copy(update={"disposition": "reconcile_structural"}),
                reason="A caller flag is not evidence",
                schema_writers_excluded=True,
            )
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


async def lose_contraction_receipt(
    server: TemporaryMariaDBServer,
) -> migrations.Prepared:
    """Set up a real DDL commit with an externally rejected journal update."""
    first = migrations.compile(
        migrations.generate("001", [EntryWithNote], backend="mariadb")
    )
    second = migrations.compile(
        migrations.generate(
            "002", [RequiredEntry], backend="mariadb", previous=first
        ).resolve(migrations.DropColumn(table_name="entry", column_name="title"))
    )
    await server.run_sql(
        "CREATE TABLE unrelated(id INTEGER) COMMENT=' AUTO_INCREMENT=7'"
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
        return plan


@fixture
async def provide_contraction_failure() -> AsyncGenerator[
    tuple[TemporaryMariaDBServer, migrations.Prepared]
]:
    """A reviewed contraction whose DDL committed but whose receipt did not."""
    server = await load_fixture(provide_package_server())
    yield server, await lose_contraction_receipt(server)


@test(mark="slow")
async def committed_contraction_can_be_reconciled_without_replaying_ddl() -> None:
    """Exact structural acceptance is explicit, durable, and distinct from execution."""
    server, plan = await load_fixture(provide_contraction_failure())
    async with migrations.connect(server.config()) as target:
        assessment = await target.inspect_recovery(plan, schema_writers_excluded=True)
        assert_eq(assessment.disposition, "reconcile_structural")
        assert_eq(assessment.acknowledged_steps, 0)
        original_sql = next(
            sql for _, name, sql in assessment.before_catalog if name == "entry"
        )
        observed_sql = next(
            sql for _, name, sql in assessment.observed_catalog if name == "entry"
        )
        assert "`title`" in original_sql
        assert "`title`" not in observed_sql
        with assert_raises(migrations.PackageError):
            await target.resume(assessment, schema_writers_excluded=True)
        with assert_raises(migrations.PackageError):
            await target.reconcile(assessment, reason=" ", schema_writers_excluded=True)
        accepted = await target.reconcile(
            assessment,
            reason="Reviewed the lost contraction receipt",
            schema_writers_excluded=True,
        )
        assert_eq(accepted.disposition, "finish")
        with assert_raises(migrations.PackageError):
            await target.reconcile(
                assessment, reason="Must not accept twice", schema_writers_excluded=True
            )
    async with migrations.connect(server.config()) as reopened:
        assessed = await reopened.inspect_recovery(plan, schema_writers_excluded=True)
        assert_eq(assessed.disposition, "finish")
        assert_eq(
            await reopened.resume(assessed, schema_writers_excluded=True), "applied"
        )
        progress = next(p for p in await reopened.status() if p.revision == "002")
        assert_eq(len(progress.reconciliations), 1)
        assert_eq(progress.reconciliations[0].step, 1)
        assert_eq(
            progress.reconciliations[0].reason, "Reviewed the lost contraction receipt"
        )
        assert_eq(progress.reconciliations[0].before_catalog, assessment.before_catalog)
        assert_eq(
            progress.reconciliations[0].after_catalog, assessment.observed_catalog
        )
        assert_eq(await reopened.apply(plan), "already_applied")
    async with (
        await mariadb.Database.initialize(server.config()) as db,
        db.transaction() as tx,
    ):
        assert_eq(
            await tx.fetch_all(mariadb.raw("SELECT * FROM entry")),
            [{"id": 1, "note": "kept"}],
        )


@test(mark="slow")
async def reconciliation_refuses_changed_catalog_and_stale_review() -> None:
    """Only the exact next transition qualifies, including untouched objects."""
    server, plan = await load_fixture(provide_contraction_failure())
    async with migrations.connect(server.config()) as target:
        assessment = await target.inspect_recovery(plan, schema_writers_excluded=True)
        for change, restore in (
            (
                "ALTER TABLE unrelated COMMENT=' AUTO_INCREMENT=8'",
                "ALTER TABLE unrelated COMMENT=' AUTO_INCREMENT=7'",
            ),
            ("CREATE TABLE unexpected(id INTEGER)", "DROP TABLE unexpected"),
            (
                "ALTER TABLE entry MODIFY note VARCHAR(256) NOT NULL",
                "ALTER TABLE entry MODIFY note VARCHAR(255) CHARACTER SET utf8mb4 COLLATE utf8mb4_bin NOT NULL",
            ),
        ):
            await server.run_sql(change)
            assert_eq(
                (
                    await target.inspect_recovery(plan, schema_writers_excluded=True)
                ).disposition,
                "ambiguous",
            )
            with assert_raises(migrations.PackageError):
                await target.reconcile(
                    assessment,
                    reason="Not the reviewed schema",
                    schema_writers_excluded=True,
                )
            await server.run_sql(restore)
        progress = next(p for p in await target.status() if p.revision == "002")
        assert_eq(progress.acknowledged_steps, 0)
        assert_eq(progress.reconciliations, ())


@test(mark="slow")
async def reconciliation_refuses_changed_rendering_profile() -> None:
    """Identical SHOW CREATE text under another SQL mode is not equivalent evidence."""
    server, plan = await load_fixture(provide_contraction_failure())
    async with migrations.connect(server.config()) as target:
        assessment = await target.inspect_recovery(plan, schema_writers_excluded=True)
    await server.run_sql(
        "SET GLOBAL sql_mode=CONCAT(@@GLOBAL.sql_mode,',NO_BACKSLASH_ESCAPES')"
    )
    try:
        async with migrations.connect(server.config()) as different_mode:
            assert_eq(
                (
                    await different_mode.inspect_recovery(
                        plan, schema_writers_excluded=True
                    )
                ).disposition,
                "ambiguous",
            )
            with assert_raises(migrations.PackageError):
                await different_mode.reconcile(
                    assessment,
                    reason="Different rendering",
                    schema_writers_excluded=True,
                )
    finally:
        await server.run_sql(
            "SET GLOBAL sql_mode='"
            + assessment.before_profile[1].replace("'", "''")
            + "'"
        )


@test(mark="slow")
async def structural_acceptance_survives_server_restart_before_completion() -> None:
    """A committed acceptance must not become a second DDL attempt after restart."""
    with TemporaryDirectory() as directory:
        data, socket = Path(directory) / "data", Path(directory) / "server.sock"
        async with temporary_mariadb_server(
            data_directory=data, socket_path=socket
        ) as server:
            plan = await lose_contraction_receipt(server)
            async with migrations.connect(server.config()) as target:
                assessment = await target.inspect_recovery(
                    plan, schema_writers_excluded=True
                )
                await target.reconcile(
                    assessment,
                    reason="Reviewed before restart",
                    schema_writers_excluded=True,
                )
            pid = int(await asyncio.to_thread(server.pid_path.read_text))
            os.kill(pid, signal.SIGKILL)
        async with (
            temporary_mariadb_server(
                data_directory=data, socket_path=socket
            ) as restarted,
            migrations.connect(restarted.config()) as target,
        ):
            progress = next(p for p in await target.status() if p.revision == "002")
            assert_eq(progress.phase, "uncertain")
            assert_eq(progress.acknowledged_steps, 1)
            assert_eq(len(progress.reconciliations), 1)
            assert_eq(progress.reconciliations[0].reason, "Reviewed before restart")
            remaining = await target.inspect_recovery(
                plan, schema_writers_excluded=True
            )
            assert_eq(remaining.disposition, "finish")
            assert_eq(
                await target.resume(remaining, schema_writers_excluded=True), "applied"
            )


@test(mark="slow")
async def competing_reconcilers_record_only_one_acceptance() -> None:
    """The losing reviewer must reassess, rather than append a duplicate receipt."""
    server, plan = await load_fixture(provide_contraction_failure())
    async with (
        migrations.connect(server.config()) as first,
        migrations.connect(server.config()) as second,
    ):
        a = await first.inspect_recovery(plan, schema_writers_excluded=True)
        b = await second.inspect_recovery(plan, schema_writers_excluded=True)
        results = await asyncio.gather(
            first.reconcile(a, reason="first reviewer", schema_writers_excluded=True),
            second.reconcile(b, reason="second reviewer", schema_writers_excluded=True),
            return_exceptions=True,
        )
        assert_eq(sum(isinstance(result, migrations.Recovery) for result in results), 1)
        assert_eq(
            sum(isinstance(result, migrations.PackageError) for result in results), 1
        )
        progress = next(p for p in await first.status() if p.revision == "002")
        assert_eq(progress.acknowledged_steps, 1)
        assert_eq(len(progress.reconciliations), 1)


@test(mark="slow")
async def unacknowledged_creation_is_not_guessed_from_the_destination() -> None:
    """The supported contraction proof must not generalize to other SQL steps."""
    server = await load_fixture(provide_package_server())
    first = migrations.compile(migrations.generate("001", [Entry], backend="mariadb"))
    second = migrations.compile(
        migrations.generate("002", [Entry, Counter], backend="mariadb", previous=first)
    )
    async with migrations.connect(server.config()) as target:
        await target.apply(await target.prepare(first, schema_writers_excluded=True))
        await server.run_sql(
            "CREATE TRIGGER fail_receipt BEFORE UPDATE ON snekql_experimental_migrations FOR EACH ROW SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='receipt unavailable'"
        )
        plan = await target.prepare(second, schema_writers_excluded=True)
        with assert_raises(OperationalError):
            await target.apply(plan)
        await server.run_sql("DROP TRIGGER fail_receipt")
        assessment = await target.inspect_recovery(plan, schema_writers_excluded=True)
        assert_eq(assessment.disposition, "ambiguous")
        assert any(name == "counter" for _, name, _ in assessment.observed_catalog)
        with assert_raises(migrations.PackageError):
            await target.reconcile(
                assessment,
                reason="An endpoint alone is insufficient",
                schema_writers_excluded=True,
            )
        assert_eq(
            next(
                p for p in await target.status() if p.revision == "002"
            ).acknowledged_steps,
            0,
        )


@test(mark="slow")
async def interrupted_reconciliation_keeps_progress_and_audit_unaccepted() -> None:
    """Kill an owned server while acceptance is blocked on its journal row lock."""
    with TemporaryDirectory() as directory:
        data, socket = Path(directory) / "data", Path(directory) / "server.sock"
        async with temporary_mariadb_server(
            data_directory=data, socket_path=socket
        ) as server:
            plan = await lose_contraction_receipt(server)
            config = server.config()
            blocker = await aiomysql.connect(
                unix_socket=str(config.unix_socket),
                user=config.user,
                password=config.password,
                db=config.database,
                autocommit=False,
            )
            try:
                async with migrations.connect(config) as target:
                    assessment = await target.inspect_recovery(
                        plan, schema_writers_excluded=True
                    )
                    async with blocker.cursor() as cursor:
                        await cursor.execute(
                            "SELECT digest FROM snekql_experimental_migrations WHERE digest=%s FOR UPDATE",
                            (plan.package.digest,),
                        )
                        assert_eq(await cursor.fetchall(), ((plan.package.digest,),))
                    accepting = asyncio.create_task(
                        target.reconcile(
                            assessment,
                            reason="Must not survive an uncommitted acceptance",
                            schema_writers_excluded=True,
                        )
                    )
                    try:
                        async with asyncio.timeout(10):
                            while True:
                                waiting = await server.run_sql(
                                    "SELECT COUNT(*) FROM information_schema.PROCESSLIST WHERE INFO LIKE 'UPDATE %snekql_experimental_migrations%'"
                                )
                                if waiting.stdout.splitlines()[-1] == "1":
                                    break
                                await asyncio.sleep(0.02)
                        pid = int(await asyncio.to_thread(server.pid_path.read_text))
                        os.kill(pid, signal.SIGKILL)
                        outcome = await asyncio.gather(
                            accepting, return_exceptions=True
                        )
                        assert isinstance(outcome[0], Exception)
                    finally:
                        if not accepting.done():
                            accepting.cancel()
                            await asyncio.gather(accepting, return_exceptions=True)
            finally:
                blocker.close()
        async with (
            temporary_mariadb_server(
                data_directory=data, socket_path=socket
            ) as restarted,
            migrations.connect(restarted.config()) as target,
        ):
            progress = next(p for p in await target.status() if p.revision == "002")
            assert_eq(progress.acknowledged_steps, 0)
            assert_eq(progress.reconciliations, ())
            reassessed = await target.inspect_recovery(
                plan, schema_writers_excluded=True
            )
            assert_eq(reassessed.disposition, "reconcile_structural")
            accepted = await target.reconcile(
                reassessed,
                reason="Reviewed after restart",
                schema_writers_excluded=True,
            )
            assert_eq(
                await target.resume(accepted, schema_writers_excluded=True), "applied"
            )


async def check_cancelled_reconciliation(*, level_cancellation: bool) -> None:
    """Exercise native cancellation with the server blocked on a journal row lock."""
    server, plan = await load_fixture(provide_contraction_failure())
    config = server.config()
    blocker = await aiomysql.connect(
        unix_socket=str(config.unix_socket),
        user=config.user,
        password=config.password,
        db=config.database,
        autocommit=False,
    )
    try:
        async with migrations.connect(config) as target:
            assessment = await target.inspect_recovery(
                plan, schema_writers_excluded=True
            )
            async with blocker.cursor() as cursor:
                await cursor.execute(
                    "SELECT digest FROM snekql_experimental_migrations WHERE digest=%s FOR UPDATE",
                    (plan.package.digest,),
                )
                assert_eq(await cursor.fetchall(), ((plan.package.digest,),))
            scope = anyio.CancelScope()

            async def accept() -> None:
                if level_cancellation:
                    with scope:
                        await target.reconcile(
                            assessment,
                            reason="Cancelled review",
                            schema_writers_excluded=True,
                        )
                else:
                    await target.reconcile(
                        assessment,
                        reason="Cancelled review",
                        schema_writers_excluded=True,
                    )

            accepting = asyncio.create_task(accept())
            try:
                async with asyncio.timeout(10):
                    while True:
                        waiting = await server.run_sql(
                            "SELECT COUNT(*) FROM information_schema.PROCESSLIST WHERE INFO LIKE 'UPDATE %snekql_experimental_migrations%'"
                        )
                        if waiting.stdout.splitlines()[-1] == "1":
                            break
                        await asyncio.sleep(0.02)
                if level_cancellation:
                    scope.cancel()
                    await accepting
                    assert scope.cancelled_caught
                else:
                    accepting.cancel()
                    with assert_raises(asyncio.CancelledError):
                        await accepting
                with assert_raises(migrations.PackageError):
                    await target.status()
            finally:
                if not accepting.done():
                    accepting.cancel()
                await asyncio.gather(accepting, return_exceptions=True)
    finally:
        await blocker.rollback()
        blocker.close()
    async with asyncio.timeout(10), migrations.connect(config) as reopened:
        progress = next(p for p in await reopened.status() if p.revision == "002")
        assert_eq((progress.acknowledged_steps, progress.reconciliations), (0, ()))
        fresh = await reopened.inspect_recovery(plan, schema_writers_excluded=True)
        accepted = await reopened.reconcile(
            fresh, reason="Fresh review", schema_writers_excluded=True
        )
        assert_eq(
            await reopened.resume(accepted, schema_writers_excluded=True), "applied"
        )


@test(mark="slow")
async def cancelled_reconciliation_releases_coordination_without_acceptance() -> None:
    """Task cancellation remains cancellation and invalidates the uncertain session."""
    await check_cancelled_reconciliation(level_cancellation=False)


@test(mark="slow")
async def scope_cancelled_reconciliation_releases_coordination_without_acceptance() -> (
    None
):
    """Level cancellation is not masked by cleanup on a cancelled protocol read."""
    await check_cancelled_reconciliation(level_cancellation=True)


@test(mark="slow")
async def cancelled_status_invalidates_the_interrupted_connection() -> None:
    """Read-only inspection must not leave a broken session apparently reusable."""
    server, _ = await load_fixture(provide_contraction_failure())
    config = server.config()
    blocker = await aiomysql.connect(
        unix_socket=str(config.unix_socket),
        user=config.user,
        password=config.password,
        db=config.database,
    )
    try:
        async with blocker.cursor() as cursor:
            await cursor.execute("LOCK TABLES snekql_experimental_migrations WRITE")
        async with migrations.connect(config) as target:
            inspecting = asyncio.create_task(target.status())
            try:
                async with asyncio.timeout(10):
                    while True:
                        waiting = await server.run_sql(
                            "SELECT COUNT(*) FROM information_schema.PROCESSLIST WHERE INFO LIKE 'SELECT digest,revision,predecessor,%'"
                        )
                        if waiting.stdout.splitlines()[-1] == "1":
                            break
                        await asyncio.sleep(0.02)
                inspecting.cancel()
                with assert_raises(asyncio.CancelledError):
                    await inspecting
                with assert_raises(migrations.PackageError):
                    await target.status()
            finally:
                if not inspecting.done():
                    inspecting.cancel()
                await asyncio.gather(inspecting, return_exceptions=True)
    finally:
        async with blocker.cursor() as cursor:
            await cursor.execute("UNLOCK TABLES")
        blocker.close()
    async with asyncio.timeout(10), migrations.connect(config) as reopened:
        progress = next(p for p in await reopened.status() if p.revision == "002")
        assert_eq((progress.acknowledged_steps, progress.reconciliations), (0, ()))


@test(mark="slow")
async def mariadb_relinquishment_recovers_without_replaying_application_sql() -> None:
    """A failed completion receipt leaves a recoverable metadata-only handoff."""
    server = await load_fixture(provide_package_server())
    first = migrations.compile(
        migrations.generate("001", [Entry, Counter], backend="mariadb")
    )
    second = migrations.Package.load(
        migrations.compile(
            migrations.generate(
                "002", [Counter], backend="mariadb", previous=first
            ).resolve(migrations.RelinquishTable(table_name="entry"))
        ).dump()
    )
    async with migrations.connect(server.config()) as target:
        await target.apply(await target.prepare(first, schema_writers_excluded=True))
        await server.run_sql("INSERT INTO entry VALUES(17,'kept')")
        plan = await target.prepare(second, schema_writers_excluded=True)
        assert_eq(plan.statements, ())
        await server.run_sql(
            "CREATE TRIGGER fail_receipt BEFORE UPDATE ON snekql_experimental_migrations FOR EACH ROW SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='receipt unavailable'"
        )
        with assert_raises(OperationalError):
            await target.apply(plan)
        await server.run_sql("DROP TRIGGER fail_receipt")
    async with migrations.connect(server.config()) as reopened:
        progress = next(p for p in await reopened.status() if p.revision == "002")
        assert_eq(
            (progress.phase, progress.acknowledged_steps, progress.total_steps),
            ("uncertain", 0, 0),
        )
        assessment = await reopened.inspect_recovery(plan, schema_writers_excluded=True)
        assert_eq(assessment.disposition, "finish")
        assert_eq(
            await reopened.resume(assessment, schema_writers_excluded=True), "applied"
        )
        assert_eq(await reopened.apply(plan), "already_applied")
        assert_eq([table.name for table in second.target.tables], ["counter"])
        async with (
            await mariadb.Database.initialize(server.config()) as db,
            db.transaction() as tx,
        ):
            assert_eq(await tx.fetch_all(mariadb.select(Entry.title)), ["kept"])
            assert_eq(await tx.fetch_all(mariadb.select(Entry.id)), [17])
        # Ownership handoff is not a blanket exemption from catalog drift checks.
        await server.run_sql("ALTER TABLE entry ADD COLUMN external_note TEXT")
        continuation = migrations.compile(
            migrations.generate("003", [Counter], backend="mariadb", previous=second)
        )
        with assert_raises(migrations.PackageError):
            await reopened.prepare(continuation, schema_writers_excluded=True)


@test(mark="fast")
def mariadb_adoption_requires_a_backend_specific_proof() -> None:
    """SQLite's declaration comparison must not silently certify another backend."""
    with assert_raises(migrations.PackageError):
        migrations.compile(
            migrations.generate("001", [Entry], backend="mariadb").adopt("entry")
        )


@test(mark="slow")
async def edited_metadata_only_plan_cannot_cross_backend_contracts() -> None:
    """An empty SQL route still must match the target's backend before journaling."""
    server = await load_fixture(provide_package_server())
    native = migrations.compile(migrations.generate("001", [], backend="mariadb"))
    foreign = migrations.compile(migrations.generate("001", [], backend="sqlite"))
    async with migrations.connect(server.config()) as target:
        plan = await target.prepare(native, schema_writers_excluded=True)
        with assert_raises(migrations.PackageError):
            await target.apply(plan.model_copy(update={"package": foreign}))
        assert_eq(await target.status(), ())


@test(mark="slow")
async def sqlite_copy_metadata_does_not_change_native_plan_serialization() -> None:
    """Pre-copy-contract native plan JSON retains its canonical recovery identity."""
    server = await load_fixture(provide_package_server())
    package = migrations.compile(migrations.generate("001", [Entry], backend="mariadb"))
    async with migrations.connect(server.config()) as target:
        prepared = await target.prepare(package, schema_writers_excluded=True)
        legacy = prepared.model_dump(mode="json")
        for step in legacy["steps"]:
            step.pop("copy_columns", None)
            step.pop("dropped_columns", None)
        restored = migrations.Prepared.model_validate(legacy)
        assert_eq(restored.model_dump(mode="json"), legacy)
        assert_eq(await target.apply(restored), "applied")


@test(mark="slow")
async def mariadb_missing_managed_table_cannot_complete_or_finish_recovery() -> None:
    """Committed DDL is not completion when the declared managed table is absent."""
    server = await load_fixture(provide_package_server())
    draft = migrations.generate("001", [Entry], backend="mariadb")
    table = draft.target.tables[0]
    table = table.model_copy(
        update={"sql": table.sql.replace("`entry`", "`wrong_table`")}
    )
    package = migrations.compile(
        draft.model_copy(
            update={
                "target": migrations.State(backend="mariadb", tables=(table,)),
                "operations": (migrations.CreateTable(table=table),),
            }
        )
    )
    async with migrations.connect(server.config()) as target:
        prepared = await target.prepare(package, schema_writers_excluded=True)
        with assert_raises(migrations.PackageError) as error:
            await target.apply(prepared)
        assert "managed table postcondition" in str(error.exception)
        assert "entry" in str(error.exception)
        progress = await target.status()
        assert_eq(
            [(p.phase, p.acknowledged_steps, p.total_steps) for p in progress],
            [("uncertain", 1, 1)],
        )
    async with migrations.connect(server.config()) as target:
        recovery = await target.inspect_recovery(prepared, schema_writers_excluded=True)
        assert_eq(recovery.disposition, "ambiguous")
        assert "managed table postcondition" in recovery.explanation
        with assert_raises(migrations.PackageError):
            await target.resume(recovery, schema_writers_excluded=True)
    async with (
        await mariadb.Database.initialize(server.config()) as db,
        db.transaction() as tx,
    ):
        rows = await tx.fetch_all(
            mariadb.raw(
                "SELECT TABLE_NAME FROM information_schema.TABLES WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='wrong_table'"
            )
        )
        assert_eq(rows, [{"TABLE_NAME": "wrong_table"}])


@test(mark="slow")
async def mariadb_view_cannot_satisfy_a_managed_table_claim() -> None:
    """A queryable object with the right name is not necessarily a base table."""
    server = await load_fixture(provide_package_server())
    draft = migrations.generate("001", [Entry], backend="mariadb")
    table = draft.target.tables[0].model_copy(
        update={"sql": "CREATE VIEW entry AS SELECT 1 AS id, 'visible' AS title"}
    )
    package = migrations.compile(
        draft.model_copy(
            update={
                "target": migrations.State(backend="mariadb", tables=(table,)),
                "operations": (migrations.CreateTable(table=table),),
            }
        )
    )
    async with migrations.connect(server.config()) as target:
        prepared = await target.prepare(package, schema_writers_excluded=True)
        with assert_raises(migrations.PackageError) as error:
            await target.apply(prepared)
        assert "not an observed base table" in str(error.exception)
        assert_eq((await target.status())[0].phase, "uncertain")
        recovery = await target.inspect_recovery(prepared, schema_writers_excluded=True)
        assert_eq(recovery.disposition, "ambiguous")
    async with (
        await mariadb.Database.initialize(server.config()) as db,
        db.transaction() as tx,
    ):
        assert_eq(
            await tx.fetch_all(mariadb.raw("SELECT title FROM entry")),
            [{"title": "visible"}],
        )


@test(mark="slow")
async def mariadb_table_postcondition_uses_server_identifier_resolution() -> None:
    """Case-folding servers resolve a declared mixed-case table without Python folding."""

    class Mixed[S = mariadb.Pending](mariadb.Model[S]):
        """A deliberately mixed-case physical name."""

        __tablename__ = "MixedEntry"
        __row_type__: ClassVar[mariadb.ReadType[Mixed[mariadb.Row]]]
        id: mariadb.Col[int] = mariadb.Integer(primary_key=True)

    await asyncio.to_thread(Path(".snektest").mkdir, exist_ok=True)
    with TemporaryDirectory(prefix="packages-case-", dir=".snektest") as directory:
        async with temporary_mariadb_server(
            data_directory=Path(directory) / "data",
            server_args=("--lower-case-table-names=1",),
        ) as server:
            package = migrations.compile(
                migrations.generate("001", [Mixed], backend="mariadb")
            )
            async with migrations.connect(server.config()) as target:
                plan = await target.prepare(package, schema_writers_excluded=True)
                assert_eq(await target.apply(plan), "applied")
                assert_eq((await target.status())[0].phase, "complete")
            async with (
                await mariadb.Database.initialize(server.config()) as db,
                db.transaction() as tx,
            ):
                assert_eq(
                    await tx.fetch_all(
                        mariadb.raw(
                            "SELECT TABLE_NAME FROM information_schema.TABLES WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='mixedentry'"
                        )
                    ),
                    [{"TABLE_NAME": "mixedentry"}],
                )


@test(mark="slow")
async def mariadb_missing_declared_column_blocks_completion_and_finish() -> None:
    """A real base table is insufficient if a recorded column cannot resolve."""
    server = await load_fixture(provide_package_server())
    draft = migrations.generate("001", [Entry], backend="mariadb")
    table = draft.target.tables[0].model_copy(
        update={"sql": "CREATE TABLE entry(id BIGINT PRIMARY KEY) ENGINE=InnoDB"}
    )
    package = migrations.compile(
        draft.model_copy(
            update={
                "target": migrations.State(backend="mariadb", tables=(table,)),
                "operations": (migrations.CreateTable(table=table),),
            }
        )
    )
    async with migrations.connect(server.config()) as target:
        plan = await target.prepare(package, schema_writers_excluded=True)
        with assert_raises(migrations.PackageError) as error:
            await target.apply(plan)
        assert "managed column postcondition" in str(error.exception)
        assert "entry" in str(error.exception)
        assert_eq(
            [
                (p.phase, p.acknowledged_steps, p.total_steps)
                for p in await target.status()
            ],
            [("uncertain", 1, 1)],
        )
    async with migrations.connect(server.config()) as target:
        recovery = await target.inspect_recovery(plan, schema_writers_excluded=True)
        assert_eq(recovery.disposition, "ambiguous")
        assert "managed column postcondition" in recovery.explanation
        with assert_raises(migrations.PackageError):
            await target.resume(recovery, schema_writers_excluded=True)
    async with (
        await mariadb.Database.initialize(server.config()) as db,
        db.transaction() as tx,
    ):
        assert_eq(
            await tx.fetch_all(
                mariadb.raw(
                    "SELECT COLUMN_NAME FROM information_schema.COLUMNS WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='entry'"
                )
            ),
            [{"COLUMN_NAME": "id"}],
        )


@test(mark="slow")
async def mariadb_column_presence_uses_native_case_rules_and_identifier_quoting() -> (
    None
):
    """Escaped names and differing physical case remain queryable, including populated tables."""
    server = await load_fixture(provide_package_server())
    draft = migrations.generate("001", [Entry], backend="mariadb")
    original = draft.target.tables[0]
    title = original.columns[1].model_copy(
        update={
            "name": "odd`name",
            "definition": original.columns[1].definition.replace(
                "`title`", "`odd``name`"
            ),
        }
    )
    table = original.model_copy(
        update={
            "sql": original.sql.replace("`id`", "`ID`").replace(
                "`title`", "`ODD``NAME`"
            ),
            "columns": (original.columns[0], title),
        }
    )
    first = migrations.compile(
        draft.model_copy(
            update={
                "target": migrations.State(backend="mariadb", tables=(table,)),
                "operations": (migrations.CreateTable(table=table),),
            }
        )
    )
    second = migrations.compile(
        migrations.Draft(
            revision="002",
            predecessor=first.digest,
            before=first.target,
            target=first.target,
            operations=(),
        )
    )
    async with migrations.connect(server.config()) as target:
        assert_eq(
            await target.apply(
                await target.prepare(first, schema_writers_excluded=True)
            ),
            "applied",
        )
        async with (
            await mariadb.Database.initialize(server.config()) as db,
            db.transaction() as tx,
        ):
            await tx.execute(
                mariadb.raw("INSERT INTO entry(id,`odd``name`) VALUES(1,'kept')")
            )
        assert_eq(
            await target.apply(
                await target.prepare(second, schema_writers_excluded=True)
            ),
            "applied",
        )
        assert_eq([p.phase for p in await target.status()], ["complete", "complete"])
    async with (
        await mariadb.Database.initialize(server.config()) as db,
        db.transaction() as tx,
    ):
        assert_eq(
            await tx.fetch_all(
                mariadb.raw("SELECT ID AS id, `ODD``NAME` AS title FROM entry")
            ),
            [{"id": 1, "title": "kept"}],
        )
        assert_eq(
            await tx.fetch_all(
                mariadb.raw(
                    "SELECT COLUMN_NAME FROM information_schema.COLUMNS WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='entry' ORDER BY ORDINAL_POSITION"
                )
            ),
            [{"COLUMN_NAME": "ID"}, {"COLUMN_NAME": "ODD`NAME"}],
        )


@test(mark="slow")
async def mariadb_pseudo_column_cannot_satisfy_a_physical_column_claim() -> None:
    """The native _rowid alias can resolve without a separately declared column."""
    server = await load_fixture(provide_package_server())
    draft = migrations.generate("001", [Entry], backend="mariadb")
    original = draft.target.tables[0]
    alias = original.columns[1].model_copy(
        update={"name": "_rowid", "definition": "`_rowid` TEXT NOT NULL"}
    )
    table = original.model_copy(
        update={
            "sql": "CREATE TABLE entry(id BIGINT PRIMARY KEY) ENGINE=InnoDB",
            "columns": (original.columns[0], alias),
        }
    )
    package = migrations.compile(
        draft.model_copy(
            update={
                "target": migrations.State(backend="mariadb", tables=(table,)),
                "operations": (migrations.CreateTable(table=table),),
            }
        )
    )
    async with migrations.connect(server.config()) as target:
        plan = await target.prepare(package, schema_writers_excluded=True)
        with assert_raises(migrations.PackageError) as error:
            await target.apply(plan)
        assert "managed column postcondition" in str(error.exception)
        assert_eq(
            (
                await target.inspect_recovery(plan, schema_writers_excluded=True)
            ).disposition,
            "ambiguous",
        )
    async with (
        await mariadb.Database.initialize(server.config()) as db,
        db.transaction() as tx,
    ):
        await tx.execute(mariadb.raw("INSERT INTO entry VALUES(7)"))
        assert_eq(
            await tx.fetch_all(
                mariadb.raw("SELECT `_rowid` AS alias_value FROM entry")
            ),
            [{"alias_value": 7}],
        )
        assert_eq(
            await tx.fetch_all(
                mariadb.raw(
                    "SELECT COLUMN_NAME FROM information_schema.COLUMNS WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='entry'"
                )
            ),
            [{"COLUMN_NAME": "id"}],
        )


@test(mark="slow")
async def mariadb_physical_invisible_rowid_column_remains_a_valid_claim() -> None:
    """Catalog-backed matching accepts a real invisible column with the alias spelling."""
    server = await load_fixture(provide_package_server())
    draft = migrations.generate("001", [Entry], backend="mariadb")
    original = draft.target.tables[0]
    column = original.columns[1].model_copy(
        update={
            "name": "_rowid",
            "definition": "`_rowid` TEXT NOT NULL DEFAULT 'kept' INVISIBLE",
        }
    )
    table = original.model_copy(
        update={
            "sql": "CREATE TABLE entry(id BIGINT PRIMARY KEY, `_rowid` TEXT NOT NULL DEFAULT 'kept' INVISIBLE) ENGINE=InnoDB",
            "columns": (original.columns[0], column),
        }
    )
    package = migrations.compile(
        draft.model_copy(
            update={
                "target": migrations.State(backend="mariadb", tables=(table,)),
                "operations": (migrations.CreateTable(table=table),),
            }
        )
    )
    async with migrations.connect(server.config()) as target:
        assert_eq(
            await target.apply(
                await target.prepare(package, schema_writers_excluded=True)
            ),
            "applied",
        )
        assert_eq((await target.status())[0].phase, "complete")
    async with (
        await mariadb.Database.initialize(server.config()) as db,
        db.transaction() as tx,
    ):
        await tx.execute(mariadb.raw("INSERT INTO entry(id) VALUES(9)"))
        assert_eq(
            await tx.fetch_all(
                mariadb.raw("SELECT `_rowid` AS physical_value FROM entry")
            ),
            [{"physical_value": "kept"}],
        )


@test(mark="slow")
async def mariadb_nullable_column_cannot_satisfy_a_required_contract() -> None:
    """Resolvable names are insufficient when the declared NOT NULL fact is absent."""
    server = await load_fixture(provide_package_server())
    draft = migrations.generate("001", [Entry], backend="mariadb")
    table = draft.target.tables[0].model_copy(
        update={
            "sql": "CREATE TABLE entry(id BIGINT PRIMARY KEY, title TEXT NULL) ENGINE=InnoDB"
        }
    )
    package = migrations.compile(
        draft.model_copy(
            update={
                "target": migrations.State(backend="mariadb", tables=(table,)),
                "operations": (migrations.CreateTable(table=table),),
            }
        )
    )
    async with migrations.connect(server.config()) as target:
        plan = await target.prepare(package, schema_writers_excluded=True)
        with assert_raises(migrations.PackageError) as error:
            await target.apply(plan)
        assert "nullability" in str(error.exception)
        assert "title" in str(error.exception)
        assert_eq(
            [
                (p.phase, p.acknowledged_steps, p.total_steps)
                for p in await target.status()
            ],
            [("uncertain", 1, 1)],
        )
    async with migrations.connect(server.config()) as target:
        recovery = await target.inspect_recovery(plan, schema_writers_excluded=True)
        assert_eq(recovery.disposition, "ambiguous")
        assert "nullability" in recovery.explanation
        with assert_raises(migrations.PackageError):
            await target.resume(recovery, schema_writers_excluded=True)
    async with (
        await mariadb.Database.initialize(server.config()) as db,
        db.transaction() as tx,
    ):
        await tx.execute(mariadb.raw("INSERT INTO entry VALUES(1,NULL)"))
        assert_eq(
            await tx.fetch_all(mariadb.raw("SELECT title FROM entry")),
            [{"title": None}],
        )


@test(mark="slow")
async def mariadb_required_column_cannot_satisfy_a_nullable_contract() -> None:
    """An unrequested NOT NULL constraint is also a recorded-structure mismatch."""
    server = await load_fixture(provide_package_server())
    draft = migrations.generate("001", [Entry], backend="mariadb")
    original = draft.target.tables[0]
    title = original.columns[1].model_copy(
        update={
            "nullable": True,
            "definition": "`title` TEXT NULL",
            "query_type": "str | None",
        }
    )
    table = original.model_copy(update={"columns": (original.columns[0], title)})
    package = migrations.compile(
        draft.model_copy(
            update={
                "target": migrations.State(backend="mariadb", tables=(table,)),
                "operations": (migrations.CreateTable(table=table),),
            }
        )
    )
    async with migrations.connect(server.config()) as target:
        plan = await target.prepare(package, schema_writers_excluded=True)
        with assert_raises(migrations.PackageError) as error:
            await target.apply(plan)
        assert "nullability" in str(error.exception)
        recovery = await target.inspect_recovery(plan, schema_writers_excluded=True)
        assert_eq(recovery.disposition, "ambiguous")
        assert_eq((await target.status())[0].phase, "uncertain")
    async with (
        await mariadb.Database.initialize(server.config()) as db,
        db.transaction() as tx,
    ):
        assert_eq(
            await tx.fetch_all(
                mariadb.raw(
                    "SELECT IS_NULLABLE FROM information_schema.COLUMNS WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='entry' AND COLUMN_NAME='title'"
                )
            ),
            [{"IS_NULLABLE": "NO"}],
        )


@test(mark="slow")
async def mariadb_nullability_matches_names_not_physical_column_order() -> None:
    """Opposite flags, differing case and reversed physical order bind to the right claims."""
    server = await load_fixture(provide_package_server())
    draft = migrations.generate("001", [Entry], backend="mariadb")
    original = draft.target.tables[0]
    title = original.columns[1].model_copy(
        update={
            "nullable": True,
            "definition": "`title` TEXT NULL",
            "query_type": "str | None",
        }
    )
    table = original.model_copy(
        update={
            "sql": "CREATE TABLE entry(TITLE TEXT NULL, ID BIGINT PRIMARY KEY) ENGINE=InnoDB",
            "columns": (original.columns[0], title),
        }
    )
    package = migrations.compile(
        draft.model_copy(
            update={
                "target": migrations.State(backend="mariadb", tables=(table,)),
                "operations": (migrations.CreateTable(table=table),),
            }
        )
    )
    async with migrations.connect(server.config()) as target:
        assert_eq(
            await target.apply(
                await target.prepare(package, schema_writers_excluded=True)
            ),
            "applied",
        )
        assert_eq((await target.status())[0].phase, "complete")
    async with (
        await mariadb.Database.initialize(server.config()) as db,
        db.transaction() as tx,
    ):
        await tx.execute(mariadb.raw("INSERT INTO entry(id,title) VALUES(3,NULL)"))
        assert_eq(
            await tx.fetch_all(
                mariadb.raw("SELECT ID AS id,TITLE AS title FROM entry")
            ),
            [{"id": 3, "title": None}],
        )
        assert_eq(
            await tx.fetch_all(
                mariadb.raw(
                    "SELECT COLUMN_NAME,IS_NULLABLE FROM information_schema.COLUMNS WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='entry' ORDER BY ORDINAL_POSITION"
                )
            ),
            [
                {"COLUMN_NAME": "TITLE", "IS_NULLABLE": "YES"},
                {"COLUMN_NAME": "ID", "IS_NULLABLE": "NO"},
            ],
        )


@test(mark="slow")
async def mariadb_wrong_physical_type_blocks_completion_and_finish() -> None:
    """Generic text storage is not proof of the recorded bounded VARCHAR type."""
    server = await load_fixture(provide_package_server())
    draft = migrations.generate("001", [Entry], backend="mariadb")
    original = draft.target.tables[0]
    table = original.model_copy(
        update={"sql": original.sql.replace("VARCHAR(255)", "LONGTEXT")}
    )
    package = migrations.compile(
        draft.model_copy(
            update={
                "target": migrations.State(backend="mariadb", tables=(table,)),
                "operations": (migrations.CreateTable(table=table),),
            }
        )
    )
    async with migrations.connect(server.config()) as target:
        plan = await target.prepare(package, schema_writers_excluded=True)
        with assert_raises(migrations.PackageError) as error:
            await target.apply(plan)
        assert "type differs" in str(error.exception)
        assert "title" in str(error.exception)
        assert_eq(
            [
                (p.phase, p.acknowledged_steps, p.total_steps)
                for p in await target.status()
            ],
            [("uncertain", 1, 1)],
        )
    async with migrations.connect(server.config()) as target:
        recovery = await target.inspect_recovery(plan, schema_writers_excluded=True)
        assert_eq(recovery.disposition, "ambiguous")
        assert "type differs" in recovery.explanation
        with assert_raises(migrations.PackageError):
            await target.resume(recovery, schema_writers_excluded=True)
    async with (
        await mariadb.Database.initialize(server.config()) as db,
        db.transaction() as tx,
    ):
        assert_eq(
            await tx.fetch_all(
                mariadb.raw(
                    "SELECT DATA_TYPE FROM information_schema.COLUMNS WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='entry' AND COLUMN_NAME='title'"
                )
            ),
            [{"DATA_TYPE": "longtext"}],
        )


class NativeTypes[S = mariadb.Pending](mariadb.Model[S]):
    """Frozen declarations for the generated native storage families."""

    __row_type__: ClassVar[mariadb.ReadType[NativeTypes[mariadb.Row]]]
    id: mariadb.Col[int] = mariadb.Integer(primary_key=True)
    label: mariadb.Col[str] = mariadb.Text(length=12)
    amount: mariadb.Col[Decimal] = mariadb.Decimal(12, 3)
    at: mariadb.Col[mariadb.UtcDatetime] = mariadb.DateTime(precision=6)
    day: mariadb.Col[date] = mariadb.Date()
    enabled: mariadb.Col[bool] = mariadb.Boolean()
    ratio: mariadb.Col[float] = mariadb.Real()
    payload: mariadb.Col[bytes] = mariadb.Blob()
    notes: mariadb.Col[str] = mariadb.LongText()
    metadata: mariadb.JsonCol[dict[str, int]] = mariadb.Json()
    key: mariadb.Col[UUID] = mariadb.Uuid()


@test(mark="slow")
async def mariadb_generated_storage_families_match_native_type_rendering() -> None:
    """Native aliases and integer display widths do not reject generated storage."""
    server = await load_fixture(provide_package_server())
    package = migrations.compile(
        migrations.generate("001", [NativeTypes], backend="mariadb")
    )
    async with migrations.connect(server.config()) as target:
        assert_eq(
            await target.apply(
                await target.prepare(package, schema_writers_excluded=True)
            ),
            "applied",
        )
        assert_eq((await target.status())[0].phase, "complete")
    async with (
        await mariadb.Database.initialize(server.config()) as db,
        db.transaction() as tx,
    ):
        assert_eq(
            await tx.fetch_all(
                mariadb.raw(
                    "SELECT COLUMN_NAME,DATA_TYPE FROM information_schema.COLUMNS WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='native_types' ORDER BY ORDINAL_POSITION"
                )
            ),
            [
                {"COLUMN_NAME": "id", "DATA_TYPE": "bigint"},
                {"COLUMN_NAME": "label", "DATA_TYPE": "varchar"},
                {"COLUMN_NAME": "amount", "DATA_TYPE": "decimal"},
                {"COLUMN_NAME": "at", "DATA_TYPE": "datetime"},
                {"COLUMN_NAME": "day", "DATA_TYPE": "date"},
                {"COLUMN_NAME": "enabled", "DATA_TYPE": "tinyint"},
                {"COLUMN_NAME": "ratio", "DATA_TYPE": "double"},
                {"COLUMN_NAME": "payload", "DATA_TYPE": "blob"},
                {"COLUMN_NAME": "notes", "DATA_TYPE": "longtext"},
                {"COLUMN_NAME": "metadata", "DATA_TYPE": "longtext"},
                {"COLUMN_NAME": "key", "DATA_TYPE": "uuid"},
            ],
        )


@test(mark="slow")
async def mariadb_type_parameters_and_signedness_cannot_silently_change() -> None:
    """Widths, numeric/temporal precision and unsigned domains are physical facts."""
    server = await load_fixture(provide_package_server())
    for old, new, column in (
        ("VARCHAR(12)", "VARCHAR(13)", "label"),
        ("DECIMAL(12,3)", "DECIMAL(13,3)", "amount"),
        ("DECIMAL(12,3)", "DECIMAL(12,2)", "amount"),
        ("DATETIME(6)", "DATETIME(3)", "at"),
        ("BIGINT", "BIGINT UNSIGNED", "id"),
        ("DOUBLE", "FLOAT", "ratio"),
    ):
        await server.reset_database()
        draft = migrations.generate("001", [NativeTypes], backend="mariadb")
        original = draft.target.tables[0]
        assert old in original.sql
        table = original.model_copy(update={"sql": original.sql.replace(old, new, 1)})
        package = migrations.compile(
            draft.model_copy(
                update={
                    "target": migrations.State(backend="mariadb", tables=(table,)),
                    "operations": (migrations.CreateTable(table=table),),
                }
            )
        )
        async with migrations.connect(server.config()) as target:
            plan = await target.prepare(package, schema_writers_excluded=True)
            with assert_raises(migrations.PackageError) as error:
                await target.apply(plan)
            assert "type differs" in str(error.exception)
            assert repr(column) in str(error.exception)
            assert_eq((await target.status())[0].phase, "uncertain")
            assert_eq(
                (
                    await target.inspect_recovery(plan, schema_writers_excluded=True)
                ).disposition,
                "ambiguous",
            )


@test(mark="slow")
async def mariadb_unsupported_recorded_type_is_rejected_before_execution() -> None:
    """An unimplemented modifier must not first commit avoidable native DDL."""
    server = await load_fixture(provide_package_server())
    draft = migrations.generate("001", [Entry], backend="mariadb")
    original = draft.target.tables[0]
    first = original.columns[0].model_copy(
        update={
            "definition": original.columns[0].definition.replace(
                "BIGINT", "BIGINT ZEROFILL"
            )
        }
    )
    table = original.model_copy(
        update={
            "sql": original.sql.replace("BIGINT", "BIGINT ZEROFILL"),
            "columns": (first, original.columns[1]),
        }
    )
    package = migrations.compile(
        draft.model_copy(
            update={
                "target": migrations.State(backend="mariadb", tables=(table,)),
                "operations": (migrations.CreateTable(table=table),),
            }
        )
    )
    async with migrations.connect(server.config()) as target:
        with assert_raises(migrations.PackageError) as error:
            await target.prepare(package, schema_writers_excluded=True)
        assert "unsupported MariaDB type modifier" in str(error.exception)
        assert_eq(await target.status(), ())
    async with (
        await mariadb.Database.initialize(server.config()) as db,
        db.transaction() as tx,
    ):
        assert_eq(await tx.fetch_all(mariadb.raw("SHOW TABLES")), [])


@test(mark="slow")
async def mariadb_binary_charset_type_conversion_needs_explicit_support() -> None:
    """Do not mistake VARCHAR's binary-charset alias for ordinary text storage."""
    server = await load_fixture(provide_package_server())
    draft = migrations.generate("001", [Entry], backend="mariadb")
    original = draft.target.tables[0]
    title = original.columns[1].model_copy(
        update={"definition": "`title` VARCHAR(255) CHARACTER SET binary NOT NULL"}
    )
    table = original.model_copy(
        update={
            "sql": original.sql.replace(
                original.columns[1].definition, title.definition
            ),
            "columns": (original.columns[0], title),
        }
    )
    package = migrations.compile(
        draft.model_copy(
            update={
                "target": migrations.State(backend="mariadb", tables=(table,)),
                "operations": (migrations.CreateTable(table=table),),
            }
        )
    )
    async with migrations.connect(server.config()) as target:
        with assert_raises(migrations.PackageError) as error:
            await target.prepare(package, schema_writers_excluded=True)
        assert "unsupported MariaDB type modifier" in str(error.exception)
        assert_eq(await target.status(), ())


@test(mark="slow")
async def mariadb_observed_unsupported_type_cannot_finish_recovery() -> None:
    """Unknown physical metadata is not permission to certify a known declaration."""
    server = await load_fixture(provide_package_server())
    draft = migrations.generate("001", [Entry], backend="mariadb")
    original = draft.target.tables[0]
    table = original.model_copy(
        update={
            "sql": original.sql.replace(
                original.columns[1].definition, "`title` ENUM('one','two') NOT NULL"
            )
        }
    )
    package = migrations.compile(
        draft.model_copy(
            update={
                "target": migrations.State(backend="mariadb", tables=(table,)),
                "operations": (migrations.CreateTable(table=table),),
            }
        )
    )
    async with migrations.connect(server.config()) as target:
        plan = await target.prepare(package, schema_writers_excluded=True)
        with assert_raises(migrations.PackageError) as error:
            await target.apply(plan)
        assert "unsupported MariaDB storage type" in str(error.exception)
        assert_eq((await target.status())[0].phase, "uncertain")
        recovery = await target.inspect_recovery(plan, schema_writers_excluded=True)
        assert_eq(recovery.disposition, "ambiguous")
        assert "unsupported MariaDB storage type" in recovery.explanation


@test(mark="slow")
async def mariadb_storage_aliases_and_implicit_parameters_preserve_identity() -> None:
    """Literal native spellings bind by name, not order or display formatting."""
    server = await load_fixture(provide_package_server())
    declarations = (
        ("INTEGER", "INT(7)"),
        ("BOOL", "TINYINT(4)"),
        ("NUMERIC", "DECIMAL(10,0)"),
        ("DEC(9)", "DECIMAL(9,0)"),
        ("FIXED(9,2)", "DECIMAL(9,2)"),
        ("DOUBLE PRECISION", "DOUBLE"),
        ("DATETIME(0)", "DATETIME"),
        ("TIME", "TIME(0)"),
        ("TIMESTAMP(0)", "TIMESTAMP"),
        ("CHAR", "CHAR(1)"),
        ("BINARY", "BINARY(1)"),
        ("VARBINARY(8)", "VARBINARY(8)"),
        ("BIT", "BIT(1)"),
        ("TINYTEXT", "TINYTEXT"),
        ("TEXT", "TEXT"),
        ("MEDIUMTEXT", "MEDIUMTEXT"),
        ("TINYBLOB", "TINYBLOB"),
        ("MEDIUMBLOB", "MEDIUMBLOB"),
        ("LONGBLOB", "LONGBLOB"),
        ("FLOAT", "FLOAT"),
        ("SMALLINT(8)", "SMALLINT(5)"),
        ("MEDIUMINT", "MEDIUMINT(9)"),
        ("BIGINT UNSIGNED", "BIGINT(20) UNSIGNED"),
        ("DECIMAL(7,2) UNSIGNED", "DECIMAL(7,2) UNSIGNED"),
        ("DOUBLE UNSIGNED", "DOUBLE UNSIGNED"),
        ("INTEGER SIGNED", "INT(11)"),
    )
    columns = tuple(
        migrations.ColumnState(
            name=f"c{index}",
            definition=f"`c{index}` {declared} NOT NULL",
            nullable=False,
            storage="native",
        )
        for index, (declared, _) in enumerate(declarations)
    )
    definitions = ", ".join(
        f"`C{index}` {physical} NOT NULL"
        for index, (_, physical) in reversed(tuple(enumerate(declarations)))
    )
    table = migrations.TableState(
        name="aliases",
        quoted_name="`aliases`",
        columns=columns,
        sql=f"CREATE TABLE aliases ({definitions}) ENGINE=InnoDB",
    )
    draft = migrations.generate("001", [], backend="mariadb")
    package = migrations.compile(
        draft.model_copy(
            update={
                "target": migrations.State(backend="mariadb", tables=(table,)),
                "operations": (migrations.CreateTable(table=table),),
            }
        )
    )
    async with migrations.connect(server.config()) as target:
        assert_eq(
            await target.apply(
                await target.prepare(package, schema_writers_excluded=True)
            ),
            "applied",
        )
        assert_eq((await target.status())[0].phase, "complete")


@test(mark="slow")
async def mariadb_wrong_collation_blocks_completion_and_finish() -> None:
    """Matching VARCHAR storage cannot certify different comparison semantics."""
    server = await load_fixture(provide_package_server())
    draft = migrations.generate("001", [Entry], backend="mariadb")
    original = draft.target.tables[0]
    title = original.columns[1].model_copy(
        update={
            "definition": "`title` VARCHAR(255) CHARACTER SET utf8mb4 COLLATE utf8mb4_bin NOT NULL"
        }
    )
    table = original.model_copy(
        update={
            "columns": (original.columns[0], title),
            "sql": "CREATE TABLE entry(id BIGINT PRIMARY KEY, title VARCHAR(255) CHARACTER SET utf8mb4 COLLATE utf8mb4_general_ci NOT NULL) ENGINE=InnoDB",
        }
    )
    package = migrations.compile(
        draft.model_copy(
            update={
                "target": migrations.State(backend="mariadb", tables=(table,)),
                "operations": (migrations.CreateTable(table=table),),
            }
        )
    )
    async with migrations.connect(server.config()) as target:
        plan = await target.prepare(package, schema_writers_excluded=True)
        with assert_raises(migrations.PackageError) as error:
            await target.apply(plan)
        assert "collation differs" in str(error.exception)
        assert_eq((await target.status())[0].phase, "uncertain")
    async with migrations.connect(server.config()) as target:
        recovery = await target.inspect_recovery(plan, schema_writers_excluded=True)
        assert_eq(recovery.disposition, "ambiguous")
        assert "collation differs" in recovery.explanation
        with assert_raises(migrations.PackageError):
            await target.resume(recovery, schema_writers_excluded=True)
    async with (
        await mariadb.Database.initialize(server.config()) as db,
        db.transaction() as tx,
    ):
        assert_eq(
            await tx.fetch_all(
                mariadb.raw(
                    "SELECT COLLATION_NAME FROM information_schema.COLUMNS WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='entry' AND COLUMN_NAME='title'"
                )
            ),
            [{"COLLATION_NAME": "utf8mb4_general_ci"}],
        )


@test(mark="slow")
async def mariadb_json_storage_alone_cannot_certify_implicit_collation() -> None:
    """JSON's LONGTEXT alias also records binary comparison semantics."""
    server = await load_fixture(provide_package_server())
    draft = migrations.generate("001", [NativeTypes], backend="mariadb")
    original = draft.target.tables[0]
    assert "`metadata` JSON" in original.sql
    table = original.model_copy(
        update={
            "sql": original.sql.replace(
                "`metadata` JSON",
                "`metadata` LONGTEXT CHARACTER SET utf8mb4 COLLATE utf8mb4_general_ci",
            )
        }
    )
    package = migrations.compile(
        draft.model_copy(
            update={
                "target": migrations.State(backend="mariadb", tables=(table,)),
                "operations": (migrations.CreateTable(table=table),),
            }
        )
    )
    async with migrations.connect(server.config()) as target:
        plan = await target.prepare(package, schema_writers_excluded=True)
        with assert_raises(migrations.PackageError) as error:
            await target.apply(plan)
        assert "collation differs" in str(error.exception)
        assert "metadata" in str(error.exception)
        assert_eq((await target.status())[0].phase, "uncertain")
        recovery = await target.inspect_recovery(plan, schema_writers_excluded=True)
        assert_eq(recovery.disposition, "ambiguous")
        assert "collation differs" in recovery.explanation


@test(mark="slow")
async def mariadb_unimplemented_collation_position_is_not_silently_ignored() -> None:
    """Unsupported column-attribute syntax needs review before native effects."""
    server = await load_fixture(provide_package_server())
    draft = migrations.generate("001", [Entry], backend="mariadb")
    original = draft.target.tables[0]
    title = original.columns[1].model_copy(
        update={"definition": "`title` VARCHAR(255) NOT NULL COLLATE utf8mb4_bin"}
    )
    table = original.model_copy(update={"columns": (original.columns[0], title)})
    package = migrations.compile(
        draft.model_copy(
            update={
                "target": migrations.State(backend="mariadb", tables=(table,)),
                "operations": (migrations.CreateTable(table=table),),
            }
        )
    )
    async with migrations.connect(server.config()) as target:
        with assert_raises(migrations.PackageError) as error:
            await target.prepare(package, schema_writers_excluded=True)
        assert "unsupported MariaDB collation position" in str(error.exception)
        assert_eq(await target.status(), ())


@test(mark="slow")
async def mariadb_collations_bind_by_name_and_ignore_default_literal_words() -> None:
    """Equal types/nullability cannot hide swapped collations or quoted defaults."""
    server = await load_fixture(provide_package_server())
    columns = (
        migrations.ColumnState(
            name="first",
            definition="`first` VARCHAR(64) CHARACTER SET utf8mb4 COLLATE UTF8MB4_BIN NOT NULL DEFAULT 'COLLATE utf8mb4_general_ci'",
            nullable=False,
            storage="TEXT",
        ),
        migrations.ColumnState(
            name="second",
            definition="`second` VARCHAR(64) CHARACTER SET utf8mb4 COLLATE utf8mb4_general_ci NOT NULL DEFAULT 'COLLATE utf8mb4_bin'",
            nullable=False,
            storage="TEXT",
        ),
    )
    table = migrations.TableState(
        name="collated",
        quoted_name="`collated`",
        columns=columns,
        sql="CREATE TABLE collated (`SECOND` VARCHAR(64) CHARACTER SET utf8mb4 COLLATE utf8mb4_general_ci NOT NULL DEFAULT 'COLLATE utf8mb4_bin', `FIRST` VARCHAR(64) CHARACTER SET utf8mb4 COLLATE utf8mb4_bin NOT NULL DEFAULT 'COLLATE utf8mb4_general_ci') ENGINE=InnoDB",
    )
    draft = migrations.generate("001", [], backend="mariadb")
    package = migrations.compile(
        draft.model_copy(
            update={
                "target": migrations.State(backend="mariadb", tables=(table,)),
                "operations": (migrations.CreateTable(table=table),),
            }
        )
    )
    async with migrations.connect(server.config()) as target:
        assert_eq(
            await target.apply(
                await target.prepare(package, schema_writers_excluded=True)
            ),
            "applied",
        )
        assert_eq((await target.status())[0].phase, "complete")
    async with (
        await mariadb.Database.initialize(server.config()) as db,
        db.transaction() as tx,
    ):
        assert_eq(
            await tx.fetch_all(
                mariadb.raw(
                    "SELECT COLUMN_NAME,COLLATION_NAME FROM information_schema.COLUMNS WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='collated' ORDER BY ORDINAL_POSITION"
                )
            ),
            [
                {"COLUMN_NAME": "SECOND", "COLLATION_NAME": "utf8mb4_general_ci"},
                {"COLUMN_NAME": "FIRST", "COLLATION_NAME": "utf8mb4_bin"},
            ],
        )


@test(mark="slow")
async def mariadb_missing_auto_increment_blocks_completion_and_finish() -> None:
    """A primary key is not proof of the recorded server-side ID generator."""
    server = await load_fixture(provide_package_server())
    draft = migrations.generate("001", [Entry], backend="mariadb")
    original = draft.target.tables[0]
    identifier = original.columns[0].model_copy(
        update={"definition": "`id` BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY"}
    )
    table = original.model_copy(update={"columns": (identifier, original.columns[1])})
    package = migrations.compile(
        draft.model_copy(
            update={
                "target": migrations.State(backend="mariadb", tables=(table,)),
                "operations": (migrations.CreateTable(table=table),),
            }
        )
    )
    async with migrations.connect(server.config()) as target:
        plan = await target.prepare(package, schema_writers_excluded=True)
        with assert_raises(migrations.PackageError) as error:
            await target.apply(plan)
        assert "AUTO_INCREMENT differs" in str(error.exception)
        assert_eq((await target.status())[0].phase, "uncertain")
    async with migrations.connect(server.config()) as target:
        recovery = await target.inspect_recovery(plan, schema_writers_excluded=True)
        assert_eq(recovery.disposition, "ambiguous")
        assert "AUTO_INCREMENT differs" in recovery.explanation
        with assert_raises(migrations.PackageError):
            await target.resume(recovery, schema_writers_excluded=True)
    async with (
        await mariadb.Database.initialize(server.config()) as db,
        db.transaction() as tx,
    ):
        assert_eq(
            await tx.fetch_all(
                mariadb.raw(
                    "SELECT EXTRA FROM information_schema.COLUMNS WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='entry' AND COLUMN_NAME='id'"
                )
            ),
            [{"EXTRA": ""}],
        )


@test(mark="slow")
async def mariadb_unrequested_auto_increment_cannot_complete() -> None:
    """A stricter server-side generation policy is not the declared contract either."""
    server = await load_fixture(provide_package_server())
    draft = migrations.generate("001", [Entry], backend="mariadb")
    original = draft.target.tables[0]
    table = original.model_copy(
        update={
            "sql": original.sql.replace(
                original.columns[0].definition,
                "`id` BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY",
            )
        }
    )
    package = migrations.compile(
        draft.model_copy(
            update={
                "target": migrations.State(backend="mariadb", tables=(table,)),
                "operations": (migrations.CreateTable(table=table),),
            }
        )
    )
    async with migrations.connect(server.config()) as target:
        plan = await target.prepare(package, schema_writers_excluded=True)
        with assert_raises(migrations.PackageError) as error:
            await target.apply(plan)
        assert "AUTO_INCREMENT differs" in str(error.exception)
        assert_eq((await target.status())[0].phase, "uncertain")
        recovery = await target.inspect_recovery(plan, schema_writers_excluded=True)
        assert_eq(recovery.disposition, "ambiguous")
        assert "AUTO_INCREMENT differs" in recovery.explanation


@test(mark="slow")
async def mariadb_auto_increment_binds_by_name_without_claiming_counter_values() -> (
    None
):
    """Names/literals do not create a generator claim; inserts may advance its counter."""
    server = await load_fixture(provide_package_server())

    class AutoEntry[S = mariadb.Pending](mariadb.Model[S]):
        __row_type__: ClassVar[mariadb.ReadType[AutoEntry[mariadb.Row]]]
        id: mariadb.Col[int] = mariadb.Integer(primary_key=True, auto_increment=True)
        auto_increment: mariadb.Col[int] = mariadb.Integer()

    draft = migrations.generate("001", [AutoEntry], backend="mariadb")
    original = draft.target.tables[0]
    value = original.columns[1].model_copy(
        update={
            "definition": "`auto_increment` BIGINT NOT NULL DEFAULT 9 COMMENT 'AUTO_INCREMENT'"
        }
    )
    table = original.model_copy(
        update={
            "columns": (original.columns[0], value),
            "sql": "CREATE TABLE auto_entry (`AUTO_INCREMENT` BIGINT NOT NULL DEFAULT 9 COMMENT 'AUTO_INCREMENT', `ID` BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY) ENGINE=InnoDB",
        }
    )
    package = migrations.compile(
        draft.model_copy(
            update={
                "target": migrations.State(backend="mariadb", tables=(table,)),
                "operations": (migrations.CreateTable(table=table),),
            }
        )
    )
    async with migrations.connect(server.config()) as target:
        assert_eq(
            await target.apply(
                await target.prepare(package, schema_writers_excluded=True)
            ),
            "applied",
        )
    async with (
        await mariadb.Database.initialize(server.config()) as db,
        db.transaction() as tx,
    ):
        await tx.execute(mariadb.raw("INSERT INTO auto_entry () VALUES (), ()"))
        assert_eq(
            await tx.fetch_all(
                mariadb.raw("SELECT id, `auto_increment` FROM auto_entry ORDER BY id")
            ),
            [{"id": 1, "auto_increment": 9}, {"id": 2, "auto_increment": 9}],
        )
    followup = migrations.compile(
        migrations.Draft(
            revision="002",
            predecessor=package.digest,
            before=package.target,
            target=package.target,
            operations=(),
        )
    )
    async with migrations.connect(server.config()) as target:
        assert_eq(
            await target.apply(
                await target.prepare(followup, schema_writers_excluded=True)
            ),
            "applied",
        )
        assert_eq(
            [progress.phase for progress in await target.status()],
            ["complete", "complete"],
        )


@test(mark="slow")
async def mariadb_auto_increment_in_unparsed_attribute_text_requires_review() -> None:
    """A bare word in an unsupported default must not become a generator claim."""
    server = await load_fixture(provide_package_server())
    draft = migrations.generate("001", [Entry], backend="mariadb")
    original = draft.target.tables[0]
    title = original.columns[1].model_copy(
        update={"definition": "`title` VARCHAR(255) NOT NULL DEFAULT auto_increment"}
    )
    table = original.model_copy(update={"columns": (original.columns[0], title)})
    package = migrations.compile(
        draft.model_copy(
            update={
                "target": migrations.State(backend="mariadb", tables=(table,)),
                "operations": (migrations.CreateTable(table=table),),
            }
        )
    )
    async with migrations.connect(server.config()) as target:
        with assert_raises(migrations.PackageError) as error:
            await target.prepare(package, schema_writers_excluded=True)
        assert "unsupported MariaDB AUTO_INCREMENT position" in str(error.exception)
        assert_eq(await target.status(), ())

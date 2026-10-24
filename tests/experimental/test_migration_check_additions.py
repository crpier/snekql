"""Bounded named CHECK additions through frozen migration routes."""

import json
from pathlib import Path
from sqlite3 import IntegrityError
from tempfile import TemporaryDirectory
from typing import ClassVar

import aiosqlite
from pymysql.err import IntegrityError as NativeIntegrityError
from pymysql.err import OperationalError
from snektest import assert_eq, assert_raises, load_fixture, test

from snekql import mariadb, sqlite
from snekql.experimental import migrations as m
from tests.experimental.test_migration_nullability import (
    NativeRequired,
    Optional,
    Required,
)
from tests.experimental.test_migration_targets import provide_package_server


class Checked[S = sqlite.Pending](sqlite.Model[S]):
    """An existing column gains a named table CHECK, not a data repair."""

    __tablename__ = "entries"
    __row_type__: ClassVar[sqlite.ReadType[Checked[sqlite.Row]]]
    id: sqlite.Col[int] = sqlite.Integer(primary_key=True)
    value: sqlite.GenCol[int] = sqlite.Integer(default=sqlite.LiteralDefault(7))

    @classmethod
    def __checks__(cls) -> list[sqlite.CheckConstraint[Checked[S]]]:
        return [sqlite.CheckConstraint(cls.value.gte(0), name="ck_nonnegative")]


@test(mark="medium")
async def sqlite_check_addition_rejects_old_rows_without_repair_and_can_retry() -> None:
    """Invalid existing data rolls back the rebuild/receipt; explicit correction permits retry."""
    first = m.compile(m.generate("001", [Required], backend="sqlite"))
    second = m.Package.load(
        m.compile(m.generate("002", [Checked], backend="sqlite", previous=first)).dump()
    )
    assert_eq(second.version, 7)
    with TemporaryDirectory() as directory:
        config = sqlite.Config(database=Path(directory) / "checks.db")
        async with m.connect(config) as target:
            await target.apply(await target.prepare(first))
        async with (
            await sqlite.Database.initialize(config) as db,
            db.transaction() as tx,
        ):
            await tx.execute(sqlite.raw("INSERT INTO entries VALUES(1,-1),(2,42)"))
        async with m.connect(config) as target:
            plan = await target.prepare(second)
            with assert_raises(IntegrityError):
                await target.apply(plan)
            assert_eq(len(await target.status()), 1)
        async with (
            await sqlite.Database.initialize(config) as db,
            db.transaction() as tx,
        ):
            assert_eq(
                await tx.fetch_all(sqlite.raw("SELECT value FROM entries ORDER BY id")),
                [{"value": -1}, {"value": 42}],
            )
            await tx.execute(sqlite.raw("UPDATE entries SET value=0 WHERE id=1"))
        async with m.connect(config) as target:
            await target.apply(plan)
            assert_eq(
                await target.apply(await target.prepare(second)), "already_applied"
            )
        async with await sqlite.Database.initialize(config) as db:
            async with db.transaction() as tx:
                await tx.execute(sqlite.raw("INSERT INTO entries(id) VALUES(3)"))
                assert_eq(
                    await tx.fetch_all(
                        sqlite.raw("SELECT value FROM entries ORDER BY id")
                    ),
                    [{"value": 0}, {"value": 42}, {"value": 7}],
                )
            with assert_raises(sqlite.ExecutionError):
                async with db.transaction() as tx:
                    await tx.execute(sqlite.raw("INSERT INTO entries VALUES(4,-2)"))


class NativeChecked[S = mariadb.Pending](mariadb.Model[S]):
    """A named native CHECK added independently of column/default changes."""

    __tablename__ = "entries"
    __row_type__: ClassVar[mariadb.ReadType[NativeChecked[mariadb.Row]]]
    id: mariadb.Col[int] = mariadb.Integer(primary_key=True)
    value: mariadb.GenCol[int] = mariadb.Integer(default=mariadb.LiteralDefault(7))

    @classmethod
    def __checks__(cls) -> list[mariadb.CheckConstraint[NativeChecked[S]]]:
        return [mariadb.CheckConstraint(cls.value.gte(0), name="ck_nonnegative")]


@test(mark="slow")
async def native_check_addition_refuses_disabled_check_enforcement_without_a_receipt() -> (
    None
):
    """A declared CHECK must not falsely certify addition over invalid existing rows."""
    server = await load_fixture(provide_package_server())
    first = m.compile(m.generate("001", [NativeRequired], backend="mariadb"))
    second = m.compile(
        m.generate("002", [NativeChecked], backend="mariadb", previous=first)
    )
    async with m.connect(server.config()) as target:
        await target.apply(await target.prepare(first, schema_writers_excluded=True))
    await server.run_sql("INSERT INTO entries VALUES(1,-1)")
    await server.run_sql("SET GLOBAL check_constraint_checks=0")
    try:
        async with m.connect(server.config()) as target:
            with assert_raises(m.PackageError) as error:
                await target.apply(
                    await target.prepare(second, schema_writers_excluded=True)
                )
            assert "CHECK addition" in str(error.exception)
            assert_eq(len(await target.status()), 1)
    finally:
        await server.run_sql("SET GLOBAL check_constraint_checks=1")


@test(mark="medium")
async def sqlite_check_addition_cannot_reuse_an_unmanaged_constraint_name() -> None:
    """Preservation does not authorize a second declaration under an existing name."""
    first = m.compile(m.generate("001", [Required], backend="sqlite"))
    second = m.compile(m.generate("002", [Checked], backend="sqlite", previous=first))
    with TemporaryDirectory() as directory:
        config = sqlite.Config(database=Path(directory) / "collision.db")
        async with m.connect(config) as target:
            await target.apply(await target.prepare(first))
        sql = first.target.tables[0].sql.replace(
            ") STRICT", ', CONSTRAINT "ck_nonnegative" CHECK ("value" <= 100)) STRICT'
        )
        assert sql != first.target.tables[0].sql
        async with aiosqlite.connect(str(config.database)) as app:
            await app.execute("DROP TABLE entries")
            await app.execute(sql)
            await app.commit()
        async with m.connect(config) as target:
            with assert_raises(m.PackageError) as error:
                await target.prepare(second, preserve_unmanaged=True)
            assert "constraint name" in str(error.exception)
            assert_eq(len(await target.status()), 1)


@test(mark="slow")
async def native_failed_check_addition_can_retry_after_explicit_data_correction() -> (
    None
):
    """Native DDL validates old rows; recovery retries the rejected ALTER, without backfill."""
    server = await load_fixture(provide_package_server())
    first = m.compile(m.generate("001", [NativeRequired], backend="mariadb"))
    second = m.Package.load(
        m.compile(
            m.generate("002", [NativeChecked], backend="mariadb", previous=first)
        ).dump()
    )
    async with m.connect(server.config()) as target:
        await target.apply(await target.prepare(first, schema_writers_excluded=True))
    await server.run_sql("INSERT INTO entries VALUES(1,-1),(2,42)")
    async with m.connect(server.config()) as target:
        plan = await target.prepare(second, schema_writers_excluded=True)
        with assert_raises(OperationalError) as error:
            await target.apply(plan)
        assert "ck_nonnegative" in str(error.exception)
        recovery = await target.inspect_recovery(plan, schema_writers_excluded=True)
        assert_eq(recovery.disposition, "retry_remaining")
        assert_eq(recovery.acknowledged_steps, 0)
    async with (
        await mariadb.Database.initialize(server.config()) as db,
        db.transaction() as tx,
    ):
        assert_eq(
            await tx.fetch_all(mariadb.raw("SELECT value FROM entries ORDER BY id")),
            [{"value": -1}, {"value": 42}],
        )
        await tx.execute(mariadb.raw("UPDATE entries SET value=0 WHERE id=1"))
    async with m.connect(server.config()) as target:
        recovery = await target.inspect_recovery(plan, schema_writers_excluded=True)
        await target.resume(recovery, schema_writers_excluded=True)
        assert_eq(
            await target.apply(
                await target.prepare(second, schema_writers_excluded=True)
            ),
            "already_applied",
        )
    async with await mariadb.Database.initialize(server.config()) as db:
        async with db.transaction() as tx:
            await tx.execute(mariadb.raw("INSERT INTO entries(id) VALUES(3)"))
            assert_eq(
                await tx.fetch_all(
                    mariadb.raw("SELECT value FROM entries ORDER BY id")
                ),
                [{"value": 0}, {"value": 42}, {"value": 7}],
            )
        with assert_raises(mariadb.ExecutionError):
            async with db.transaction() as tx:
                await tx.execute(mariadb.raw("INSERT INTO entries VALUES(4,-2)"))


@test(mark="slow")
async def lost_native_check_receipt_is_ambiguous_even_when_the_constraint_is_present() -> (
    None
):
    """An endpoint is not a receipt and never authorizes replaying an ADD CONSTRAINT."""
    server = await load_fixture(provide_package_server())
    first = m.compile(m.generate("001", [NativeRequired], backend="mariadb"))
    second = m.compile(
        m.generate("002", [NativeChecked], backend="mariadb", previous=first)
    )
    async with m.connect(server.config()) as target:
        await target.apply(await target.prepare(first, schema_writers_excluded=True))
    await server.run_sql("INSERT INTO entries VALUES(1,42)")
    await server.run_sql(
        "CREATE TRIGGER fail_receipt BEFORE UPDATE ON snekql_experimental_migrations FOR EACH ROW SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='receipt unavailable'"
    )
    async with m.connect(server.config()) as target:
        plan = await target.prepare(second, schema_writers_excluded=True)
        with assert_raises(OperationalError):
            await target.apply(plan)
    await server.run_sql("DROP TRIGGER fail_receipt")
    async with m.connect(server.config()) as target:
        recovery = await target.inspect_recovery(plan, schema_writers_excluded=True)
        assert_eq(recovery.disposition, "ambiguous")
        assert_eq(recovery.acknowledged_steps, 0)
        with assert_raises(m.PackageError):
            await target.resume(recovery, schema_writers_excluded=True)
        with assert_raises(m.PackageError):
            await target.reconcile(
                recovery, reason="CHECK exists", schema_writers_excluded=True
            )
    async with await mariadb.Database.initialize(server.config()) as db:
        async with db.transaction() as tx:
            assert_eq(
                await tx.fetch_all(mariadb.raw("SELECT value FROM entries")),
                [{"value": 42}],
            )
        with assert_raises(mariadb.ExecutionError):
            async with db.transaction() as tx:
                await tx.execute(mariadb.raw("INSERT INTO entries VALUES(2,-1)"))


@test(mark="fast")
def check_additions_have_a_closed_grammar_and_explicit_format() -> None:
    """Names, columns, expression work and vocabulary are checked before deployment."""
    first = m.compile(m.generate("001", [Required], backend="sqlite"))
    draft = m.generate("002", [Checked], backend="sqlite", previous=first)
    package = m.compile(draft)
    for version in (2, 3, 4, 5, 6):
        data = json.loads(package.dump())
        data["version"] = version
        with assert_raises(m.PackageError) as error:
            m.Package.load(json.dumps(data))
        assert "require execution package version 7" in str(error.exception)
    for definition in (
        'CHECK ("value" >= 0)',
        'CONSTRAINT "ck" CHECK ("missing" >= 0)',
        'CONSTRAINT "ck" CHECK (ABS("value") >= 0)',
        'CONSTRAINT "ck" CHECK ("value" >= 0) NOT ENFORCED',
        'CONSTRAINT "ck" CHECK ("value" >= 0); DROP TABLE "entries"',
        'CONSTRAINT "ck" CHECK ("value" >= 0) -- comment',
        'CONSTRAINT "ck" CHECK (' + "NOT " * 40 + '"value" >= 0)',
    ):
        with assert_raises(m.PackageError):
            m.compile(
                draft.model_copy(
                    update={
                        "operations": (
                            m.AddCheck(table_name="entries", definition=definition),
                        )
                    }
                )
            )
    old = m.compile(m.generate("001", [Checked], backend="sqlite"))
    removed = m.generate("002", [Required], backend="sqlite", previous=old)
    assert removed.unresolved
    assert_eq(removed.operations, ())
    with assert_raises(m.PackageError):
        m.compile(removed)
    with assert_raises(m.PackageError) as error:
        m.compile(
            m.generate("002", [Checked], backend="sqlite", previous=old).then(
                m.AddCheck(
                    table_name="entries",
                    definition='CONSTRAINT "CK_NONNEGATIVE" CHECK ("value" <= 100)',
                )
            )
        )
    assert "new constraint name" in str(error.exception)
    legacy = m.compile(m.generate("002", [Optional], backend="sqlite", previous=first))
    data = json.loads(legacy.dump())
    data["contractions"][0]["added_checks"] = []
    with assert_raises(m.PackageError) as error:
        m.Package.load(json.dumps(data))
    assert "require execution package version 7" in str(error.exception)


@test(mark="medium")
async def sqlite_check_then_data_failure_rolls_back_and_preserves_unmanaged_objects() -> (
    None
):
    """The checked rebuild and later DML share atomicity without replaying insert triggers."""
    first = m.compile(m.generate("001", [Required], backend="sqlite"))
    draft = m.generate("002", [Checked], backend="sqlite", previous=first).then(
        m.Checkpoint(name="checked")
    )
    assert "CheckConstraint" not in m.contract_source(
        draft, point="checked", table="entries"
    )
    second = m.Package.load(
        m.compile(
            draft.then(
                m.DataChange.from_query(
                    sqlite.update(Checked).set(Checked.id.to(42)).all(),
                    checkpoint="checked",
                    contract_digest=m.contract_digest(draft, point="checked"),
                )
            )
        ).dump()
    )
    with TemporaryDirectory() as directory:
        config = sqlite.Config(database=Path(directory) / "preserved.db")
        async with m.connect(config) as target:
            await target.apply(await target.prepare(first))
        async with aiosqlite.connect(str(config.database)) as app:
            for sql in (
                "ALTER TABLE entries ADD COLUMN payload BLOB DEFAULT X'00FF'",
                "CREATE INDEX external_payload ON entries(payload)",
                "CREATE TABLE audit(value INTEGER)",
                "CREATE TRIGGER audit_insert AFTER INSERT ON entries BEGIN INSERT INTO audit VALUES(new.value); END",
                "CREATE VIEW visible_entries AS SELECT id,value,payload FROM entries",
                "INSERT INTO entries VALUES(1,5,X'AB'),(2,6,X'CD')",
            ):
                await app.execute(sql)
            await app.commit()
        async with m.connect(config) as target:
            plan = await target.prepare(second, preserve_unmanaged=True)
            with assert_raises(IntegrityError):
                await target.apply(plan)
            assert_eq(len(await target.status()), 1)
        async with (
            await sqlite.Database.initialize(config) as db,
            db.transaction() as tx,
        ):
            assert_eq(
                await tx.fetch_all(
                    sqlite.raw("SELECT * FROM visible_entries ORDER BY id")
                ),
                [
                    {"id": 1, "value": 5, "payload": bytes.fromhex("ab")},
                    {"id": 2, "value": 6, "payload": bytes.fromhex("cd")},
                ],
            )
            await tx.execute(sqlite.raw("DELETE FROM entries WHERE id=2"))
        async with m.connect(config) as target:
            await target.apply(plan)
        async with (
            await sqlite.Database.initialize(config) as db,
            db.transaction() as tx,
        ):
            assert_eq(
                await tx.fetch_all(sqlite.raw("SELECT * FROM visible_entries")),
                [{"id": 42, "value": 5, "payload": bytes.fromhex("ab")}],
            )
            assert_eq(
                await tx.fetch_all(sqlite.raw("SELECT * FROM audit ORDER BY rowid")),
                [{"value": 5}, {"value": 6}],
            )
            assert_eq(
                await tx.fetch_all(
                    sqlite.raw(
                        "SELECT name FROM sqlite_schema WHERE type='index' AND tbl_name='entries'"
                    )
                ),
                [{"name": "external_payload"}],
            )
            await tx.execute(sqlite.raw("INSERT INTO entries(id) VALUES(3)"))
            assert_eq(
                await tx.fetch_all(
                    sqlite.raw("SELECT payload FROM visible_entries WHERE id=3")
                ),
                [{"payload": bytes.fromhex("00ff")}],
            )


@test(mark="slow")
async def acknowledged_native_check_is_not_replayed_after_a_later_data_failure() -> (
    None
):
    """A failed UPDATE resumes after the acknowledged CHECK, retaining old values."""
    server = await load_fixture(provide_package_server())
    first = m.compile(m.generate("001", [NativeRequired], backend="mariadb"))
    draft = m.generate("002", [NativeChecked], backend="mariadb", previous=first).then(
        m.Checkpoint(name="checked")
    )
    second = m.Package.load(
        m.compile(
            draft.then(
                m.DataChange.from_query(
                    mariadb.update(NativeChecked).set(NativeChecked.id.to(42)).all(),
                    checkpoint="checked",
                    contract_digest=m.contract_digest(draft, point="checked"),
                )
            )
        ).dump()
    )
    async with m.connect(server.config()) as target:
        await target.apply(await target.prepare(first, schema_writers_excluded=True))
    await server.run_sql("INSERT INTO entries VALUES(1,5),(2,6)")
    async with m.connect(server.config()) as target:
        plan = await target.prepare(second, schema_writers_excluded=True)
        with assert_raises(NativeIntegrityError):
            await target.apply(plan)
        recovery = await target.inspect_recovery(plan, schema_writers_excluded=True)
        assert_eq(recovery.disposition, "retry_remaining")
        assert_eq(recovery.acknowledged_steps, 1)
    await server.run_sql("DELETE FROM entries WHERE id=2")
    async with m.connect(server.config()) as target:
        recovery = await target.inspect_recovery(plan, schema_writers_excluded=True)
        await target.resume(recovery, schema_writers_excluded=True)
    async with (
        await mariadb.Database.initialize(server.config()) as db,
        db.transaction() as tx,
    ):
        assert_eq(
            await tx.fetch_all(mariadb.raw("SELECT id,value FROM entries")),
            [{"id": 42, "value": 5}],
        )


@test(mark="medium")
def frozen_check_metadata_counts_toward_the_aggregate_sql_budget() -> None:
    """Repeated CHECK source strings in deferred metadata cannot escape byte charging."""
    first = m.compile(m.generate("001", [Required], backend="sqlite"))
    definitions = tuple(
        f'CONSTRAINT "ck_{name}" CHECK (' + " " * 450_000 + '"value" >= 0)'
        for name in ("a", "b")
    )
    table = first.target.tables[0]
    target = table.model_copy(
        update={
            "sql": table.sql.replace(
                ") STRICT", ", " + ", ".join(definitions) + ") STRICT"
            )
        }
    )
    draft = m.Draft(
        revision="002",
        predecessor=first.digest,
        before=first.target,
        target=m.State(backend="sqlite", tables=(target,)),
        operations=tuple(
            m.AddCheck(table_name="entries", definition=definition)
            for definition in definitions
        ),
    )
    with assert_raises(m.PackageError) as error:
        m.compile(draft)
    assert "aggregate SQL" in str(error.exception)

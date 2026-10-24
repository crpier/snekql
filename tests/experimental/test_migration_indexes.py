"""Named index additions through frozen migration routes."""

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
from tests.experimental.test_migration_nullability import NativeRequired, Required
from tests.experimental.test_migration_targets import provide_package_server


class Indexed[S = sqlite.Pending](sqlite.Model[S]):
    """The same table with a separate managed unique index."""

    __tablename__ = "entries"
    __row_type__: ClassVar[sqlite.ReadType[Indexed[sqlite.Row]]]
    id: sqlite.Col[int] = sqlite.Integer(primary_key=True)
    value: sqlite.GenCol[int] = sqlite.Integer(default=sqlite.LiteralDefault(7))
    __indexes__: ClassVar = [sqlite.Index(value, name="by_value", unique=True)]


@test(mark="medium")
async def sqlite_adds_a_frozen_named_index_without_rebuilding_rows() -> None:
    """A populated table gains an index without recreating its rows or defaults."""
    first = m.compile(m.generate("001", [Required], backend="sqlite"))
    second = m.Package.load(
        m.compile(m.generate("002", [Indexed], backend="sqlite", previous=first)).dump()
    )
    assert_eq(second.version, 5)
    with TemporaryDirectory() as directory:
        config = sqlite.Config(database=Path(directory) / "indexes.db")
        async with m.connect(config) as target:
            await target.apply(await target.prepare(first))
        async with (
            await sqlite.Database.initialize(config) as db,
            db.transaction() as tx,
        ):
            await tx.execute(sqlite.raw("INSERT INTO entries VALUES(1,42)"))
        async with m.connect(config) as target:
            await target.apply(await target.prepare(second))
            assert_eq(
                await target.apply(await target.prepare(second)), "already_applied"
            )
        async with (
            await sqlite.Database.initialize(config) as db,
            db.transaction() as tx,
        ):
            await tx.execute(sqlite.raw("INSERT INTO entries(id) VALUES(2)"))
            assert_eq(
                await tx.fetch_all(sqlite.raw("SELECT value FROM entries ORDER BY id")),
                [{"value": 42}, {"value": 7}],
            )
            assert_eq(
                await tx.fetch_all(
                    sqlite.raw(
                        "SELECT name FROM sqlite_schema WHERE type='index' AND tbl_name='entries'"
                    )
                ),
                [{"name": "by_value"}],
            )


class NativeIndexed[S = mariadb.Pending](mariadb.Model[S]):
    """Native table with an additional named whole-column index."""

    __tablename__ = "entries"
    __row_type__: ClassVar[mariadb.ReadType[NativeIndexed[mariadb.Row]]]
    id: mariadb.Col[int] = mariadb.Integer(primary_key=True)
    value: mariadb.GenCol[int] = mariadb.Integer(default=mariadb.LiteralDefault(7))
    __indexes__: ClassVar = [mariadb.Index(value, name="by_value", unique=True)]


@test(mark="slow")
async def native_adds_frozen_index_preserving_rows_and_proves_it_afterward() -> None:
    """Acknowledged native creation retains rows; subsequent missing-index drift refuses."""
    server = await load_fixture(provide_package_server())
    first = m.compile(m.generate("001", [NativeRequired], backend="mariadb"))
    second = m.Package.load(
        m.compile(
            m.generate("002", [NativeIndexed], backend="mariadb", previous=first)
        ).dump()
    )
    async with m.connect(server.config()) as target:
        await target.apply(await target.prepare(first, schema_writers_excluded=True))
    await server.run_sql("INSERT INTO entries VALUES(1,42)")
    async with m.connect(server.config()) as target:
        await target.apply(await target.prepare(second, schema_writers_excluded=True))
        assert_eq(
            await target.apply(
                await target.prepare(second, schema_writers_excluded=True)
            ),
            "already_applied",
        )
    async with (
        await mariadb.Database.initialize(server.config()) as db,
        db.transaction() as tx,
    ):
        await tx.execute(mariadb.raw("INSERT INTO entries(id) VALUES(2)"))
        assert_eq(
            await tx.fetch_all(mariadb.raw("SELECT value FROM entries ORDER BY id")),
            [{"value": 42}, {"value": 7}],
        )
    third = m.compile(
        m.generate("003", [NativeIndexed], backend="mariadb", previous=second)
    )
    await server.run_sql("DROP INDEX by_value ON entries")
    async with m.connect(server.config()) as target:
        with assert_raises(m.PackageError):
            await target.prepare(third, schema_writers_excluded=True)
        assert_eq(len(await target.status()), 2)


@test(mark="fast")
def index_additions_have_closed_grammar_and_explicit_format() -> None:
    """No conditional adoption, expressions, prefixes, predicates or unrelated owners."""
    first = m.compile(m.generate("001", [Required], backend="sqlite"))
    draft = m.generate("002", [Indexed], backend="sqlite", previous=first)
    package = m.compile(draft)
    for version in (2, 3, 4):
        data = json.loads(package.dump())
        data["version"] = version
        with assert_raises(m.PackageError) as error:
            m.Package.load(json.dumps(data))
        assert "require execution package version 5" in str(error.exception)
    for sql in (
        "",
        "CREATE INDEX",
        'CREATE INDEX IF NOT EXISTS "by_value" ON "entries" ("value")',
        'CREATE INDEX "by_value" ON "other" ("value")',
        'CREATE INDEX "by_value" ON "entries" ("missing")',
        'CREATE INDEX "by_value" ON "entries" ("value" DESC)',
        'CREATE INDEX "by_value" ON "entries" ("value"(2))',
        'CREATE INDEX "by_value" ON "entries" (("value"+1))',
        'CREATE INDEX "by_value" ON "entries" ("value") WHERE "value">0',
        'CREATE INDEX "by_value" ON "entries" ("value") /* comment */',
        'CREATE INDEX "by_value" ON "entries" ("value"); DROP TABLE "entries"',
    ):
        table = draft.target.tables[0].model_copy(update={"indexes": (sql,)})
        malformed = draft.model_copy(
            update={
                "target": draft.target.model_copy(update={"tables": (table,)}),
                "operations": (m.CreateIndex(table_name="entries", sql=sql),),
            }
        )
        with assert_raises(m.PackageError) as error:
            m.compile(malformed)
        assert "unsupported index addition" in str(error.exception)


@test(mark="fast")
def removing_or_replacing_an_index_remains_an_explicit_unsupported_decision() -> None:
    """Addition support does not silently remove a unique constraint or reuse its name."""
    first = m.compile(m.generate("001", [Indexed], backend="sqlite"))
    draft = m.generate("002", [Required], backend="sqlite", previous=first)
    assert draft.unresolved
    assert_eq(draft.operations, ())
    with assert_raises(m.PackageError):
        m.compile(draft)
    sql = 'CREATE INDEX "BY_VALUE" ON "entries" ("id")'
    same = m.generate("002", [Indexed], backend="sqlite", previous=first)
    with assert_raises(m.PackageError) as error:
        m.compile(same.then(m.CreateIndex(table_name="entries", sql=sql)))
    assert "new managed index name" in str(error.exception)


@test(mark="medium")
async def unique_index_conflict_rolls_back_and_original_plan_can_retry() -> None:
    """Existing duplicates cannot be certified; correcting data permits the reviewed creation."""
    first = m.compile(m.generate("001", [Required], backend="sqlite"))
    second = m.Package.load(
        m.compile(m.generate("002", [Indexed], backend="sqlite", previous=first)).dump()
    )
    with TemporaryDirectory() as directory:
        config = sqlite.Config(database=Path(directory) / "duplicates.db")
        async with m.connect(config) as target:
            await target.apply(await target.prepare(first))
        async with (
            await sqlite.Database.initialize(config) as db,
            db.transaction() as tx,
        ):
            await tx.execute(sqlite.raw("INSERT INTO entries VALUES(1,42),(2,42)"))
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
                [{"value": 42}, {"value": 42}],
            )
            assert_eq(
                await tx.fetch_all(
                    sqlite.raw(
                        "SELECT name FROM sqlite_schema WHERE type='index' AND tbl_name='entries'"
                    )
                ),
                [],
            )
            await tx.execute(sqlite.raw("DELETE FROM entries WHERE id=2"))
        async with m.connect(config) as target:
            await target.apply(plan)
        async with (
            await sqlite.Database.initialize(config) as db,
            db.transaction() as tx,
        ):
            assert_eq(
                await tx.fetch_all(sqlite.raw("SELECT value FROM entries")),
                [{"value": 42}],
            )
            assert_eq(
                await tx.fetch_all(
                    sqlite.raw(
                        "SELECT name FROM sqlite_schema WHERE type='index' AND tbl_name='entries'"
                    )
                ),
                [{"name": "by_value"}],
            )


@test(mark="slow")
async def lost_native_index_receipt_does_not_authorize_replay_or_adoption() -> None:
    """An existing correct new index is not proof of an acknowledged CREATE."""
    server = await load_fixture(provide_package_server())
    first = m.compile(m.generate("001", [NativeRequired], backend="mariadb"))
    second = m.Package.load(
        m.compile(
            m.generate("002", [NativeIndexed], backend="mariadb", previous=first)
        ).dump()
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
                recovery, reason="Index matches", schema_writers_excluded=True
            )
    async with (
        await mariadb.Database.initialize(server.config()) as db,
        db.transaction() as tx,
    ):
        assert_eq(
            await tx.fetch_all(mariadb.raw("SELECT value FROM entries")),
            [{"value": 42}],
        )
        indexes = await tx.fetch_all(
            mariadb.raw("SHOW INDEX FROM entries WHERE Key_name='by_value'")
        )
        assert_eq(len(indexes), 1)


@test(mark="slow")
async def acknowledged_native_index_is_not_recreated_after_later_data_failure() -> None:
    """Recovery resumes the failed UPDATE, not an already committed unique index."""
    server = await load_fixture(provide_package_server())
    first = m.compile(m.generate("001", [NativeRequired], backend="mariadb"))
    draft = m.generate("002", [NativeIndexed], backend="mariadb", previous=first).then(
        m.Checkpoint(name="indexed")
    )
    second = m.Package.load(
        m.compile(
            draft.then(
                m.DataChange.from_query(
                    mariadb.update(NativeIndexed).set(NativeIndexed.id.to(42)).all(),
                    checkpoint="indexed",
                    contract_digest=m.contract_digest(draft, point="indexed"),
                )
            )
        ).dump()
    )
    async with m.connect(server.config()) as target:
        await target.apply(await target.prepare(first, schema_writers_excluded=True))
    await server.run_sql("INSERT INTO entries VALUES(1,10),(2,20)")
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
            [{"id": 42, "value": 10}],
        )
        assert_eq(
            len(
                await tx.fetch_all(
                    mariadb.raw("SHOW INDEX FROM entries WHERE Key_name='by_value'")
                )
            ),
            1,
        )


class OptionalIndexed[S = sqlite.Pending](sqlite.Model[S]):
    """Index creation before a nullable rebuild in the same frozen route."""

    __tablename__ = "entries"
    __row_type__: ClassVar[sqlite.ReadType[OptionalIndexed[sqlite.Row]]]
    id: sqlite.Col[int] = sqlite.Integer(primary_key=True)
    value: sqlite.GenCol[int | None] = sqlite.Integer(
        nullable=True, default=sqlite.LiteralDefault(7)
    )
    __indexes__: ClassVar = [sqlite.Index(value, name="on", unique=True)]


@test(mark="medium")
async def sqlite_index_then_rebuild_preserves_unmanaged_objects_without_firing_trigger() -> (
    None
):
    """Projected index creation remains present through a later checked rebuild."""
    first = m.compile(m.generate("001", [Required], backend="sqlite"))
    draft = m.generate("002", [OptionalIndexed], backend="sqlite", previous=first)
    draft = draft.model_copy(update={"operations": tuple(reversed(draft.operations))})
    second = m.Package.load(m.compile(draft).dump())
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
                "INSERT INTO entries VALUES(1,42,X'ABCD')",
            ):
                await app.execute(sql)
            await app.commit()
        async with m.connect(config) as target:
            await target.apply(await target.prepare(second, preserve_unmanaged=True))
        async with (
            await sqlite.Database.initialize(config) as db,
            db.transaction() as tx,
        ):
            assert_eq(
                await tx.fetch_all(sqlite.raw("SELECT * FROM visible_entries")),
                [{"id": 1, "value": 42, "payload": bytes.fromhex("abcd")}],
            )
            assert_eq(
                await tx.fetch_all(sqlite.raw("SELECT * FROM audit")), [{"value": 42}]
            )
            assert_eq(
                await tx.fetch_all(
                    sqlite.raw(
                        "SELECT name FROM sqlite_schema WHERE type='index' AND tbl_name='entries' ORDER BY name"
                    )
                ),
                [{"name": "external_payload"}, {"name": "on"}],
            )
            await tx.execute(sqlite.raw("INSERT INTO entries(id,value) VALUES(2,NULL)"))
            assert_eq(
                await tx.fetch_all(
                    sqlite.raw("SELECT payload FROM visible_entries WHERE id=2")
                ),
                [{"payload": bytes.fromhex("00ff")}],
            )

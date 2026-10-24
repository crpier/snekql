"""Explicit index removals and replacements through frozen public routes."""

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
from tests.experimental.test_migration_indexes import (
    Indexed,
    NativeIndexed,
    NativeRequired,
    Required,
)
from tests.experimental.test_migration_nullability import Optional
from tests.experimental.test_migration_targets import provide_package_server


@test(mark="medium")
async def sqlite_unique_index_removal_requires_authority_and_preserves_values() -> None:
    """Removing uniqueness is explicit; retained rows/defaults survive and duplicates work."""
    first = m.compile(m.generate("001", [Indexed], backend="sqlite"))
    draft = m.generate("002", [Required], backend="sqlite", previous=first)
    with assert_raises(m.PackageError):
        m.compile(draft)
    second = m.Package.load(
        m.compile(
            draft.resolve(m.DropIndex(table_name="entries", index_name="by_value"))
        ).dump()
    )
    assert_eq(second.version, 6)
    with TemporaryDirectory() as directory:
        config = sqlite.Config(database=Path(directory) / "drop.db")
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
            await tx.execute(sqlite.raw("INSERT INTO entries VALUES(2,42)"))
            await tx.execute(sqlite.raw("INSERT INTO entries(id) VALUES(3)"))
            assert_eq(
                await tx.fetch_all(sqlite.raw("SELECT value FROM entries ORDER BY id")),
                [{"value": 42}, {"value": 42}, {"value": 7}],
            )
            assert_eq(
                await tx.fetch_all(
                    sqlite.raw(
                        "SELECT name FROM sqlite_schema WHERE type='index' AND tbl_name='entries'"
                    )
                ),
                [],
            )


@test(mark="medium")
async def sqlite_removed_index_is_not_resurrected_by_a_later_rebuild() -> None:
    """A nullable rebuild must project preceding index deletion, not recreate it."""
    first = m.compile(m.generate("001", [Indexed], backend="sqlite"))
    draft = m.generate("002", [Optional], backend="sqlite", previous=first)
    second = m.Package.load(
        m.compile(
            draft.resolve(m.DropIndex(table_name="entries", index_name="by_value"))
        ).dump()
    )
    with TemporaryDirectory() as directory:
        config = sqlite.Config(database=Path(directory) / "rebuild.db")
        async with m.connect(config) as target:
            await target.apply(await target.prepare(first))
        async with (
            await sqlite.Database.initialize(config) as db,
            db.transaction() as tx,
        ):
            await tx.execute(sqlite.raw("INSERT INTO entries VALUES(1,42)"))
        async with m.connect(config) as target:
            await target.apply(await target.prepare(second))
        async with (
            await sqlite.Database.initialize(config) as db,
            db.transaction() as tx,
        ):
            assert_eq(
                await tx.fetch_all(
                    sqlite.raw(
                        "SELECT name FROM sqlite_schema WHERE type='index' AND tbl_name='entries'"
                    )
                ),
                [],
            )
            await tx.execute(sqlite.raw("INSERT INTO entries VALUES(2,42),(3,NULL)"))
            assert_eq(
                await tx.fetch_all(sqlite.raw("SELECT value FROM entries ORDER BY id")),
                [{"value": 42}, {"value": 42}, {"value": None}],
            )


@test(mark="medium")
async def sqlite_removal_refuses_an_unmanaged_foreign_key_dependency_before_effects() -> (
    None
):
    """A parent unique index cannot disappear underneath an unowned child contract."""
    first = m.compile(m.generate("001", [Indexed], backend="sqlite"))
    second = m.compile(
        m.generate("002", [Required], backend="sqlite", previous=first).resolve(
            m.DropIndex(table_name="entries", index_name="by_value")
        )
    )
    with TemporaryDirectory() as directory:
        config = sqlite.Config(database=Path(directory) / "foreign-key.db")
        async with m.connect(config) as target:
            await target.apply(await target.prepare(first))
        async with aiosqlite.connect(str(config.database)) as app:
            await app.execute(
                "CREATE TABLE children(value INTEGER REFERENCES 'entries'(value))"
            )
            await app.execute("INSERT INTO entries VALUES(1,42)")
            await app.execute("INSERT INTO children VALUES(42)")
            await app.commit()
        async with m.connect(config) as target:
            with assert_raises(m.PackageError) as error:
                await target.prepare(second, preserve_unmanaged=True)
            assert "index removal" in str(error.exception)
            assert_eq(len(await target.status()), 1)
        async with (
            await sqlite.Database.initialize(config) as db,
            db.transaction() as tx,
        ):
            assert_eq(
                await tx.fetch_all(
                    sqlite.raw(
                        "SELECT name FROM sqlite_schema WHERE type='index' AND tbl_name='entries'"
                    )
                ),
                [{"name": "by_value"}],
            )
            assert_eq(
                await tx.fetch_all(sqlite.raw("SELECT value FROM children")),
                [{"value": 42}],
            )


@test(mark="medium")
async def sqlite_removal_refuses_an_index_hint_in_an_unmanaged_view() -> None:
    """An otherwise valid DROP must not leave an existing view unusable."""
    first = m.compile(m.generate("001", [Indexed], backend="sqlite"))
    second = m.compile(
        m.generate("002", [Required], backend="sqlite", previous=first).resolve(
            m.DropIndex(table_name="entries", index_name="by_value")
        )
    )
    with TemporaryDirectory() as directory:
        config = sqlite.Config(database=Path(directory) / "view.db")
        async with m.connect(config) as target:
            await target.apply(await target.prepare(first))
        async with aiosqlite.connect(str(config.database)) as app:
            await app.execute(
                "CREATE VIEW indexed_entries AS SELECT value FROM entries INDEXED BY by_value"
            )
            await app.commit()
        async with m.connect(config) as target:
            with assert_raises(m.PackageError) as error:
                await target.prepare(second, preserve_unmanaged=True)
            assert "index removal" in str(error.exception)
            assert_eq(len(await target.status()), 1)


@test(mark="slow")
async def native_drop_requires_foreign_key_checks_and_no_opaque_program_dependencies() -> (
    None
):
    """Weak FK enforcement or opaque routines cannot authorize index removal."""
    server = await load_fixture(provide_package_server())
    first = m.compile(m.generate("001", [NativeIndexed], backend="mariadb"))
    second = m.compile(
        m.generate("002", [NativeRequired], backend="mariadb", previous=first).resolve(
            m.DropIndex(table_name="entries", index_name="by_value")
        )
    )
    async with m.connect(server.config()) as target:
        await target.apply(await target.prepare(first, schema_writers_excluded=True))
    await server.run_sql("SET GLOBAL foreign_key_checks=0")
    try:
        async with m.connect(server.config()) as target:
            with assert_raises(m.PackageError) as error:
                await target.prepare(second, schema_writers_excluded=True)
            assert "index removal" in str(error.exception)
            assert_eq(len(await target.status()), 1)
    finally:
        await server.run_sql("SET GLOBAL foreign_key_checks=1")
    await server.run_sql(
        "CREATE PROCEDURE hidden_dependency() SELECT value FROM entries FORCE INDEX(by_value)"
    )
    try:
        async with m.connect(server.config()) as target:
            with assert_raises(m.PackageError) as error:
                await target.prepare(second, schema_writers_excluded=True)
            assert "index removal" in str(error.exception)
            assert_eq(len(await target.status()), 1)
    finally:
        await server.run_sql("DROP PROCEDURE hidden_dependency")


class NonUnique[S = sqlite.Pending](sqlite.Model[S]):
    """A same-name replacement that no longer imposes uniqueness."""

    __tablename__ = "entries"
    __row_type__: ClassVar[sqlite.ReadType[NonUnique[sqlite.Row]]]
    id: sqlite.Col[int] = sqlite.Integer(primary_key=True)
    value: sqlite.GenCol[int] = sqlite.Integer(default=sqlite.LiteralDefault(7))
    __indexes__: ClassVar = [sqlite.Index(value, name="by_value")]


class NativeNonUnique[S = mariadb.Pending](mariadb.Model[S]):
    """A native nonunique predecessor for tightening via replacement."""

    __tablename__ = "entries"
    __row_type__: ClassVar[mariadb.ReadType[NativeNonUnique[mariadb.Row]]]
    id: mariadb.Col[int] = mariadb.Integer(primary_key=True)
    value: mariadb.GenCol[int] = mariadb.Integer(default=mariadb.LiteralDefault(7))
    __indexes__: ClassVar = [mariadb.Index(value, name="by_value")]


@test(mark="medium")
async def sqlite_replacement_failure_restores_old_index_and_can_retry() -> None:
    """DROP plus CREATE is atomic; a failed unique build restores the nonunique index."""
    first = m.compile(m.generate("001", [NonUnique], backend="sqlite"))
    draft = m.generate("002", [Indexed], backend="sqlite", previous=first)
    with assert_raises(m.PackageError):
        m.compile(draft)
    second = m.Package.load(
        m.compile(
            draft.resolve(m.DropIndex(table_name="entries", index_name="by_value"))
        ).dump()
    )
    with TemporaryDirectory() as directory:
        config = sqlite.Config(database=Path(directory) / "replacement.db")
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
                await tx.fetch_all(
                    sqlite.raw("SELECT sql FROM sqlite_schema WHERE name='by_value'")
                ),
                [{"sql": 'CREATE INDEX "by_value" ON "entries" ("value")'}],
            )
            assert_eq(
                await tx.fetch_all(sqlite.raw("SELECT value FROM entries ORDER BY id")),
                [{"value": 42}, {"value": 42}],
            )
            await tx.execute(sqlite.raw("DELETE FROM entries WHERE id=2"))
        async with m.connect(config) as target:
            await target.apply(plan)
        async with (
            await sqlite.Database.initialize(config) as db,
            db.transaction() as tx,
        ):
            assert_eq(
                await tx.fetch_all(
                    sqlite.raw("SELECT sql FROM sqlite_schema WHERE name='by_value'")
                ),
                [{"sql": 'CREATE UNIQUE INDEX "by_value" ON "entries" ("value")'}],
            )


@test(mark="slow")
async def native_replacement_keeps_acknowledged_drop_when_new_unique_index_fails() -> (
    None
):
    """Native replacement has a real gap; corrected retry executes CREATE, not DROP."""
    server = await load_fixture(provide_package_server())
    first = m.compile(m.generate("001", [NativeNonUnique], backend="mariadb"))
    second = m.Package.load(
        m.compile(
            m.generate(
                "002", [NativeIndexed], backend="mariadb", previous=first
            ).resolve(m.DropIndex(table_name="entries", index_name="by_value"))
        ).dump()
    )
    async with m.connect(server.config()) as target:
        await target.apply(await target.prepare(first, schema_writers_excluded=True))
    await server.run_sql("INSERT INTO entries VALUES(1,42),(2,42)")
    async with m.connect(server.config()) as target:
        plan = await target.prepare(second, schema_writers_excluded=True)
        with assert_raises(NativeIntegrityError):
            await target.apply(plan)
        recovery = await target.inspect_recovery(plan, schema_writers_excluded=True)
        assert_eq(recovery.disposition, "retry_remaining")
        assert_eq(recovery.acknowledged_steps, 1)
    async with (
        await mariadb.Database.initialize(server.config()) as db,
        db.transaction() as tx,
    ):
        assert_eq(
            await tx.fetch_all(
                mariadb.raw("SHOW INDEX FROM entries WHERE Key_name='by_value'")
            ),
            [],
        )
        assert_eq(
            await tx.fetch_all(mariadb.raw("SELECT value FROM entries ORDER BY id")),
            [{"value": 42}, {"value": 42}],
        )
        await tx.execute(mariadb.raw("DELETE FROM entries WHERE id=2"))
    async with m.connect(server.config()) as target:
        recovery = await target.inspect_recovery(plan, schema_writers_excluded=True)
        await target.resume(recovery, schema_writers_excluded=True)
    async with (
        await mariadb.Database.initialize(server.config()) as db,
        db.transaction() as tx,
    ):
        indexes = await tx.fetch_all(
            mariadb.raw("SHOW INDEX FROM entries WHERE Key_name='by_value'")
        )
        assert_eq(len(indexes), 1)
        assert_eq(indexes[0]["Non_unique"], 0)
        assert_eq(
            await tx.fetch_all(mariadb.raw("SELECT value FROM entries")),
            [{"value": 42}],
        )


@test(mark="slow")
async def native_drop_proves_absence_and_lost_receipt_is_not_structurally_accepted() -> (
    None
):
    """Even correct disappearance is insufficient to reconstruct a lost acknowledgement."""
    server = await load_fixture(provide_package_server())
    first = m.compile(m.generate("001", [NativeIndexed], backend="mariadb"))
    second = m.compile(
        m.generate("002", [NativeRequired], backend="mariadb", previous=first).resolve(
            m.DropIndex(table_name="entries", index_name="by_value")
        )
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
                recovery, reason="Index is absent", schema_writers_excluded=True
            )
    async with (
        await mariadb.Database.initialize(server.config()) as db,
        db.transaction() as tx,
    ):
        assert_eq(
            await tx.fetch_all(
                mariadb.raw("SHOW INDEX FROM entries WHERE Key_name='by_value'")
            ),
            [],
        )
        assert_eq(
            await tx.fetch_all(mariadb.raw("SELECT value FROM entries")),
            [{"value": 42}],
        )


@test(mark="fast")
def index_removal_requires_a_managed_name_and_format_six() -> None:
    """Destructive authority is exact; an old reader vocabulary cannot carry DROP."""
    first = m.compile(m.generate("001", [Indexed], backend="sqlite"))
    draft = m.generate("002", [Required], backend="sqlite", previous=first)
    for name in ("missing", "BY_VALUE"):
        with assert_raises(m.PackageError):
            draft.resolve(m.DropIndex(table_name="entries", index_name=name))
    package = m.compile(
        draft.resolve(m.DropIndex(table_name="entries", index_name="by_value"))
    )
    for version in (2, 3, 4, 5):
        data = json.loads(package.dump())
        data["version"] = version
        with assert_raises(m.PackageError) as error:
            m.Package.load(json.dumps(data))
        assert "require execution package version 6" in str(error.exception)
    unchanged = m.generate("002", [Indexed], backend="sqlite", previous=first)
    with assert_raises(m.PackageError) as error:
        m.compile(
            unchanged.then(m.DropIndex(table_name="entries", index_name="unmanaged"))
        )
    assert "explicitly managed" in str(error.exception)


class NativeUntouched[S = mariadb.Pending](mariadb.Model[S]):
    """An unrelated existing prefix index retains its own verifier grammar."""

    __tablename__ = "untouched"
    __row_type__: ClassVar[mariadb.ReadType[NativeUntouched[mariadb.Row]]]
    id: mariadb.Col[int] = mariadb.Integer(primary_key=True)
    title: mariadb.Col[str] = mariadb.Text(length=255)
    __indexes__: ClassVar = [mariadb.Index(title, name="by_title", prefix_lengths=(8,))]


@test(mark="slow")
async def native_removal_completes_with_absence_and_duplicate_writes() -> None:
    """A normally acknowledged unique-index removal preserves rows and future defaults."""
    server = await load_fixture(provide_package_server())
    first = m.compile(
        m.generate("001", [NativeIndexed, NativeUntouched], backend="mariadb")
    )
    second = m.Package.load(
        m.compile(
            m.generate(
                "002",
                [NativeRequired, NativeUntouched],
                backend="mariadb",
                previous=first,
            ).resolve(m.DropIndex(table_name="entries", index_name="by_value"))
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
        await tx.execute(mariadb.raw("INSERT INTO entries VALUES(2,42)"))
        await tx.execute(mariadb.raw("INSERT INTO entries(id) VALUES(3)"))
        assert_eq(
            await tx.fetch_all(mariadb.raw("SELECT value FROM entries ORDER BY id")),
            [{"value": 42}, {"value": 42}, {"value": 7}],
        )
        assert_eq(
            await tx.fetch_all(
                mariadb.raw("SHOW INDEX FROM entries WHERE Key_name='by_value'")
            ),
            [],
        )


@test(mark="medium")
async def relinquishing_a_new_child_cannot_hide_an_intermediate_index_dependency() -> (
    None
):
    """Ownership release does not erase physical FK dependencies created by the route."""
    first = m.compile(m.generate("001", [Indexed], backend="sqlite"))
    draft = m.generate("002", [Required], backend="sqlite", previous=first).resolve(
        m.DropIndex(table_name="entries", index_name="by_value")
    )
    child = m.TableState(
        name="children",
        quoted_name='"children"',
        sql='CREATE TABLE "children" ("value" INTEGER REFERENCES "entries"("value"))',
        columns=(
            m.ColumnState(
                name="value",
                definition='"value" INTEGER REFERENCES "entries"("value")',
                nullable=True,
                query_type="int | None",
                storage="INTEGER",
            ),
        ),
    )
    second = m.compile(
        draft.model_copy(
            update={
                "operations": (
                    m.CreateTable(table=child),
                    m.RelinquishTable(table_name="children"),
                    *draft.operations,
                )
            }
        )
    )
    with TemporaryDirectory() as directory:
        config = sqlite.Config(database=Path(directory) / "intermediate.db")
        async with m.connect(config) as target:
            await target.apply(await target.prepare(first))
            with assert_raises(m.PackageError) as error:
                await target.prepare(second)
            assert "index removal" in str(error.exception)
            assert_eq(len(await target.status()), 1)
        async with (
            await sqlite.Database.initialize(config) as db,
            db.transaction() as tx,
        ):
            assert_eq(
                await tx.fetch_all(
                    sqlite.raw("SELECT name FROM sqlite_schema WHERE name='children'")
                ),
                [],
            )

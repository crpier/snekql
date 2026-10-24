"""Required-to-nullable changes through frozen public migration routes."""

import json
from pathlib import Path
from sqlite3 import IntegrityError
from tempfile import TemporaryDirectory
from typing import ClassVar

from pymysql.err import OperationalError
from snektest import assert_eq, assert_raises, load_fixture, test

from snekql import mariadb, sqlite
from snekql.experimental import migrations as m
from tests.experimental.test_migration_targets import provide_package_server


class Required[S = sqlite.Pending](sqlite.Model[S]):
    """Existing non-null values and future-insert default."""

    __tablename__ = "entries"
    __row_type__: ClassVar[sqlite.ReadType[Required[sqlite.Row]]]
    id: sqlite.Col[int] = sqlite.Integer(primary_key=True)
    value: sqlite.GenCol[int] = sqlite.Integer(default=sqlite.LiteralDefault(7))


class Optional[S = sqlite.Pending](sqlite.Model[S]):
    """Only the NOT NULL restriction changes."""

    __tablename__ = "entries"
    __row_type__: ClassVar[sqlite.ReadType[Optional[sqlite.Row]]]
    id: sqlite.Col[int] = sqlite.Integer(primary_key=True)
    value: sqlite.GenCol[int | None] = sqlite.Integer(
        nullable=True, default=sqlite.LiteralDefault(7)
    )


@test(mark="medium")
async def sqlite_relaxation_preserves_values_and_default_and_allows_null() -> None:
    """A frozen transition changes nullability without rewriting values or defaults."""
    first = m.compile(m.generate("001", [Required], backend="sqlite"))
    second = m.Package.load(
        m.compile(
            m.generate("002", [Optional], backend="sqlite", previous=first)
        ).dump()
    )
    assert_eq(second.version, 4)
    with TemporaryDirectory() as directory:
        config = sqlite.Config(database=Path(directory) / "relax.db")
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
            await tx.execute(sqlite.raw("INSERT INTO entries VALUES(2,NULL)"))
            await tx.execute(sqlite.raw("INSERT INTO entries(id) VALUES(3)"))
            assert_eq(
                await tx.fetch_all(sqlite.raw("SELECT value FROM entries ORDER BY id")),
                [{"value": 42}, {"value": None}, {"value": 7}],
            )


class NativeRequired[S = mariadb.Pending](mariadb.Model[S]):
    """Native required value with an insertion default."""

    __tablename__ = "entries"
    __row_type__: ClassVar[mariadb.ReadType[NativeRequired[mariadb.Row]]]
    id: mariadb.Col[int] = mariadb.Integer(primary_key=True)
    value: mariadb.GenCol[int] = mariadb.Integer(default=mariadb.LiteralDefault(7))


class NativeOptional[S = mariadb.Pending](mariadb.Model[S]):
    """Native nullable value retaining the same default."""

    __tablename__ = "entries"
    __row_type__: ClassVar[mariadb.ReadType[NativeOptional[mariadb.Row]]]
    id: mariadb.Col[int] = mariadb.Integer(primary_key=True)
    value: mariadb.GenCol[int | None] = mariadb.Integer(
        nullable=True, default=mariadb.LiteralDefault(7)
    )


@test(mark="slow")
async def native_relaxation_preserves_values_and_default_and_allows_null() -> None:
    """Native MODIFY permits NULL without discarding the existing default or rows."""
    server = await load_fixture(provide_package_server())
    first = m.compile(m.generate("001", [NativeRequired], backend="mariadb"))
    second = m.Package.load(
        m.compile(
            m.generate("002", [NativeOptional], backend="mariadb", previous=first)
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
        await tx.execute(mariadb.raw("INSERT INTO entries VALUES(2,NULL)"))
        await tx.execute(mariadb.raw("INSERT INTO entries(id) VALUES(3)"))
        assert_eq(
            await tx.fetch_all(mariadb.raw("SELECT value FROM entries ORDER BY id")),
            [{"value": 42}, {"value": None}, {"value": 7}],
        )


@test(mark="fast")
def opposing_nullability_transitions_require_a_checkpoint() -> None:
    """A single grouped rebuild must not invert the intended final constraint."""
    first = m.compile(m.generate("001", [Required], backend="sqlite"))
    draft = m.generate("002", [Required], backend="sqlite", previous=first)
    with assert_raises(m.PackageError):
        m.compile(
            draft.then(
                m.AllowNull(table_name="entries", column_name="value"),
                m.RequireNotNull(table_name="entries", column_name="value"),
            )
        )


@test(mark="fast")
def explicit_drop_after_relaxation_does_not_modify_a_removed_column() -> None:
    """Explicit deletion takes precedence over the earlier nullable alteration."""
    first = m.compile(m.generate("001", [NativeRequired], backend="mariadb"))
    table = first.target.tables[0]
    id_column = table.columns[0]
    target = table.model_copy(
        update={
            "columns": (id_column,),
            "sql": table.sql.replace(", " + table.columns[1].definition, ""),
        }
    )
    draft = m.Draft(
        revision="002",
        predecessor=first.digest,
        before=first.target,
        target=first.target.model_copy(update={"tables": (target,)}),
        operations=(
            m.AllowNull(table_name="entries", column_name="value"),
            m.DropColumn(table_name="entries", column_name="value"),
        ),
    )
    package = m.compile(draft)
    assert_eq(package.statements, ("ALTER TABLE `entries` DROP COLUMN `value`",))
    assert_eq(m.Package.load(package.dump()), package)


@test(mark="fast")
def relaxation_refuses_lexer_comments_in_column_sources() -> None:
    """A retained trailing comment must not swallow later native MODIFY clauses."""
    table = m.generate("001", [NativeRequired], backend="mariadb").target.tables[0]
    old = table.columns[1]
    source = old.model_copy(update={"definition": old.definition + " -- reviewed\n"})
    before = table.model_copy(
        update={
            "columns": (table.columns[0], source),
            "sql": table.sql.replace(old.definition, source.definition),
        }
    )
    relaxed = source.model_copy(
        update={
            "definition": source.definition.replace(" NOT NULL", "").rstrip(),
            "nullable": True,
            "query_type": "int | None",
        }
    )
    after = before.model_copy(
        update={
            "columns": (table.columns[0], relaxed),
            "sql": before.sql.replace(source.definition, relaxed.definition),
        }
    )
    draft = m.Draft(
        revision="002",
        predecessor="reviewed",
        before=m.State(backend="mariadb", tables=(before,)),
        target=m.State(backend="mariadb", tables=(after,)),
        operations=(m.AllowNull(table_name="entries", column_name="value"),),
    )
    with assert_raises(m.PackageError) as error:
        m.compile(draft)
    assert "comments" in str(error.exception)


class OptionalEight[S = sqlite.Pending](sqlite.Model[S]):
    """Simultaneous relaxation and default change."""

    __tablename__ = "entries"
    __row_type__: ClassVar[sqlite.ReadType[OptionalEight[sqlite.Row]]]
    id: sqlite.Col[int] = sqlite.Integer(primary_key=True)
    value: sqlite.GenCol[int | None] = sqlite.Integer(
        nullable=True, default=sqlite.LiteralDefault(8)
    )


@test(mark="fast")
def old_formats_cannot_carry_relaxation_operations_or_even_empty_metadata() -> None:
    """Vocabulary selection remains explicit and old artifact shapes stay closed."""
    first = m.compile(m.generate("001", [Optional], backend="sqlite"))
    for model, version in ((Required, 2), (OptionalEight, 3)):
        package = m.compile(
            m.generate("002", [model], backend="sqlite", previous=first)
        )
        assert_eq(package.version, version)
        data = json.loads(package.dump())
        data["contractions"][0]["relaxed"] = []
        with assert_raises(m.PackageError) as error:
            m.Package.load(json.dumps(data))
        assert "require execution package version 4" in str(error.exception)
    required = m.compile(m.generate("001", [Required], backend="sqlite"))
    relaxed = m.compile(
        m.generate("002", [Optional], backend="sqlite", previous=required)
    )
    for version in (2, 3):
        data = json.loads(relaxed.dump())
        data["version"] = version
        with assert_raises(m.PackageError) as error:
            m.Package.load(json.dumps(data))
        assert "require execution package version 4" in str(error.exception)


@test(mark="fast")
def relaxation_cannot_change_storage_or_query_type() -> None:
    """A nullability operation cannot carry unrelated recorded facts."""
    first = m.compile(m.generate("001", [Required], backend="sqlite"))
    draft = m.generate("002", [Optional], backend="sqlite", previous=first)
    table = draft.target.tables[0]
    for changes in ({"storage": "TEXT"}, {"query_type": "str | None"}):
        column = table.columns[1].model_copy(update=changes)
        changed = table.model_copy(update={"columns": (table.columns[0], column)})
        with assert_raises(m.PackageError):
            m.compile(
                draft.model_copy(
                    update={
                        "target": draft.target.model_copy(update={"tables": (changed,)})
                    }
                )
            )


class NativeExtra[S = mariadb.Pending](mariadb.Model[S]):
    """Dropping another column must not mask an unproven relaxation."""

    __tablename__ = "entries"
    __row_type__: ClassVar[mariadb.ReadType[NativeExtra[mariadb.Row]]]
    id: mariadb.Col[int] = mariadb.Integer(primary_key=True)
    value: mariadb.GenCol[int] = mariadb.Integer(default=mariadb.LiteralDefault(7))
    extra: mariadb.Col[str | None] = mariadb.Text(nullable=True)


@test(mark="slow")
async def lost_relaxation_receipt_cannot_reconcile_only_a_column_drop() -> None:
    """The require/drop projection must not certify a nullable fact it ignores."""
    server = await load_fixture(provide_package_server())
    first = m.compile(m.generate("001", [NativeExtra], backend="mariadb"))
    second = m.compile(
        m.generate("002", [NativeOptional], backend="mariadb", previous=first).resolve(
            m.DropColumn(table_name="entries", column_name="extra")
        )
    )
    async with m.connect(server.config()) as target:
        await target.apply(await target.prepare(first, schema_writers_excluded=True))
    await server.run_sql(
        "CREATE TRIGGER fail_receipt BEFORE UPDATE ON snekql_experimental_migrations FOR EACH ROW SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='receipt unavailable'"
    )
    async with m.connect(server.config()) as target:
        plan = await target.prepare(second, schema_writers_excluded=True)
        with assert_raises(OperationalError):
            await target.apply(plan)
    await server.run_sql("DROP TRIGGER fail_receipt")
    await server.run_sql(
        "ALTER TABLE entries MODIFY COLUMN value BIGINT NOT NULL DEFAULT 7"
    )
    async with m.connect(server.config()) as target:
        recovery = await target.inspect_recovery(plan, schema_writers_excluded=True)
        assert_eq(recovery.disposition, "ambiguous")
        assert_eq(recovery.acknowledged_steps, 0)
        with assert_raises(m.PackageError):
            await target.reconcile(
                recovery, reason="Only drop matches", schema_writers_excluded=True
            )
        with assert_raises(m.PackageError):
            await target.resume(recovery, schema_writers_excluded=True)
    await server.run_sql("ALTER TABLE entries MODIFY COLUMN value BIGINT DEFAULT 7")
    async with m.connect(server.config()) as target:
        recovery = await target.inspect_recovery(plan, schema_writers_excluded=True)
        assert_eq(recovery.disposition, "ambiguous")


@test(mark="fast")
def relaxation_refuses_coupled_inline_constraints() -> None:
    """MODIFY must not recreate or duplicate inline constraints while relaxing NULL."""
    base = m.generate("001", [NativeRequired], backend="mariadb").target.tables[0]
    old = base.columns[1]
    for clause in (" UNIQUE", " CHECK(value >= 0)"):
        column = old.model_copy(update={"definition": old.definition + clause})
        before = base.model_copy(
            update={
                "columns": (base.columns[0], column),
                "sql": base.sql.replace(old.definition, column.definition),
            }
        )
        relaxed = column.model_copy(
            update={
                "definition": column.definition.replace(" NOT NULL", ""),
                "nullable": True,
                "query_type": "int | None",
            }
        )
        after = before.model_copy(
            update={
                "columns": (base.columns[0], relaxed),
                "sql": before.sql.replace(column.definition, relaxed.definition),
            }
        )
        with assert_raises(m.PackageError):
            m.compile(
                m.Draft(
                    revision="002",
                    predecessor="reviewed",
                    before=m.State(backend="mariadb", tables=(before,)),
                    target=m.State(backend="mariadb", tables=(after,)),
                    operations=(
                        m.AllowNull(table_name="entries", column_name="value"),
                    ),
                )
            )


@test(mark="medium")
async def sqlite_relaxation_and_default_change_roll_back_with_later_data_failure() -> (
    None
):
    """Rebuild rollback retains the old constraint/default; corrected retry preserves rows."""
    first = m.compile(m.generate("001", [Required], backend="sqlite"))
    draft = m.generate("002", [OptionalEight], backend="sqlite", previous=first).then(
        m.Checkpoint(name="relaxed")
    )
    second = m.Package.load(
        m.compile(
            draft.then(
                m.DataChange.from_query(
                    sqlite.update(OptionalEight).set(OptionalEight.id.to(42)).all(),
                    checkpoint="relaxed",
                    contract_digest=m.contract_digest(draft, point="relaxed"),
                )
            )
        ).dump()
    )
    with TemporaryDirectory() as directory:
        config = sqlite.Config(database=Path(directory) / "rollback.db")
        async with m.connect(config) as target:
            await target.apply(await target.prepare(first))
        async with (
            await sqlite.Database.initialize(config) as db,
            db.transaction() as tx,
        ):
            await tx.execute(sqlite.raw("INSERT INTO entries VALUES(1,7),(2,42)"))
        async with m.connect(config) as target:
            plan = await target.prepare(second)
            with assert_raises(IntegrityError):
                await target.apply(plan)
            assert_eq(len(await target.status()), 1)
        async with (
            await sqlite.Database.initialize(config) as db,
            db.transaction() as tx,
        ):
            column = (await tx.fetch_all(sqlite.raw("PRAGMA table_info(entries)")))[1]
            assert_eq(column["notnull"], 1)
            assert_eq(column["dflt_value"], "7")
            assert_eq(
                await tx.fetch_all(sqlite.raw("SELECT value FROM entries ORDER BY id")),
                [{"value": 7}, {"value": 42}],
            )
            await tx.execute(sqlite.raw("DELETE FROM entries WHERE id=2"))
        async with m.connect(config) as target:
            await target.apply(plan)
        async with (
            await sqlite.Database.initialize(config) as db,
            db.transaction() as tx,
        ):
            await tx.execute(sqlite.raw("INSERT INTO entries VALUES(3,NULL)"))
            await tx.execute(sqlite.raw("INSERT INTO entries(id) VALUES(4)"))
            assert_eq(
                await tx.fetch_all(
                    sqlite.raw("SELECT id,value FROM entries ORDER BY id")
                ),
                [
                    {"id": 3, "value": None},
                    {"id": 4, "value": 8},
                    {"id": 42, "value": 7},
                ],
            )


class NativeOptionalNoDefault[S = mariadb.Pending](mariadb.Model[S]):
    """Nullable omission after removing the former required default."""

    __tablename__ = "entries"
    __row_type__: ClassVar[mariadb.ReadType[NativeOptionalNoDefault[mariadb.Row]]]
    id: mariadb.Col[int] = mariadb.Integer(primary_key=True)
    value: mariadb.Col[int | None] = mariadb.Integer(nullable=True)


@test(mark="slow")
async def native_relaxation_can_remove_default_without_changing_existing_values() -> (
    None
):
    """The final MODIFY includes both changes, retaining scalar rows and allowing omission."""
    server = await load_fixture(provide_package_server())
    first = m.compile(m.generate("001", [NativeRequired], backend="mariadb"))
    second = m.Package.load(
        m.compile(
            m.generate(
                "002", [NativeOptionalNoDefault], backend="mariadb", previous=first
            )
        ).dump()
    )
    async with m.connect(server.config()) as target:
        await target.apply(await target.prepare(first, schema_writers_excluded=True))
    await server.run_sql("INSERT INTO entries VALUES(1,42)")
    async with m.connect(server.config()) as target:
        await target.apply(await target.prepare(second, schema_writers_excluded=True))
    async with (
        await mariadb.Database.initialize(server.config()) as db,
        db.transaction() as tx,
    ):
        await tx.execute(mariadb.raw("INSERT INTO entries VALUES(2,NULL)"))
        await tx.execute(mariadb.raw("INSERT INTO entries(id) VALUES(3)"))
        assert_eq(
            await tx.fetch_all(mariadb.raw("SELECT value FROM entries ORDER BY id")),
            [{"value": 42}, {"value": None}, {"value": None}],
        )

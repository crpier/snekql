"""Default alteration through frozen authoring and SQLite deployment seams."""

import asyncio
import json
import sys
from pathlib import Path
from sqlite3 import IntegrityError
from tempfile import TemporaryDirectory
from typing import ClassVar

import aiosqlite
from snektest import assert_eq, assert_raises, test

from snekql import mariadb, sqlite
from snekql.errors import ExecutionError
from snekql.experimental import migrations as m


class Original[S = sqlite.Pending](sqlite.Model[S]):
    """Initial insertion default."""

    __tablename__ = "settings"
    __row_type__: ClassVar[sqlite.ReadType[Original[sqlite.Row]]]
    id: sqlite.Col[int] = sqlite.Integer(primary_key=True)
    value: sqlite.GenCol[int] = sqlite.Integer(default=sqlite.LiteralDefault(7))


class Changed[S = sqlite.Pending](sqlite.Model[S]):
    """Only future omitted values change."""

    __tablename__ = "settings"
    __row_type__: ClassVar[sqlite.ReadType[Changed[sqlite.Row]]]
    id: sqlite.Col[int] = sqlite.Integer(primary_key=True)
    value: sqlite.GenCol[int] = sqlite.Integer(default=sqlite.LiteralDefault(8))


@test(mark="medium")
async def default_change_preserves_existing_values_and_changes_future_inserts() -> None:
    """Frozen default alteration is not a backfill or an implicit data rewrite."""
    first = m.compile(m.generate("001", [Original], backend="sqlite"))
    draft = m.generate("002", [Changed], backend="sqlite", previous=first)
    assert_eq(draft.unresolved, ())
    second = m.Package.load(m.compile(draft).dump())
    assert_eq(first.version, 2)
    assert_eq(second.version, 3)
    with TemporaryDirectory() as directory:
        config = sqlite.Config(database=Path(directory) / "defaults.db")
        async with m.connect(config) as target:
            await target.apply(await target.prepare(first))
        async with (
            await sqlite.Database.initialize(config) as database,
            database.transaction() as transaction,
        ):
            await transaction.execute(sqlite.raw("INSERT INTO settings(id) VALUES(1)"))
        async with m.connect(config) as target:
            assert_eq(await target.apply(await target.prepare(second)), "applied")
            assert_eq(
                await target.apply(await target.prepare(second)), "already_applied"
            )
        async with (
            await sqlite.Database.initialize(config) as database,
            database.transaction() as transaction,
        ):
            await transaction.execute(sqlite.raw("INSERT INTO settings(id) VALUES(2)"))
            assert_eq(
                await transaction.fetch_all(
                    sqlite.raw("SELECT value FROM settings ORDER BY id")
                ),
                [{"value": 7}, {"value": 8}],
            )


class Required[S = sqlite.Pending](sqlite.Model[S]):
    """Removing the default requires future writers to supply a value."""

    __tablename__ = "settings"
    __row_type__: ClassVar[sqlite.ReadType[Required[sqlite.Row]]]
    id: sqlite.Col[int] = sqlite.Integer(primary_key=True)
    value: sqlite.Col[int] = sqlite.Integer()


@test(mark="medium")
async def removing_and_setting_a_default_is_not_data_backfill() -> None:
    """Removed required defaults reject omission; later setting a default is explicit."""
    first = m.compile(m.generate("001", [Original], backend="sqlite"))
    removed = m.Package.load(
        m.compile(
            m.generate("002", [Required], backend="sqlite", previous=first)
        ).dump()
    )
    restored = m.Package.load(
        m.compile(
            m.generate("003", [Changed], backend="sqlite", previous=removed)
        ).dump()
    )
    with TemporaryDirectory() as directory:
        config = sqlite.Config(database=Path(directory) / "defaults.db")
        async with m.connect(config) as target:
            await target.apply(await target.prepare(first))
        async with (
            await sqlite.Database.initialize(config) as database,
            database.transaction() as transaction,
        ):
            await transaction.execute(sqlite.raw("INSERT INTO settings(id) VALUES(1)"))
        async with m.connect(config) as target:
            await target.apply(await target.prepare(removed))
        async with await sqlite.Database.initialize(config) as database:
            with assert_raises(sqlite.ExecutionError):
                async with database.transaction() as transaction:
                    await transaction.execute(
                        sqlite.raw("INSERT INTO settings(id) VALUES(2)")
                    )
        async with m.connect(config) as target:
            await target.apply(await target.prepare(restored))
        async with (
            await sqlite.Database.initialize(config) as database,
            database.transaction() as transaction,
        ):
            await transaction.execute(sqlite.raw("INSERT INTO settings(id) VALUES(3)"))
            assert_eq(
                await transaction.fetch_all(
                    sqlite.raw("SELECT id, value FROM settings ORDER BY id")
                ),
                [{"id": 1, "value": 7}, {"id": 3, "value": 8}],
            )


@test(mark="medium")
async def failed_work_after_default_change_rolls_back_schema_data_and_receipt() -> None:
    """Retry follows atomic rollback, not uncertain native-DDL reconciliation."""
    first = m.compile(m.generate("001", [Original], backend="sqlite"))
    draft = m.generate("002", [Changed], backend="sqlite", previous=first).then(
        m.Checkpoint(name="changed")
    )
    assert "CONTRACT_DIGEST" in m.contract_source(
        draft, point="changed", table="settings"
    )
    package = m.Package.load(
        m.compile(
            draft.then(
                m.DataChange.from_query(
                    sqlite.update(Changed).set(Changed.id.to(42)).all(),
                    checkpoint="changed",
                    contract_digest=m.contract_digest(draft, point="changed"),
                )
            )
        ).dump()
    )
    with TemporaryDirectory() as directory:
        config = sqlite.Config(database=Path(directory) / "defaults.db")
        async with m.connect(config) as target:
            await target.apply(await target.prepare(first))
        async with (
            await sqlite.Database.initialize(config) as database,
            database.transaction() as transaction,
        ):
            await transaction.execute(
                sqlite.raw("INSERT INTO settings(id) VALUES(1),(2)")
            )
        async with m.connect(config) as target:
            plan = await target.prepare(package)
            with assert_raises(IntegrityError):
                await target.apply(plan)
            assert_eq([item.revision for item in await target.status()], ["001"])
        async with (
            await sqlite.Database.initialize(config) as database,
            database.transaction() as transaction,
        ):
            await transaction.execute(sqlite.raw("INSERT INTO settings(id) VALUES(3)"))
            assert_eq(
                await transaction.fetch_all(
                    sqlite.raw("SELECT id, value FROM settings ORDER BY id")
                ),
                [{"id": 1, "value": 7}, {"id": 2, "value": 7}, {"id": 3, "value": 7}],
            )
            await transaction.execute(sqlite.raw("DELETE FROM settings WHERE id <> 1"))
        async with m.connect(config) as target:
            assert_eq(await target.apply(plan), "applied")
        async with (
            await sqlite.Database.initialize(config) as database,
            database.transaction() as transaction,
        ):
            await transaction.execute(sqlite.raw("INSERT INTO settings(id) VALUES(43)"))
            assert_eq(
                await transaction.fetch_all(
                    sqlite.raw("SELECT id, value FROM settings ORDER BY id")
                ),
                [{"id": 42, "value": 7}, {"id": 43, "value": 8}],
            )


@test(mark="fast")
def default_operation_cannot_authorize_other_column_changes() -> None:
    """Changed constraints, storage, nullability and codec claims need their own routes."""
    first = m.compile(m.generate("001", [Original], backend="sqlite"))
    draft = m.generate("002", [Changed], backend="sqlite", previous=first)
    table = draft.target.tables[0]
    for update in (
        {"definition": table.columns[1].definition + " COLLATE NOCASE"},
        {"nullable": True},
        {"storage": "TEXT"},
        {"query_type": "str"},
    ):
        column = table.columns[1].model_copy(update=update)
        altered = table.model_copy(
            update={
                "columns": (table.columns[0], column),
                "sql": table.sql.replace(
                    table.columns[1].definition, column.definition
                ),
            }
        )
        invalid = draft.model_copy(
            update={
                "target": draft.target.model_copy(update={"tables": (altered,)}),
                "operations": (m.ChangeDefault(table_name=table.name, column=column),),
            }
        )
        with assert_raises(m.PackageError) as error:
            m.compile(invalid)
        assert "only the default" in str(error.exception)


@test(mark="fast")
def default_operation_cannot_be_relabelled_as_the_old_format() -> None:
    """A new operation and its contraction metadata require explicit format 3."""
    first = m.compile(m.generate("001", [Original], backend="sqlite"))
    package = m.compile(m.generate("002", [Changed], backend="sqlite", previous=first))
    payload = json.loads(package.dump())
    payload["version"] = 2
    with assert_raises(m.PackageError):
        m.Package.load(json.dumps(payload))


class Nullable[S = sqlite.Pending](sqlite.Model[S]):
    """Nullable declaration with no explicit default."""

    __tablename__ = "settings"
    __row_type__: ClassVar[sqlite.ReadType[Nullable[sqlite.Row]]]
    id: sqlite.Col[int] = sqlite.Integer(primary_key=True)
    value: sqlite.Col[int | None] = sqlite.Integer(nullable=True)


class NullDefault[S = sqlite.Pending](sqlite.Model[S]):
    """An explicit NULL is still a recorded declaration."""

    __tablename__ = "settings"
    __row_type__: ClassVar[sqlite.ReadType[NullDefault[sqlite.Row]]]
    id: sqlite.Col[int] = sqlite.Integer(primary_key=True)
    value: sqlite.GenCol[int | None] = sqlite.Integer(
        nullable=True, default=sqlite.LiteralDefault(None)
    )


class NegativeDefault[S = sqlite.Pending](sqlite.Model[S]):
    """Signed integer defaults remain bounded declaration edits."""

    __tablename__ = "settings"
    __row_type__: ClassVar[sqlite.ReadType[NegativeDefault[sqlite.Row]]]
    id: sqlite.Col[int] = sqlite.Integer(primary_key=True)
    value: sqlite.GenCol[int | None] = sqlite.Integer(
        nullable=True, default=sqlite.LiteralDefault(-9)
    )


@test(mark="medium")
async def nullable_defaults_can_be_set_changed_and_removed_without_filling_nulls() -> (
    None
):
    """Physical NULL/absent declarations differ while old SQL NULL values survive."""
    previous = None
    packages = []
    for revision, model in enumerate(
        (Nullable, NullDefault, NegativeDefault, Nullable), 1
    ):
        previous = m.Package.load(
            m.compile(
                m.generate(str(revision), [model], backend="sqlite", previous=previous)
            ).dump()
        )
        packages.append(previous)
    with TemporaryDirectory() as directory:
        config = sqlite.Config(database=Path(directory) / "defaults.db")
        for revision, package in enumerate(packages, 1):
            async with m.connect(config) as target:
                assert_eq(await target.apply(await target.prepare(package)), "applied")
            async with (
                await sqlite.Database.initialize(config) as database,
                database.transaction() as transaction,
            ):
                await transaction.execute(
                    sqlite.raw("INSERT INTO settings(id) VALUES(?)", params=(revision,))
                )
        async with (
            await sqlite.Database.initialize(config) as database,
            database.transaction() as transaction,
        ):
            assert_eq(
                await transaction.fetch_all(
                    sqlite.raw("SELECT value FROM settings ORDER BY id")
                ),
                [{"value": None}, {"value": None}, {"value": -9}, {"value": None}],
            )


@test(mark="medium")
async def default_rebuild_preserves_unmanaged_data_and_dependencies() -> None:
    """Rebuilding for a default does not drop extensions or fire insert triggers on copies."""
    first = m.compile(m.generate("001", [Original], backend="sqlite"))
    second = m.Package.load(
        m.compile(m.generate("002", [Changed], backend="sqlite", previous=first)).dump()
    )
    with TemporaryDirectory() as directory:
        config = sqlite.Config(database=Path(directory) / "defaults.db")
        async with m.connect(config) as target:
            await target.apply(await target.prepare(first))
        async with aiosqlite.connect(str(config.database)) as legacy:
            for sql in (
                "ALTER TABLE settings ADD COLUMN opaque BLOB DEFAULT X'00FF'",
                "CREATE INDEX extra_index ON settings(opaque)",
                "CREATE TABLE audit(id INTEGER, value INTEGER)",
                "CREATE VIEW visible_settings AS SELECT * FROM settings",
                "CREATE TRIGGER inserted AFTER INSERT ON settings BEGIN INSERT INTO audit VALUES(NEW.id,NEW.value); END",
                "INSERT INTO settings(id,opaque) VALUES(1,X'1234')",
            ):
                await legacy.execute(sql)
            await legacy.commit()
        async with m.connect(config) as target:
            await target.apply(await target.prepare(second, preserve_unmanaged=True))
        async with (
            await sqlite.Database.initialize(config) as database,
            database.transaction() as transaction,
        ):
            await transaction.execute(sqlite.raw("INSERT INTO settings(id) VALUES(2)"))
            assert_eq(
                await transaction.fetch_all(
                    sqlite.raw(
                        "SELECT id, value, hex(opaque) AS opaque FROM visible_settings ORDER BY id"
                    )
                ),
                [
                    {"id": 1, "value": 7, "opaque": "1234"},
                    {"id": 2, "value": 8, "opaque": "00FF"},
                ],
            )
            assert_eq(
                await transaction.fetch_all(
                    sqlite.raw("SELECT id,value FROM audit ORDER BY id")
                ),
                [{"id": 1, "value": 7}, {"id": 2, "value": 8}],
            )
            assert_eq(
                await transaction.fetch_all(
                    sqlite.raw(
                        "SELECT name FROM sqlite_schema WHERE type='index' AND name='extra_index'"
                    )
                ),
                [{"name": "extra_index"}],
            )


class TextBefore[S = sqlite.Pending](sqlite.Model[S]):
    """Encoded literals must not be mistaken for declaration syntax."""

    __tablename__ = "labels"
    __row_type__: ClassVar[sqlite.ReadType[TextBefore[sqlite.Row]]]
    id: sqlite.Col[int] = sqlite.Integer(primary_key=True)
    label: sqlite.GenCol[str] = sqlite.Text(
        default=sqlite.LiteralDefault("DEFAULT ) CHECK '\0é")
    )


class TextAfter[S = sqlite.Pending](sqlite.Model[S]):
    """A new encoded value, not a new column constraint."""

    __tablename__ = "labels"
    __row_type__: ClassVar[sqlite.ReadType[TextAfter[sqlite.Row]]]
    id: sqlite.Col[int] = sqlite.Integer(primary_key=True)
    label: sqlite.GenCol[str] = sqlite.Text(default=sqlite.LiteralDefault("new ([ \0é"))


@test(mark="medium")
async def encoded_text_default_changes_preserve_literal_values() -> None:
    """Parenthesized encodings, quotes, punctuation, NUL and Unicode survive."""
    first = m.compile(m.generate("001", [TextBefore], backend="sqlite"))
    second = m.Package.load(
        m.compile(
            m.generate("002", [TextAfter], backend="sqlite", previous=first)
        ).dump()
    )
    with TemporaryDirectory() as directory:
        config = sqlite.Config(database=Path(directory) / "defaults.db")
        for revision, package in enumerate((first, second), 1):
            async with m.connect(config) as target:
                await target.apply(await target.prepare(package))
            async with (
                await sqlite.Database.initialize(config) as database,
                database.transaction() as transaction,
            ):
                await transaction.execute(
                    sqlite.raw("INSERT INTO labels(id) VALUES(?)", params=(revision,))
                )
        async with (
            await sqlite.Database.initialize(config) as database,
            database.transaction() as transaction,
        ):
            assert_eq(
                await transaction.fetch_all(
                    sqlite.raw("SELECT label FROM labels ORDER BY id")
                ),
                [{"label": "DEFAULT ) CHECK '\0é"}, {"label": "new ([ \0é"}],
            )


class NativeBefore[S = mariadb.Pending](mariadb.Model[S]):
    """Initial native default."""

    __tablename__ = "native_defaults"
    __row_type__: ClassVar[mariadb.ReadType[NativeBefore[mariadb.Row]]]
    value: mariadb.GenCol[int] = mariadb.Integer(default=mariadb.LiteralDefault(7))


class NativeAfter[S = mariadb.Pending](mariadb.Model[S]):
    """Desired native default transition."""

    __tablename__ = "native_defaults"
    __row_type__: ClassVar[mariadb.ReadType[NativeAfter[mariadb.Row]]]
    value: mariadb.GenCol[int] = mariadb.Integer(default=mariadb.LiteralDefault(8))


@test(mark="fast")
def native_default_alteration_generates_a_frozen_reviewable_route() -> None:
    """Explicit authoring and generation agree on the supported native operation."""
    first = m.compile(m.generate("001", [NativeBefore], backend="mariadb"))
    draft = m.generate("002", [NativeAfter], backend="mariadb", previous=first)
    assert_eq(draft.unresolved, ())
    package = m.compile(draft)
    assert_eq(package.version, 3)
    assert_eq(m.Package.load(package.dump()), package)
    assert_eq(
        package.statements,
        ("ALTER TABLE `native_defaults` ALTER COLUMN `value` SET DEFAULT 8",),
    )


@test(mark="fast")
def old_format_cannot_carry_new_default_transition_metadata() -> None:
    """An empty new field cannot silently broaden the old format's vocabulary."""
    payload = json.loads(
        (Path(__file__).parent / "fixtures" / "format2" / "003.json").read_text()
    )
    payload["contractions"][0]["defaults"] = []
    with assert_raises(m.PackageError) as error:
        m.Package.load(json.dumps(payload))
    assert "version 3" in str(error.exception)


_MODEL_FREE_DEFAULT = r"""
import asyncio,json,sys
from pathlib import Path
from snekql import sqlite
from snekql.errors import ExecutionError
from snekql.experimental import migrations as m
async def main():
    root=Path(sys.argv[1])
    packages=[m.Package.load((root/f"{n}.json").read_text()) for n in (1,2)]
    assert [p.version for p in packages]==[2,3]
    config=sqlite.Config(database=root/"deployed.db")
    for n,package in enumerate(packages,1):
        async with m.connect(config) as target:
            assert await target.apply(await target.prepare(package))=="applied"
        async with await sqlite.Database.initialize(config) as db, db.transaction() as tx:
            await tx.execute(sqlite.raw("INSERT INTO settings(id) VALUES(?)",params=(n,)))
    async with await sqlite.Database.initialize(config) as db, db.transaction() as tx:
        rows=await tx.fetch_all(sqlite.raw("SELECT value FROM settings ORDER BY id"))
    assert "tests.experimental.test_migration_default_changes" not in sys.modules
    print(json.dumps(rows))
asyncio.run(main())
"""


@test(mark="medium")
async def format_three_default_change_deploys_without_authoring_models() -> None:
    """The new operation needs only frozen bytes in a fresh deployment process."""
    first = m.compile(m.generate("001", [Original], backend="sqlite"))
    second = m.compile(m.generate("002", [Changed], backend="sqlite", previous=first))
    with TemporaryDirectory() as directory:
        root = Path(directory)
        for n, package in enumerate((first, second), 1):
            await asyncio.to_thread((root / f"{n}.json").write_text, package.dump())
        process = await asyncio.create_subprocess_exec(
            sys.executable,
            "-c",
            _MODEL_FREE_DEFAULT,
            directory,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=60)
            assert_eq(process.returncode, 0, msg=stderr.decode())
            assert_eq(json.loads(stdout), [{"value": 7}, {"value": 8}])
        finally:
            if process.returncode is None:
                process.kill()
                await process.wait()


@test(mark="fast")
def ambiguous_default_declarations_fail_compilation() -> None:
    """A structured edit cannot guess which default expression to replace."""
    first = m.compile(m.generate("001", [Original], backend="sqlite"))
    draft = m.generate("002", [Changed], backend="sqlite", previous=first)
    table = draft.target.tables[0]
    for declaration, diagnostic in (
        ('"value" INTEGER NOT NULL DEFAULT 8 DEFAULT 9', "DEFAULT"),
        ('"value" INTEGER NOT NULL DEFAULT', "DEFAULT"),
        ('"value" INTEGER NOT NULL DEFAULT (8', "managed column construction"),
    ):
        column = table.columns[1].model_copy(update={"definition": declaration})
        altered = table.model_copy(
            update={
                "columns": (table.columns[0], column),
                "sql": table.sql.replace(table.columns[1].definition, declaration),
            }
        )
        with assert_raises(m.PackageError) as error:
            m.compile(
                draft.model_copy(
                    update={
                        "target": draft.target.model_copy(
                            update={"tables": (altered,)}
                        ),
                        "operations": (
                            m.ChangeDefault(table_name=table.name, column=column),
                        ),
                    }
                )
            )
        assert diagnostic in str(error.exception)


@test(mark="medium")
async def required_default_transition_refuses_nulls_without_backfilling() -> None:
    """A future insertion default cannot repair existing NULLs implicitly."""
    first = m.compile(m.generate("001", [Nullable], backend="sqlite"))
    draft = m.generate("002", [Changed], backend="sqlite", previous=first)
    assert_eq(draft.unresolved, ())
    second = m.Package.load(m.compile(draft).dump())
    assert_eq(second.version, 3)
    with TemporaryDirectory() as directory:
        config = sqlite.Config(database=Path(directory) / "combined.db")
        async with m.connect(config) as target:
            await target.apply(await target.prepare(first))
        async with (
            await sqlite.Database.initialize(config) as database,
            database.transaction() as transaction,
        ):
            await transaction.execute(
                sqlite.raw("INSERT INTO settings(id,value) VALUES(1,NULL),(2,42)")
            )
        async with m.connect(config) as target:
            plan = await target.prepare(second)
            with assert_raises(m.PackageError) as error:
                await target.apply(plan)
            assert "NULL rows remain" in str(error.exception)
            assert_eq([entry.revision for entry in await target.status()], ["001"])
        async with (
            await sqlite.Database.initialize(config) as database,
            database.transaction() as transaction,
        ):
            # Refusal leaves both the old values and the old nullable/default-free schema.
            await transaction.execute(sqlite.raw("INSERT INTO settings(id) VALUES(3)"))
            assert_eq(
                await transaction.fetch_all(
                    sqlite.raw("SELECT value FROM settings ORDER BY id")
                ),
                [{"value": None}, {"value": 42}, {"value": None}],
            )
            await transaction.execute(
                sqlite.raw("UPDATE settings SET value=5 WHERE value IS NULL")
            )
        async with m.connect(config) as target:
            assert_eq(await target.apply(plan), "applied")
            assert_eq(
                await target.apply(await target.prepare(second)), "already_applied"
            )
        async with (
            await sqlite.Database.initialize(config) as database,
            database.transaction() as transaction,
        ):
            await transaction.execute(sqlite.raw("INSERT INTO settings(id) VALUES(4)"))
            assert_eq(
                await transaction.fetch_all(
                    sqlite.raw("SELECT value FROM settings ORDER BY id")
                ),
                [{"value": 5}, {"value": 42}, {"value": 5}, {"value": 8}],
            )
        async with await sqlite.Database.initialize(config) as database:
            with assert_raises(ExecutionError):
                async with database.transaction() as transaction:
                    await transaction.execute(
                        sqlite.raw("INSERT INTO settings(id,value) VALUES(5,NULL)")
                    )


@test(mark="medium")
async def required_default_removal_can_follow_an_explicit_typed_backfill() -> None:
    """A composed route fills only selected rows before enforcing the new contract."""
    first = m.compile(m.generate("001", [NegativeDefault], backend="sqlite"))
    generated = m.generate("002", [Required], backend="sqlite", previous=first)
    assert_eq(generated.unresolved, ())
    staged = generated.model_copy(update={"operations": ()}).then(
        m.Checkpoint(name="nullable")
    )
    staged = staged.then(
        m.DataChange.from_query(
            sqlite.update(NegativeDefault)
            .set(NegativeDefault.value.to(5))
            .where(NegativeDefault.value.is_null()),
            checkpoint="nullable",
            contract_digest=m.contract_digest(staged, point="nullable"),
        )
    )
    for operation in generated.operations:
        staged = staged.then(operation)
    package = m.Package.load(m.compile(staged).dump())
    assert_eq(package.version, 3)
    with TemporaryDirectory() as directory:
        config = sqlite.Config(database=Path(directory) / "backfill.db")
        async with m.connect(config) as target:
            await target.apply(await target.prepare(first))
        async with (
            await sqlite.Database.initialize(config) as database,
            database.transaction() as transaction,
        ):
            await transaction.execute(
                sqlite.raw("INSERT INTO settings(id,value) VALUES(1,NULL)")
            )
            await transaction.execute(sqlite.raw("INSERT INTO settings(id) VALUES(2)"))
        async with m.connect(config) as target:
            assert_eq(await target.apply(await target.prepare(package)), "applied")
        async with (
            await sqlite.Database.initialize(config) as database,
            database.transaction() as transaction,
        ):
            assert_eq(
                await transaction.fetch_all(
                    sqlite.raw("SELECT value FROM settings ORDER BY id")
                ),
                [{"value": 5}, {"value": -9}],
            )
        async with await sqlite.Database.initialize(config) as database:
            with assert_raises(ExecutionError):
                async with database.transaction() as transaction:
                    await transaction.execute(
                        sqlite.raw("INSERT INTO settings(id) VALUES(3)")
                    )


@test(mark="fast")
def combined_nullable_default_generation_uses_frozen_relaxation() -> None:
    """Nullable/default composition now needs the explicit format-four vocabulary."""
    required = m.compile(m.generate("001", [Original], backend="sqlite"))
    relaxed = m.generate("002", [NegativeDefault], backend="sqlite", previous=required)
    assert_eq(relaxed.unresolved, ())
    package = m.compile(relaxed)
    assert_eq(package.version, 4)
    assert_eq(m.Package.load(package.dump()), package)

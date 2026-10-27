"""Recorded managed columns must exist as declarations in construction SQL."""

from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Literal

from snektest import Param, assert_eq, assert_raises, load_fixture, test

from snekql import mariadb, sqlite
from snekql.experimental import migrations as m
from tests.experimental.test_migration_nullability import NativeRequired, Required
from tests.experimental.test_migration_targets import provide_package_server


@test(
    [
        Param[Literal["sqlite", "mariadb"]](value="sqlite", name="sqlite"),
        Param[Literal["sqlite", "mariadb"]](value="mariadb", name="mariadb"),
    ]
)
async def missing_managed_column_is_refused_before_construction(
    backend: Literal["sqlite", "mariadb"],
) -> None:
    """Matching table ownership cannot certify an absent physical column claim."""
    draft = m.generate(
        "001", [Required] if backend == "sqlite" else [NativeRequired], backend=backend
    )
    table = draft.target.tables[0]
    table = table.model_copy(
        update={
            "sql": f"CREATE TABLE {table.quoted_name} ({table.columns[0].definition})"
        }
    )
    with assert_raises(m.PackageError) as error:
        m.compile(
            draft.model_copy(
                update={
                    "target": draft.target.model_copy(update={"tables": (table,)}),
                    "operations": (m.CreateTable(table=table),),
                }
            )
        )
    assert "managed column construction" in str(error.exception)


@test(
    [
        Param(value=parts, name=str(i))
        for i, parts in enumerate(
            (
                "id INTEGER PRIMARY KEY, note TEXT DEFAULT 'value'",
                'id INTEGER PRIMARY KEY, CONSTRAINT "value" CHECK(id>=0)',
                "id INTEGER PRIMARY KEY, CHECK(value>=0)",
                'id INTEGER PRIMARY KEY, "value copy" INTEGER',
                'id INTEGER PRIMARY KEY, /* "value" INTEGER */ note TEXT',
                'id INTEGER PRIMARY KEY, "VALUE" INTEGER, "value" INTEGER',
                "id INTEGER PRIMARY KEY, 'value' INTEGER",
            )
        )
    ]
)
async def mentions_and_ambiguous_declarations_cannot_satisfy_column_claims(
    parts: str,
) -> None:
    """Only one real bounded declaration binds; expressions, strings and comments do not."""
    draft = m.generate("001", [Required], backend="sqlite")
    table = draft.target.tables[0].model_copy(
        update={"sql": f'CREATE TABLE "entries" ({parts}) STRICT'}
    )
    with assert_raises(m.PackageError) as error:
        m.compile(
            draft.model_copy(
                update={
                    "target": draft.target.model_copy(update={"tables": (table,)}),
                    "operations": (m.CreateTable(table=table),),
                }
            )
        )
    assert "managed column construction" in str(error.exception)


@test([Param(value=scope, name=scope) for scope in ("before", "intermediate", "adopt")])
async def column_presence_cannot_be_erased_by_relinquishment(scope: str) -> None:
    """Before snapshots and intermediate ownership still carry their positive claims."""
    first = m.compile(m.generate("001", [Required], backend="sqlite"))
    table = first.target.tables[0]
    table = table.model_copy(
        update={"sql": f'CREATE TABLE "entries" ({table.columns[0].definition}) STRICT'}
    )
    empty = m.State(backend="sqlite")
    if scope == "before":
        draft = m.Draft(
            revision="002",
            predecessor=first.digest,
            before=first.target.model_copy(update={"tables": (table,)}),
            target=empty,
            operations=(m.RelinquishTable(table_name="entries"),),
        )
    else:
        operation = (
            m.AdoptTable(table=table)
            if scope == "adopt"
            else m.CreateTable(table=table)
        )
        draft = m.Draft(
            revision="001",
            predecessor=None,
            before=empty,
            target=empty,
            operations=(operation, m.RelinquishTable(table_name="entries")),
        )
    with assert_raises(m.PackageError) as error:
        m.compile(draft)
    assert "managed column construction" in str(error.exception)


@test(
    [
        Param[Literal["sqlite", "mariadb"]](value="sqlite", name="sqlite"),
        Param[Literal["sqlite", "mariadb"]](value="mariadb", name="mariadb"),
    ],
    mark="slow",
)
async def reordered_case_variant_declarations_do_not_expand_column_claims(
    backend: Literal["sqlite", "mariadb"],
) -> None:
    """Presence is one-way: extra construction declarations are not ColumnState authority."""
    draft = m.generate(
        "001", [Required] if backend == "sqlite" else [NativeRequired], backend=backend
    )
    original = draft.target.tables[0]
    definitions = [
        c.definition.replace(c.name, c.name.upper(), 1)
        for c in reversed(original.columns)
    ]
    extra = (
        '"extra" INTEGER DEFAULT 9'
        if backend == "sqlite"
        else "`extra` BIGINT DEFAULT 9"
    )
    suffix = " STRICT" if backend == "sqlite" else " ENGINE=InnoDB"
    table = original.model_copy(
        update={
            "sql": f"CREATE TABLE {original.quoted_name} ("
            + ", ".join((*definitions, extra))
            + ")"
            + suffix
        }
    )
    package = m.Package.load(
        m.compile(
            draft.model_copy(
                update={
                    "target": draft.target.model_copy(update={"tables": (table,)}),
                    "operations": (m.CreateTable(table=table),),
                }
            )
        ).dump()
    )
    assert_eq(package.target.tables[0].columns, original.columns)
    with assert_raises(m.PackageError):
        m.compile(
            m.Draft(
                revision="002",
                predecessor=package.digest,
                before=package.target,
                target=package.target,
                operations=(m.DropColumn(table_name="entries", column_name="extra"),),
            )
        )
    with TemporaryDirectory() as directory:
        config = (
            sqlite.Config(database=Path(directory) / "app.db")
            if backend == "sqlite"
            else (await load_fixture(provide_package_server())).config()
        )
        async with m.connect(config) as target:
            await target.apply(
                await target.prepare(
                    package, schema_writers_excluded=backend == "mariadb"
                )
            )
            assert_eq((await target.status())[0].phase, "complete")
        if backend == "sqlite":
            assert isinstance(config, sqlite.Config)
            async with (
                await sqlite.Database.initialize(config) as db,
                db.transaction() as tx,
            ):
                await tx.execute(sqlite.raw("INSERT INTO entries(id) VALUES(42)"))
                assert_eq(
                    await tx.fetch_all(
                        sqlite.raw(
                            "SELECT id AS id,value AS value,extra AS extra FROM entries"
                        )
                    ),
                    [{"id": 42, "value": 7, "extra": 9}],
                )
        else:
            assert isinstance(config, mariadb.Config)
            async with (
                await mariadb.Database.initialize(config) as db,
                db.transaction() as tx,
            ):
                await tx.execute(mariadb.raw("INSERT INTO entries(id) VALUES(42)"))
                assert_eq(
                    await tx.fetch_all(
                        mariadb.raw(
                            "SELECT id AS id,value AS value,extra AS extra FROM entries"
                        )
                    ),
                    [{"id": 42, "value": 7, "extra": 9}],
                )


@test()
async def sqlite_distinct_unicode_identifier_does_not_supply_a_missing_claim() -> None:
    """ASCII case handling must not conflate physically distinct SQLite names."""
    draft = m.generate("001", [Required], backend="sqlite")
    original = draft.target.tables[0]
    column = original.columns[1].model_copy(
        update={"name": "é", "definition": '"é" INTEGER NOT NULL DEFAULT 7'}
    )
    table = original.model_copy(
        update={
            "columns": (original.columns[0], column),
            "sql": 'CREATE TABLE "entries" ("id" INTEGER PRIMARY KEY, "É" INTEGER NOT NULL DEFAULT 7) STRICT',
        }
    )
    with assert_raises(m.PackageError) as error:
        m.compile(
            draft.model_copy(
                update={
                    "target": draft.target.model_copy(update={"tables": (table,)}),
                    "operations": (m.CreateTable(table=table),),
                }
            )
        )
    assert "managed column construction" in str(error.exception)


@test()
async def actual_old_missing_column_artifact_is_refused_without_conversion() -> None:
    """Preserve real old valid bytes but refuse the artifact that falsely completed."""
    root = Path(__file__).parent / "fixtures" / "column-coverage"
    valid = (root / "valid-old.json").read_text()
    package = m.Package.load(valid)
    assert_eq(
        package.digest,
        "dd861098a813e3e1cb465536dc28b511d527b6fc82d1b53dd195e5d385e0a5c1",
    )
    assert_eq(package.dump(), valid)
    with assert_raises(m.PackageError) as error:
        m.Package.load((root / "invalid-old.json").read_text())
    assert "managed column construction" in str(error.exception)


@test(mark="medium")
async def preparation_revalidates_old_in_memory_column_claims_without_effects() -> None:
    """Typed in-memory package objects cannot bypass the compiler/load authority gate."""
    root = Path(__file__).parent / "fixtures" / "column-coverage"
    old = m.Package.model_validate_json((root / "invalid-old.json").read_text())
    with TemporaryDirectory() as directory:
        config = sqlite.Config(database=Path(directory) / "app.db")
        async with m.connect(config) as target:
            with assert_raises(m.PackageError) as error:
                await target.prepare(old)
            assert "managed column construction" in str(error.exception)
            assert_eq(await target.status(), ())
        async with (
            await sqlite.Database.initialize(config) as db,
            db.transaction() as tx,
        ):
            assert_eq(
                await tx.fetch_all(sqlite.raw("SELECT name FROM sqlite_schema")), []
            )

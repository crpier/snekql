"""Table construction cannot execute under a different recorded ownership claim."""

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
async def construction_header_cannot_name_an_unowned_table(
    backend: Literal["sqlite", "mariadb"],
) -> None:
    """Matching redundant metadata does not authorize CREATE of a different table."""
    draft = m.generate(
        "001", [Required] if backend == "sqlite" else [NativeRequired], backend=backend
    )
    table = draft.target.tables[0]
    table = table.model_copy(
        update={
            "sql": table.sql.replace(
                table.quoted_name,
                '"unowned"' if backend == "sqlite" else "`unowned`",
                1,
            )
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
    assert "construction header" in str(error.exception)


@test(
    [
        Param(value=sql, name=str(i))
        for i, sql in enumerate(
            (
                "CREATE VIEW entries AS SELECT 1 AS id",
                'CREATE TEMP TABLE "entries" (id INTEGER)',
                'CREATE VIRTUAL TABLE "entries" USING fts5(value)',
                'CREATE TABLE IF NOT EXISTS "entries" (id INTEGER)',
                'CREATE TABLE main."entries" (id INTEGER)',
                'CREATE TABLE "entries" AS SELECT 1 AS id',
                'CREATE TABLE "entries" LIKE unowned',
                'CREATE/* header */ TABLE "entries" (id INTEGER)',
                '-- header\nCREATE TABLE "entries" (id INTEGER)',
                'CREATE TABLE "entries"/* owner */ (id INTEGER)',
            )
        )
    ]
)
async def unsupported_construction_headers_require_an_explicit_adapter(
    sql: str,
) -> None:
    """Temporary, guarded, indirect, qualified and commented construction is not inferred."""
    draft = m.generate("001", [Required], backend="sqlite")
    table = draft.target.tables[0].model_copy(update={"sql": sql})
    with assert_raises(m.PackageError) as error:
        m.compile(
            draft.model_copy(
                update={
                    "target": draft.target.model_copy(update={"tables": (table,)}),
                    "operations": (m.CreateTable(table=table),),
                }
            )
        )
    assert "construction header" in str(error.exception)


@test(
    [
        Param(value="before", name="before"),
        Param(value="intermediate", name="intermediate"),
        Param(value="adopt", name="adopt"),
    ]
)
async def header_authority_cannot_be_erased_by_relinquishment(scope: str) -> None:
    """Frozen source claims and intermediate construction remain independently bound."""
    first = m.compile(m.generate("001", [Required], backend="sqlite"))
    table = first.target.tables[0]
    table = table.model_copy(
        update={"sql": table.sql.replace(table.quoted_name, '"unowned"', 1)}
    )
    empty = m.State(backend="sqlite")
    if scope == "before":
        draft = m.Draft(
            revision="002",
            predecessor=first.digest,
            before=first.target.model_copy(update={"tables": (table,)}),
            target=empty,
            operations=(m.RelinquishTable(table_name=table.name),),
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
            operations=(operation, m.RelinquishTable(table_name=table.name)),
        )
    with assert_raises(m.PackageError) as error:
        m.compile(draft)
    assert "construction header" in str(error.exception)


@test(
    [
        Param[Literal["sqlite", "mariadb"]](value="sqlite", name="sqlite"),
        Param[Literal["sqlite", "mariadb"]](value="mariadb", name="mariadb"),
    ],
    mark="slow",
)
async def ordinary_headers_retain_quoted_names_keyword_case_and_whitespace(
    backend: Literal["sqlite", "mariadb"],
) -> None:
    """The gate checks owner tokens rather than substring keyword/name heuristics."""
    draft = m.generate(
        "001", [Required] if backend == "sqlite" else [NativeRequired], backend=backend
    )
    table = draft.target.tables[0]
    name = 'create "table`on]é'
    delimiter = '"' if backend == "sqlite" else "`"
    quoted = delimiter + name.replace(delimiter, delimiter * 2) + delimiter
    table = table.model_copy(
        update={
            "name": name,
            "quoted_name": quoted,
            "sql": table.sql.replace(table.quoted_name, quoted, 1).replace(
                "CREATE TABLE", " \nCrEaTe\tTaBlE", 1
            ),
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
    with TemporaryDirectory() as directory:
        config = (
            sqlite.Config(database=Path(directory) / "quoted.db")
            if backend == "sqlite"
            else (await load_fixture(provide_package_server())).config()
        )
        async with m.connect(config) as target:
            plan = await target.prepare(
                package, schema_writers_excluded=backend == "mariadb"
            )
            assert_eq(await target.apply(plan), "applied")
            assert_eq((await target.status())[0].phase, "complete")
        if backend == "sqlite":
            assert isinstance(config, sqlite.Config)
            async with (
                await sqlite.Database.initialize(config) as db,
                db.transaction() as tx,
            ):
                await tx.execute(sqlite.raw("INSERT INTO " + quoted + " VALUES(42,7)"))
                assert_eq(
                    await tx.fetch_all(sqlite.raw("SELECT id FROM " + quoted)),
                    [{"id": 42}],
                )
        else:
            assert isinstance(config, mariadb.Config)
            async with (
                await mariadb.Database.initialize(config) as db,
                db.transaction() as tx,
            ):
                await tx.execute(mariadb.raw("INSERT INTO " + quoted + " VALUES(42,7)"))
                assert_eq(
                    await tx.fetch_all(mariadb.raw("SELECT id FROM " + quoted)),
                    [{"id": 42}],
                )


@test()
async def actual_old_wrong_owner_package_refuses_without_rewriting_identity() -> None:
    """An actual former compiler's accepted package is explicitly refused at load."""
    root = Path(__file__).parent / "fixtures"
    valid = (root / "identifier-claims" / "valid.json").read_text()
    assert_eq(m.Package.load(valid).dump(), valid)
    with assert_raises(m.PackageError) as error:
        m.Package.load((root / "construction-headers" / "wrong-owner.json").read_text())
    assert "construction header" in str(error.exception)

"""Ordinary nullability flags must agree with frozen declarations before effects."""

from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Literal

from snektest import Param, assert_eq, assert_raises, load_fixture, test

from snekql import mariadb, sqlite
from snekql.experimental import migrations as m
from tests.experimental.test_migration_nullability import (
    NativeOptional,
    NativeRequired,
    Optional,
    Required,
)
from tests.experimental.test_migration_targets import provide_package_server


@test(
    [
        Param[Literal["sqlite", "mariadb"]](value="sqlite", name="sqlite"),
        Param[Literal["sqlite", "mariadb"]](value="mariadb", name="mariadb"),
    ]
)
async def nullable_flag_cannot_contradict_an_ordinary_required_definition(
    backend: Literal["sqlite", "mariadb"],
) -> None:
    """Table SQL and definition agreement do not excuse inconsistent flag metadata."""
    draft = m.generate(
        "001", [Required] if backend == "sqlite" else [NativeRequired], backend=backend
    )
    table = draft.target.tables[0]
    column = table.columns[1].model_copy(update={"nullable": True})
    table = table.model_copy(update={"columns": (table.columns[0], column)})
    with assert_raises(m.PackageError) as error:
        m.compile(
            draft.model_copy(
                update={
                    "target": draft.target.model_copy(update={"tables": (table,)}),
                    "operations": (m.CreateTable(table=table),),
                }
            )
        )
    assert "ordinary column nullability" in str(error.exception)


@test([Param(value=case, name=case) for case in ("required", "nullable")])
async def construction_nullability_must_agree_in_both_directions(case: str) -> None:
    """Consistent flag/definition metadata cannot authorize opposite construction SQL."""
    draft = m.generate("001", [Required], backend="sqlite")
    table = draft.target.tables[0]
    column = table.columns[1]
    if case == "required":
        sql = table.sql.replace(
            column.definition, column.definition.replace(" NOT NULL", "")
        )
    else:
        column = column.model_copy(
            update={
                "nullable": True,
                "definition": column.definition.replace(" NOT NULL", ""),
            }
        )
        sql = table.sql
    table = table.model_copy(update={"sql": sql, "columns": (table.columns[0], column)})
    with assert_raises(m.PackageError) as error:
        m.compile(
            draft.model_copy(
                update={
                    "target": draft.target.model_copy(update={"tables": (table,)}),
                    "operations": (m.CreateTable(table=table),),
                }
            )
        )
    assert "ordinary column nullability" in str(error.exception)


@test()
async def relinquishment_cannot_hide_an_inconsistent_add_column_payload() -> None:
    """Intermediate ADD must not smuggle required SQL under a nullable flag."""
    first = m.compile(m.generate("001", [Required], backend="sqlite"))
    column = m.ColumnState(
        name="note",
        definition='"note" INTEGER NOT NULL',
        nullable=True,
        storage="INTEGER",
    )
    draft = m.Draft(
        revision="002",
        predecessor=first.digest,
        before=first.target,
        target=m.State(backend="sqlite"),
        operations=(
            m.AddColumn(table_name="entries", column=column),
            m.RelinquishTable(table_name="entries"),
        ),
    )
    with assert_raises(m.PackageError) as error:
        m.compile(draft)
    assert "ordinary column nullability" in str(error.exception)


@test(
    [
        Param(value=case, name=str(i))
        for i, case in enumerate(
            (
                ('"value" INTEGER DEFAULT NULL', True),
                ("\"value\" TEXT DEFAULT 'NOT NULL PRIMARY KEY'", True),
                ('"value" INTEGER CHECK(value IS NOT NULL)', True),
                ('"value" INTEGER NOT NULL DEFAULT(NULL)', False),
            )
        )
    ]
)
async def default_and_expression_null_tokens_do_not_become_column_clauses(
    case: tuple[str, bool],
) -> None:
    """Declared nullability remains independent of defaults, literals and CHECK effects."""
    declaration, nullable = case
    draft = m.generate("001", [Required], backend="sqlite")
    table = draft.target.tables[0]
    original = table.columns[1]
    column = original.model_copy(
        update={
            "definition": declaration,
            "nullable": nullable,
            "query_type": None,
            "storage": "TEXT" if "TEXT" in declaration else "INTEGER",
        }
    )
    table = table.model_copy(
        update={
            "sql": table.sql.replace(original.definition, declaration),
            "columns": (table.columns[0], column),
        }
    )
    package = m.compile(
        draft.model_copy(
            update={
                "target": draft.target.model_copy(update={"tables": (table,)}),
                "operations": (m.CreateTable(table=table),),
            }
        )
    )
    assert package.target.tables[0].columns[1].nullable == nullable


@test(
    [
        Param(value=declaration, name=str(i))
        for i, declaration in enumerate(
            ('"value" INTEGER NOT NULL NULL', '"value" INTEGER NULL NULL')
        )
    ]
)
async def multiple_ordinary_nullability_clauses_require_an_adapter(
    declaration: str,
) -> None:
    """Do not choose one contradictory/redundant clause as the authoritative flag."""
    draft = m.generate("001", [Required], backend="sqlite")
    table = draft.target.tables[0]
    column = table.columns[1].model_copy(update={"definition": declaration})
    table = table.model_copy(
        update={
            "sql": table.sql.replace(table.columns[1].definition, declaration),
            "columns": (table.columns[0], column),
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
    assert "multiple clauses" in str(error.exception)


@test()
async def primary_constraint_names_do_not_exempt_unrelated_ordinary_columns() -> None:
    """A key named value protects id, not the unrelated column called value."""
    draft = m.generate("001", [Required], backend="sqlite")
    table = draft.target.tables[0]
    column = table.columns[1].model_copy(update={"nullable": True})
    table = table.model_copy(
        update={
            "columns": (table.columns[0], column),
            "sql": 'CREATE TABLE "entries" ("id" INTEGER, "value" INTEGER NOT NULL DEFAULT 7, CONSTRAINT "value" PRIMARY KEY ("id")) STRICT',
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
    assert "ordinary column nullability" in str(error.exception)


@test(
    [
        Param[Literal["sqlite", "mariadb"]](value="sqlite", name="sqlite"),
        Param[Literal["sqlite", "mariadb"]](value="mariadb", name="mariadb"),
    ],
    mark="slow",
)
async def ordinary_nullable_defaults_coexist_with_separately_proven_table_keys(
    backend: Literal["sqlite", "mariadb"],
) -> None:
    """A table-level primary key must not imply requiredness for ordinary members."""
    draft = m.generate(
        "001", [Optional] if backend == "sqlite" else [NativeOptional], backend=backend
    )
    table = draft.target.tables[0]
    id_column = table.columns[0].model_copy(
        update={"definition": '"id" INTEGER' if backend == "sqlite" else "`id` BIGINT"}
    )
    quote = '"' if backend == "sqlite" else "`"
    key = f"CONSTRAINT {quote}pk_entries{quote} PRIMARY KEY ({quote}id{quote})"
    suffix = " STRICT" if backend == "sqlite" else " ENGINE=InnoDB"
    table = table.model_copy(
        update={
            "columns": (id_column, table.columns[1]),
            "sql": f"CREATE TABLE {table.quoted_name} ("
            + ", ".join((id_column.definition, table.columns[1].definition, key))
            + ")"
            + suffix,
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
                await tx.execute(sqlite.raw("INSERT INTO entries VALUES(1,NULL)"))
                await tx.execute(sqlite.raw("INSERT INTO entries(id) VALUES(42)"))
                assert_eq(
                    await tx.fetch_all(
                        sqlite.raw("SELECT value FROM entries ORDER BY id")
                    ),
                    [{"value": None}, {"value": 7}],
                )
        else:
            assert isinstance(config, mariadb.Config)
            async with (
                await mariadb.Database.initialize(config) as db,
                db.transaction() as tx,
            ):
                await tx.execute(mariadb.raw("INSERT INTO entries VALUES(1,NULL)"))
                await tx.execute(mariadb.raw("INSERT INTO entries(id) VALUES(42)"))
                assert_eq(
                    await tx.fetch_all(
                        mariadb.raw("SELECT value FROM entries ORDER BY id")
                    ),
                    [{"value": None}, {"value": 7}],
                )


@test([Param(value=scope, name=scope) for scope in ("before", "intermediate", "adopt")])
async def relinquishment_cannot_hide_contradictory_table_nullability(
    scope: str,
) -> None:
    """Unmanaged endpoints do not erase frozen intermediate ordinary claims."""
    first = m.compile(m.generate("001", [Required], backend="sqlite"))
    table = first.target.tables[0]
    table = table.model_copy(update={"sql": table.sql.replace(" NOT NULL", "")})
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
    assert "ordinary column nullability" in str(error.exception)


@test(mark="medium")
async def actual_old_nullable_construction_is_refused_at_load_and_preparation() -> None:
    """Do not certify an old required claim whose real constructor admitted NULL."""
    root = Path(__file__).parent / "fixtures"
    valid = (root / "column-coverage" / "valid-old.json").read_text()
    assert_eq(m.Package.load(valid).dump(), valid)
    text = (root / "nullability-claims" / "invalid-old.json").read_text()
    with assert_raises(m.PackageError) as error:
        m.Package.load(text)
    assert "ordinary column nullability" in str(error.exception)
    old = m.Package.model_validate_json(text)
    with TemporaryDirectory() as directory:
        config = sqlite.Config(database=Path(directory) / "app.db")
        async with m.connect(config) as target:
            with assert_raises(m.PackageError) as error:
                await target.prepare(old)
            assert "ordinary column nullability" in str(error.exception)
            assert_eq(await target.status(), ())

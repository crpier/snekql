"""Physical storage definitions must agree with the SQL constructing managed columns."""

from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Literal

from snektest import Param, assert_eq, assert_raises, test

from snekql import sqlite
from snekql.experimental import migrations as m
from tests.experimental.test_migration_nullability import NativeRequired, Required


@test(
    [
        Param[Literal["sqlite", "mariadb"]](value="sqlite", name="sqlite"),
        Param[Literal["sqlite", "mariadb"]](value="mariadb", name="mariadb"),
    ]
)
async def storage_definition_cannot_certify_a_different_constructor(
    backend: Literal["sqlite", "mariadb"],
) -> None:
    """Column presence and nullability are insufficient for physical storage claims."""
    draft = m.generate(
        "001", [Required] if backend == "sqlite" else [NativeRequired], backend=backend
    )
    table = draft.target.tables[0]
    column = table.columns[1]
    actual = column.definition.replace(
        "INTEGER" if backend == "sqlite" else "BIGINT", "TEXT", 1
    )
    table = table.model_copy(
        update={"sql": table.sql.replace(column.definition, actual)}
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
    assert "construction storage" in str(error.exception)


@test(
    [
        Param(value=spelling, name=str(i))
        for i, spelling in enumerate(("INT", "INTEGER UNSIGNED"))
    ]
)
async def sqlite_affinity_cannot_prove_rowid_type_identity(spelling: str) -> None:
    """INTEGER PRIMARY KEY identity is not implied by an INTEGER-affinity type name."""
    draft = m.generate("001", [Required], backend="sqlite")
    table = draft.target.tables[0]
    column = table.columns[0]
    table = table.model_copy(
        update={
            "sql": table.sql.replace(
                column.definition, column.definition.replace("INTEGER", spelling, 1)
            ).removesuffix(" STRICT")
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
    assert "construction storage" in str(error.exception)


@test()
async def relinquishment_cannot_hide_an_unsupported_native_storage_claim() -> None:
    """An empty final target must not bypass intermediate declaration admission."""
    draft = m.generate("001", [NativeRequired], backend="mariadb")
    table = draft.target.tables[0]
    old = table.columns[1]
    column = old.model_copy(update={"definition": "`value` ENUM('a','b') NOT NULL"})
    table = table.model_copy(
        update={
            "columns": (table.columns[0], column),
            "sql": table.sql.replace(old.definition, column.definition),
        }
    )
    with assert_raises(m.PackageError) as error:
        m.compile(
            draft.model_copy(
                update={
                    "target": m.State(backend="mariadb"),
                    "operations": (
                        m.CreateTable(table=table),
                        m.RelinquishTable(table_name="entries"),
                    ),
                }
            )
        )
    assert "unsupported MariaDB storage" in str(error.exception)


@test([Param(value=scope, name=scope) for scope in ("before", "intermediate", "adopt")])
async def relinquishment_cannot_erase_contradictory_construction_storage(
    scope: str,
) -> None:
    """Frozen intermediate storage claims remain bound even with an empty endpoint."""
    first = m.compile(m.generate("001", [Required], backend="sqlite"))
    table = first.target.tables[0]
    column = table.columns[1]
    table = table.model_copy(
        update={
            "sql": table.sql.replace(
                column.definition, column.definition.replace("INTEGER", "TEXT")
            )
        }
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
        op = (
            m.AdoptTable(table=table)
            if scope == "adopt"
            else m.CreateTable(table=table)
        )
        draft = m.Draft(
            revision="001",
            predecessor=None,
            before=empty,
            target=empty,
            operations=(op, m.RelinquishTable(table_name="entries")),
        )
    with assert_raises(m.PackageError) as error:
        m.compile(draft)
    assert "construction storage" in str(error.exception)


@test(
    [
        Param[Literal["sqlite", "mariadb"]](value="sqlite", name="sqlite"),
        Param[Literal["sqlite", "mariadb"]](value="mariadb", name="mariadb"),
    ]
)
async def intermediate_add_cannot_bypass_storage_admission(
    backend: Literal["sqlite", "mariadb"],
) -> None:
    """Standalone payloads must be checked even when their table is relinquished."""
    first = m.compile(
        m.generate(
            "001",
            [Required] if backend == "sqlite" else [NativeRequired],
            backend=backend,
        )
    )
    definition = (
        '"note" NUMERIC' if backend == "sqlite" else "`note` ENUM('a','b') NULL"
    )
    column = m.ColumnState(
        name="note", definition=definition, nullable=True, storage="native"
    )
    draft = m.Draft(
        revision="002",
        predecessor=first.digest,
        before=first.target,
        target=m.State(backend=backend),
        operations=(
            m.AddColumn(table_name="entries", column=column),
            m.RelinquishTable(table_name="entries"),
        ),
    )
    with assert_raises(m.PackageError) as error:
        m.compile(draft)
    assert "storage" in str(error.exception)


@test(mark="medium")
async def sqlite_finite_strict_type_names_survive_keyword_case_and_preserve_values() -> (
    None
):
    """No affinity collapse or storage-hint/codec inference is needed for physical types."""
    kinds = ("INT", "INTEGER", "REAL", "TEXT", "BLOB", "ANY")
    columns = tuple(
        m.ColumnState(
            name=f"c{i}",
            definition=f'"c{i}" {kind.lower()}',
            nullable=True,
            storage="native",
        )
        for i, kind in enumerate(kinds)
    )
    table = m.TableState(
        name="typed",
        quoted_name='"typed"',
        columns=columns,
        sql='CREATE TABLE "typed" ('
        + ", ".join(f'"c{i}" {kind}' for i, kind in enumerate(kinds))
        + ") STRICT",
    )
    package = m.Package.load(
        m.compile(
            m.Draft(
                revision="001",
                predecessor=None,
                before=m.State(backend="sqlite"),
                target=m.State(backend="sqlite", tables=(table,)),
                operations=(m.CreateTable(table=table),),
            )
        ).dump()
    )
    with TemporaryDirectory() as directory:
        config = sqlite.Config(database=Path(directory) / "app.db")
        async with m.connect(config) as target:
            await target.apply(await target.prepare(package))
            assert_eq((await target.status())[0].phase, "complete")
        async with (
            await sqlite.Database.initialize(config) as db,
            db.transaction() as tx,
        ):
            await tx.execute(
                sqlite.raw("INSERT INTO typed VALUES(7,8,1.5,'kept',x'00ff','001')")
            )
            assert_eq(
                await tx.fetch_all(sqlite.raw("SELECT c0,c1,c2,c3,c4,c5 FROM typed")),
                [
                    {
                        "c0": 7,
                        "c1": 8,
                        "c2": 1.5,
                        "c3": "kept",
                        "c4": b"\x00\xff",
                        "c5": "001",
                    }
                ],
            )


@test(mark="medium")
async def actual_old_text_constructor_cannot_certify_an_integer_definition() -> None:
    """An old real false-completion artifact refuses both load and typed preparation."""
    root = Path(__file__).parent / "fixtures"
    valid = (root / "column-coverage" / "valid-old.json").read_text()
    assert_eq(m.Package.load(valid).dump(), valid)
    text = (root / "storage-claims" / "invalid-old.json").read_text()
    with assert_raises(m.PackageError) as error:
        m.Package.load(text)
    assert "construction storage" in str(error.exception)
    old = m.Package.model_validate_json(text)
    with TemporaryDirectory() as directory:
        config = sqlite.Config(database=Path(directory) / "app.db")
        async with m.connect(config) as target:
            with assert_raises(m.PackageError) as error:
                await target.prepare(old)
            assert "construction storage" in str(error.exception)
            assert_eq(await target.status(), ())

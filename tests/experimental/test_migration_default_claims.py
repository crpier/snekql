"""Frozen defaults must agree with managed construction SQL before effects."""

from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Literal

from snektest import Param, assert_eq, assert_raises, test

from snekql import sqlite
from snekql.experimental import migrations as m
from tests.experimental.test_migration_defaulted_additions import Mixed
from tests.experimental.test_migration_nullability import NativeRequired, Required


@test(
    [
        Param[Literal["sqlite", "mariadb"]](value="sqlite", name="sqlite"),
        Param[Literal["sqlite", "mariadb"]](value="mariadb", name="mariadb"),
    ]
)
async def default_definition_cannot_certify_a_different_constructor(
    backend: Literal["sqlite", "mariadb"],
) -> None:
    """Presence, storage and nullability agreement cannot hide a different insertion default."""
    draft = m.generate(
        "001", [Required] if backend == "sqlite" else [NativeRequired], backend=backend
    )
    table = draft.target.tables[0]
    table = table.model_copy(
        update={"sql": table.sql.replace("DEFAULT 7", "DEFAULT 8")}
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
    assert "construction default" in str(error.exception)


@test(
    [
        Param(value=(backend, change), name=backend + "-" + change)
        for backend in ("sqlite", "mariadb")
        for change in ("missing", "hidden")
    ]
)
async def default_absence_cannot_hide_a_scalar_or_erase_an_explicit_claim(
    case: tuple[str, str],
) -> None:
    """Absence is checked independently of literal changes and future session policy."""
    name, change = case
    backend: Literal["sqlite", "mariadb"] = "sqlite" if name == "sqlite" else "mariadb"
    draft = m.generate(
        "001", [Required] if backend == "sqlite" else [NativeRequired], backend=backend
    )
    table = draft.target.tables[0]
    column = table.columns[1]
    if change == "missing":
        sql = table.sql.replace(" DEFAULT 7", "")
    else:
        column = column.model_copy(
            update={"definition": column.definition.replace(" DEFAULT 7", "")}
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
    assert "construction default" in str(error.exception)


@test(
    [
        Param[Literal["sqlite", "mariadb"]](value="sqlite", name="sqlite"),
        Param[Literal["sqlite", "mariadb"]](value="mariadb", name="mariadb"),
    ]
)
async def nullable_absence_and_null_follow_the_backend_contract(
    backend: Literal["sqlite", "mariadb"],
) -> None:
    """Native effective NULL does not erase SQLite's explicit declaration distinction."""
    draft = m.generate(
        "001", [Required] if backend == "sqlite" else [NativeRequired], backend=backend
    )
    original = draft.target.tables[0]
    before = original.columns[1]
    implicit = before.definition.replace(" NOT NULL", "").replace(" DEFAULT 7", "")
    for definition, constructor in (
        (implicit, implicit + " DEFAULT NULL"),
        (implicit + " DEFAULT NULL", implicit),
    ):
        column = before.model_copy(
            update={
                "definition": definition,
                "nullable": True,
                "query_type": "int | None",
            }
        )
        table = original.model_copy(
            update={
                "columns": (original.columns[0], column),
                "sql": original.sql.replace(before.definition, constructor),
            }
        )
        edited = draft.model_copy(
            update={
                "target": draft.target.model_copy(update={"tables": (table,)}),
                "operations": (m.CreateTable(table=table),),
            }
        )
        if backend == "mariadb":
            m.Package.load(m.compile(edited).dump())
        else:
            with assert_raises(m.PackageError) as error:
                m.compile(edited)
            assert "construction default" in str(error.exception)


@test(
    [
        Param(value=term, name=str(i))
        for i, term in enumerate(
            ("(7+1)", "(coalesce(NULL,7))", "(random())", "7+1", "7.5")
        )
    ]
)
async def identical_unsupported_expressions_are_not_default_proof(term: str) -> None:
    """Equal expression bytes cannot bypass the bounded verification language."""
    draft = m.generate("001", [Required], backend="sqlite")
    table = draft.target.tables[0]
    old = table.columns[1]
    column = old.model_copy(
        update={"definition": old.definition.replace("DEFAULT 7", "DEFAULT " + term)}
    )
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
                    "target": draft.target.model_copy(update={"tables": (table,)}),
                    "operations": (m.CreateTable(table=table),),
                }
            )
        )
    assert "unsupported SQLite DEFAULT" in str(error.exception)


@test(
    [
        Param(value=scope, name=scope)
        for scope in ("before", "intermediate", "adopt", "change_default")
    ]
)
async def relinquishment_cannot_erase_default_claims_or_admission(scope: str) -> None:
    """Frozen sources and standalone default payloads still need proof without final ownership."""
    first = m.compile(m.generate("001", [Required], backend="sqlite"))
    table = first.target.tables[0]
    bad = table.model_copy(update={"sql": table.sql.replace("DEFAULT 7", "DEFAULT 8")})
    empty = m.State(backend="sqlite")
    if scope == "before":
        draft = m.Draft(
            revision="002",
            predecessor=first.digest,
            before=first.target.model_copy(update={"tables": (bad,)}),
            target=empty,
            operations=(m.RelinquishTable(table_name="entries"),),
        )
    elif scope == "change_default":
        column = table.columns[1].model_copy(
            update={
                "definition": table.columns[1].definition.replace(
                    "DEFAULT 7", "DEFAULT (random())"
                )
            }
        )
        draft = m.Draft(
            revision="002",
            predecessor=first.digest,
            before=first.target,
            target=empty,
            operations=(
                m.ChangeDefault(table_name="entries", column=column),
                m.RelinquishTable(table_name="entries"),
            ),
        )
    else:
        op = m.AdoptTable(table=bad) if scope == "adopt" else m.CreateTable(table=bad)
        draft = m.Draft(
            revision="001",
            predecessor=None,
            before=empty,
            target=empty,
            operations=(op, m.RelinquishTable(table_name="entries")),
        )
    with assert_raises(m.PackageError) as error:
        m.compile(draft)
    assert "default" in str(error.exception).lower()


@test(mark="medium")
async def finite_literal_and_clock_defaults_execute_without_model_metadata() -> None:
    """Encoded Unicode/NUL, explicit NULL and cosmetic clock casing stay executable."""
    draft = m.generate("001", [Mixed], backend="sqlite")
    table = draft.target.tables[0]
    table = table.model_copy(
        update={
            "sql": table.sql.replace("DEFAULT NULL", "DEFAULT (((NULL)))").replace(
                "strftime(", "STRFTIME("
            )
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
    assert_eq(package.version, 2)
    frozen = package.dump()
    package = m.Package.load(frozen)
    assert_eq(package.dump(), frozen)
    with TemporaryDirectory() as directory:
        config = sqlite.Config(database=Path(directory) / "defaults.db")
        async with m.connect(config) as target:
            assert_eq(await target.apply(await target.prepare(package)), "applied")
        async with (
            await sqlite.Database.initialize(config) as db,
            db.transaction() as tx,
        ):
            await tx.execute(sqlite.raw("INSERT INTO entries(id) VALUES(42)"))
            row = (
                await tx.fetch_all(
                    sqlite.raw("SELECT id,text,empty,clock FROM entries")
                )
            )[0]
            assert_eq(row["id"], 42)
            assert_eq(row["text"], "DEFAULT '\\ \0é")
            assert_eq(row["empty"], None)
            assert isinstance(row["clock"], str) and row["clock"].endswith("000Z")


@test(mark="medium")
async def actual_old_default_mismatch_refuses_load_and_typed_preparation() -> None:
    """An actual old false-completion package is refused without rewriting its identity."""
    root = Path(__file__).parent / "fixtures"
    valid = (root / "column-coverage" / "valid-old.json").read_text()
    good = m.Package.load(valid)
    assert_eq(good.dump(), valid)
    invalid = (root / "default-claims" / "invalid-old.json").read_text()
    with assert_raises(m.PackageError) as error:
        m.Package.load(invalid)
    assert "construction default" in str(error.exception)
    old = m.Package.model_validate_json(invalid)
    assert_eq(
        old.digest, "69cda581f7e5221ee6e75dfdfedca110244c537d2c19abf7c57128063ea9506d"
    )
    with TemporaryDirectory() as directory:
        config = sqlite.Config(database=Path(directory) / "defaults.db")
        async with m.connect(config) as target:
            with assert_raises(m.PackageError) as error:
                await target.prepare(old)
            assert "construction default" in str(error.exception)
            assert_eq(await target.status(), ())
            assert_eq(await target.apply(await target.prepare(good)), "applied")
        async with (
            await sqlite.Database.initialize(config) as db,
            db.transaction() as tx,
        ):
            await tx.execute(sqlite.raw("INSERT INTO entries(id) VALUES(42)"))
            assert_eq(
                await tx.fetch_all(sqlite.raw("SELECT id,value FROM entries")),
                [{"id": 42, "value": 7}],
            )

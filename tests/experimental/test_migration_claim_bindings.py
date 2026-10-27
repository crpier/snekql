"""Frozen identifier claims must bind to the SQL fragments used for alterations."""

from pathlib import Path
from typing import Literal

from snektest import Param, assert_eq, assert_raises, test

from snekql.experimental import migrations as m
from tests.experimental.test_migration_nullability import NativeRequired, Required


@test(
    [
        Param[Literal["sqlite", "mariadb"]](value="sqlite", name="sqlite"),
        Param[Literal["sqlite", "mariadb"]](value="mariadb", name="mariadb"),
    ]
)
async def quoted_table_claim_cannot_redirect_later_alterations(
    backend: Literal["sqlite", "mariadb"],
) -> None:
    """Even an initially unused quoted name is executable authority on later routes."""
    draft = m.generate(
        "001", [Required] if backend == "sqlite" else [NativeRequired], backend=backend
    )
    original = draft.target.tables[0]
    table = original.model_copy(
        update={"quoted_name": '"unowned"' if backend == "sqlite" else "`unowned`"}
    )
    edited = draft.model_copy(
        update={
            "target": draft.target.model_copy(update={"tables": (table,)}),
            "operations": (m.CreateTable(table=table),),
        }
    )
    with assert_raises(m.PackageError) as error:
        m.compile(edited)
    assert "identifier claim" in str(error.exception)


@test([Param(value="sqlite", name="sqlite"), Param(value="mariadb", name="mariadb")])
async def column_claim_cannot_name_a_different_alteration_target(backend: str) -> None:
    """Column metadata and the executable definition must name the same column."""
    family: Literal["sqlite", "mariadb"] = (
        "sqlite" if backend == "sqlite" else "mariadb"
    )
    draft = m.generate(
        "001", [Required] if family == "sqlite" else [NativeRequired], backend=family
    )
    table = draft.target.tables[0]
    column = table.columns[1].model_copy(update={"name": "unowned"})
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
    assert "column identifier claim" in str(error.exception)


@test([Param(value="tables", name="tables"), Param(value="columns", name="columns")])
async def duplicate_recorded_identifiers_cannot_collapse_into_one_claim(
    scope: str,
) -> None:
    """Dictionary projection must not silently discard duplicate ownership claims."""
    draft = m.generate("001", [Required], backend="sqlite")
    table = draft.target.tables[0]
    if scope == "columns":
        table = table.model_copy(update={"columns": (*table.columns, table.columns[1])})
        tables = (table,)
    else:
        tables = (table, table)
    with assert_raises(m.PackageError) as error:
        m.compile(
            draft.model_copy(
                update={
                    "target": draft.target.model_copy(update={"tables": tables}),
                    "operations": (m.CreateTable(table=table),),
                }
            )
        )
    assert "ambiguous recorded" in str(error.exception)


@test(
    [
        Param(value=scope, name=scope)
        for scope in ("before", "intermediate", "add_column", "change_default")
    ]
)
async def identifier_binding_applies_outside_the_final_snapshot(scope: str) -> None:
    """Relinquishment and intermediate operations cannot erase executable name checks."""
    first = m.compile(m.generate("001", [Required], backend="sqlite"))
    table = first.target.tables[0]
    bad_table = table.model_copy(update={"quoted_name": '"unowned"'})
    empty = m.State(backend="sqlite")
    if scope == "before":
        draft = m.Draft(
            revision="002",
            predecessor=first.digest,
            before=first.target.model_copy(update={"tables": (bad_table,)}),
            target=empty,
            operations=(m.RelinquishTable(table_name=table.name),),
        )
    elif scope == "intermediate":
        draft = m.Draft(
            revision="001",
            predecessor=None,
            before=empty,
            target=empty,
            operations=(
                m.CreateTable(table=bad_table),
                m.RelinquishTable(table_name=table.name),
            ),
        )
    else:
        column = table.columns[1].model_copy(update={"name": "unowned"})
        operation = (
            m.AddColumn(table_name=table.name, column=column)
            if scope == "add_column"
            else m.ChangeDefault(table_name=table.name, column=column)
        )
        draft = m.Draft(
            revision="002",
            predecessor=first.digest,
            before=first.target,
            target=empty,
            operations=(operation, m.RelinquishTable(table_name=table.name)),
        )
    with assert_raises(m.PackageError) as error:
        m.compile(draft)
    assert "identifier claim" in str(error.exception)


@test(
    [
        Param(value=name, name=str(i))
        for i, name in enumerate(
            (
                '"entries"; DROP TABLE unowned',
                '"entries" -- suffix',
                "unquoted",
                '"unterminated',
                "'entries'",
            )
        )
    ]
)
async def quoted_name_is_a_single_complete_identifier_fragment(name: str) -> None:
    """Executable tails, comments, strings and bare names are not quoted-name claims."""
    draft = m.generate("001", [Required], backend="sqlite")
    table = draft.target.tables[0].model_copy(update={"quoted_name": name})
    with assert_raises(m.PackageError) as error:
        m.compile(
            draft.model_copy(
                update={
                    "target": draft.target.model_copy(update={"tables": (table,)}),
                    "operations": (m.CreateTable(table=table),),
                }
            )
        )
    assert "identifier claim" in str(error.exception)


@test([Param(value="tables", name="tables"), Param(value="columns", name="columns")])
async def ascii_case_collision_is_not_an_independent_ownership_claim(
    scope: str,
) -> None:
    """Conservatively refuse native deployment-dependent and SQLite case collisions."""
    draft = m.generate("001", [Required], backend="sqlite")
    table = draft.target.tables[0]
    if scope == "tables":
        alias = table.model_copy(update={"name": "ENTRIES", "quoted_name": '"ENTRIES"'})
        tables = (table, alias)
        operations = (m.CreateTable(table=table), m.CreateTable(table=alias))
    else:
        alias = table.columns[1].model_copy(
            update={"name": "VALUE", "definition": '"VALUE" INTEGER NOT NULL'}
        )
        table = table.model_copy(update={"columns": (*table.columns, alias)})
        tables = (table,)
        operations = (m.CreateTable(table=table),)
    with assert_raises(m.PackageError) as error:
        m.compile(
            draft.model_copy(
                update={
                    "target": draft.target.model_copy(update={"tables": tables}),
                    "operations": operations,
                }
            )
        )
    assert "ambiguous recorded" in str(error.exception)


@test()
async def archived_identifier_claim_artifacts_are_preserved_or_explicitly_refused() -> (
    None
):
    """Actual old writer acceptance cannot bypass new load-time authority checks."""
    root = Path(__file__).parent / "fixtures" / "identifier-claims"
    valid = (root / "valid.json").read_text()
    package = m.Package.load(valid)
    assert_eq(
        package.digest,
        "d8bf43b6df3a741ec93fe3cd3df74b2fc906b15f14f5700aa08414a8d2f9e6a5",
    )
    assert_eq(package.dump(), valid)
    with assert_raises(m.PackageError) as error:
        m.Package.load((root / "mismatched-quoted-name.json").read_text())
    assert "table identifier claim" in str(error.exception)

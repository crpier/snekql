"""Managed inline key clauses must agree before construction effects."""

from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Literal

from snektest import Param, assert_eq, assert_raises, load_fixture, test

from snekql import sqlite
from snekql.experimental import migrations as m
from tests.experimental.test_migration_nullability import NativeRequired, Required
from tests.experimental.test_migration_targets import provide_package_server


@test(
    [
        Param[Literal["sqlite", "mariadb"]](value="sqlite", name="sqlite"),
        Param[Literal["sqlite", "mariadb"]](value="mariadb", name="mariadb"),
    ],
    mark="fast",
)
async def construction_cannot_erase_a_recorded_inline_primary_key(
    backend: Literal["sqlite", "mariadb"],
) -> None:
    """Matching physical types/defaults cannot certify a missing key clause."""
    draft = m.generate(
        "001", [Required] if backend == "sqlite" else [NativeRequired], backend=backend
    )
    table = draft.target.tables[0]
    table = table.model_copy(update={"sql": table.sql.replace(" PRIMARY KEY", "")})
    with assert_raises(m.PackageError) as error:
        m.compile(
            draft.model_copy(
                update={
                    "target": draft.target.model_copy(update={"tables": (table,)}),
                    "operations": (m.CreateTable(table=table),),
                }
            )
        )
    assert "inline primary key" in str(error.exception)


@test(
    [
        Param(value=suffix, name=name)
        for name, suffix in (
            ("direction", " DESC"),
            ("conflict", " ON CONFLICT REPLACE"),
            ("identity", " AUTOINCREMENT"),
        )
    ],
    mark="fast",
)
async def inline_key_policy_cannot_change_behind_a_matching_marker(suffix: str) -> None:
    """A key marker alone cannot certify SQLite ordering, conflict or identity policy."""
    draft = m.generate("001", [Required], backend="sqlite")
    table = draft.target.tables[0]
    table = table.model_copy(
        update={"sql": table.sql.replace("PRIMARY KEY", "PRIMARY KEY" + suffix)}
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
    assert "inline primary key" in str(error.exception)


@test(
    [
        Param[Literal["sqlite", "mariadb"]](value="sqlite", name="sqlite"),
        Param[Literal["sqlite", "mariadb"]](value="mariadb", name="mariadb"),
    ],
    mark="fast",
)
async def construction_cannot_add_a_hidden_inline_key(
    backend: Literal["sqlite", "mariadb"],
) -> None:
    """Negative inline claims on managed columns bind in the opposite direction too."""
    draft = m.generate(
        "001", [Required] if backend == "sqlite" else [NativeRequired], backend=backend
    )
    table = draft.target.tables[0]
    column = table.columns[0].model_copy(
        update={"definition": table.columns[0].definition.replace(" PRIMARY KEY", "")}
    )
    table = table.model_copy(update={"columns": (column, table.columns[1])})
    with assert_raises(m.PackageError) as error:
        m.compile(
            draft.model_copy(
                update={
                    "target": draft.target.model_copy(update={"tables": (table,)}),
                    "operations": (m.CreateTable(table=table),),
                }
            )
        )
    assert "inline primary key" in str(error.exception)


@test(
    [Param(value=scope, name=scope) for scope in ("before", "create", "adopt")],
    mark="fast",
)
async def relinquishment_cannot_hide_inline_key_claims(scope: str) -> None:
    """Before and intermediate payloads retain positive key authority after handoff."""
    first = m.compile(m.generate("001", [Required], backend="sqlite"))
    table = first.target.tables[0].model_copy(
        update={"sql": first.target.tables[0].sql.replace(" PRIMARY KEY", "")}
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
    assert "inline primary key" in str(error.exception)


@test(
    [
        Param(value=policy, name=policy)
        for policy in ("asc", "desc", "ignore", "identity")
    ],
    mark="medium",
)
async def matching_sqlite_inline_policies_execute_without_erasing_behavior(
    policy: str,
) -> None:
    """Direction, duplicate-write handling and never-reuse identity remain distinct."""
    draft = m.generate("001", [Required], backend="sqlite")
    table = draft.target.tables[0]
    suffix = {
        "asc": " ASC ON CONFLICT ABORT",
        "desc": " DESC",
        "ignore": " ON CONFLICT IGNORE",
        "identity": " AUTOINCREMENT",
    }[policy]
    column = table.columns[0]
    declared = (
        column
        if policy == "asc"
        else column.model_copy(update={"definition": column.definition + suffix})
    )
    table = table.model_copy(
        update={
            "columns": (declared, table.columns[1]),
            "sql": table.sql.replace(column.definition, column.definition + suffix),
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
        config = sqlite.Config(database=Path(directory) / "keys.db")
        async with m.connect(config) as target:
            assert_eq(await target.apply(await target.prepare(package)), "applied")
        async with (
            await sqlite.Database.initialize(config) as db,
            db.transaction() as tx,
        ):
            await tx.execute(sqlite.raw("INSERT INTO entries(id) VALUES(42)"))
            if policy == "ignore":
                await tx.execute(
                    sqlite.raw("INSERT INTO entries(id,value) VALUES(42,99)")
                )
            if policy == "identity":
                await tx.execute(sqlite.raw("DELETE FROM entries"))
            if policy in {"identity", "asc"}:
                await tx.execute(sqlite.raw("INSERT INTO entries DEFAULT VALUES"))
            rows = await tx.fetch_all(
                sqlite.raw(
                    "SELECT rowid AS physical,id,value FROM entries ORDER BY rowid"
                )
            )
            expected = {
                "asc": [
                    {"physical": 42, "id": 42, "value": 7},
                    {"physical": 43, "id": 43, "value": 7},
                ],
                "desc": [{"physical": 1, "id": 42, "value": 7}],
                "ignore": [{"physical": 42, "id": 42, "value": 7}],
                "identity": [{"physical": 43, "id": 43, "value": 7}],
            }[policy]
            assert_eq(rows, expected)


@test(mark="slow")
async def native_catalog_key_drift_still_refuses_a_valid_followup_package() -> None:
    """Compilation cannot replace runtime proof of an independently changed physical key."""
    server = await load_fixture(provide_package_server())
    first = m.compile(m.generate("001", [NativeRequired], backend="mariadb"))
    second = m.compile(
        m.Draft(
            revision="002",
            predecessor=first.digest,
            before=first.target,
            target=first.target,
            operations=(),
        )
    )
    async with m.connect(server.config()) as target:
        await target.apply(await target.prepare(first, schema_writers_excluded=True))
    await server.run_sql(
        "ALTER TABLE entries DROP PRIMARY KEY, ADD UNIQUE INDEX other_identity(id)"
    )
    async with m.connect(server.config()) as target:
        with assert_raises(m.PackageError) as error:
            await target.prepare(second, schema_writers_excluded=True)
        assert "catalog differs from the last accepted execution" in str(
            error.exception
        )
        assert_eq(len(await target.status()), 1)


@test(mark="medium")
async def actual_old_missing_key_package_refuses_loading_and_typed_preparation() -> (
    None
):
    """An old completed contradiction refuses before SQL without changing valid identities."""
    root = Path(__file__).parent / "fixtures"
    valid = (root / "column-coverage" / "valid-old.json").read_text()
    good = m.Package.load(valid)
    assert_eq(good.dump(), valid)
    invalid = (root / "inline-keys" / "invalid-old.json").read_text()
    old = m.Package.model_validate_json(invalid)
    assert_eq(
        old.digest, "cea471362c0fa3142565f02c5b2cb97811806ac9a3eb95a5f2e46d2b358c8847"
    )
    with assert_raises(m.PackageError) as error:
        m.Package.load(invalid)
    assert "inline primary key" in str(error.exception)
    with TemporaryDirectory() as directory:
        config = sqlite.Config(database=Path(directory) / "keys.db")
        async with m.connect(config) as target:
            with assert_raises(m.PackageError) as error:
                await target.prepare(old)
            assert "inline primary key" in str(error.exception)
            assert_eq(await target.status(), ())
            await target.apply(await target.prepare(good))
        async with (
            await sqlite.Database.initialize(config) as db,
            db.transaction() as tx,
        ):
            await tx.execute(sqlite.raw("INSERT INTO entries(id) VALUES(42)"))
            assert_eq(
                await tx.fetch_all(sqlite.raw("SELECT id,value FROM entries")),
                [{"id": 42, "value": 7}],
            )


@test(
    [
        Param(value=case, name=str(i))
        for i, case in enumerate(
            (
                ("sqlite", "PRIMARY KEY PRIMARY KEY"),
                ("sqlite", "PRIMARY KEY SPATIAL"),
                ("sqlite", "PRIMARY KEY ON CONFLICT MYSTERY"),
                ("mariadb", "PRIMARY KEY DESC"),
            )
        )
    ],
    mark="fast",
)
async def unsupported_key_clauses_are_not_proven_by_matching_bytes(
    case: tuple[str, str],
) -> None:
    """Finite clause admission cannot be bypassed by equal unsupported definitions."""
    name, clause = case
    backend: Literal["sqlite", "mariadb"] = "sqlite" if name == "sqlite" else "mariadb"
    draft = m.generate(
        "001", [Required] if backend == "sqlite" else [NativeRequired], backend=backend
    )
    table = draft.target.tables[0]
    old = table.columns[0]
    column = old.model_copy(
        update={"definition": old.definition.replace("PRIMARY KEY", clause)}
    )
    table = table.model_copy(
        update={
            "columns": (column, table.columns[1]),
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
    assert "inline primary key" in str(error.exception)


@test(
    [
        Param[Literal["sqlite", "mariadb"]](value="sqlite", name="sqlite"),
        Param[Literal["sqlite", "mariadb"]](value="mariadb", name="mariadb"),
    ],
    mark="fast",
)
async def quoted_literal_and_nested_key_words_do_not_manufacture_inline_claims(
    backend: Literal["sqlite", "mariadb"],
) -> None:
    """Identifier, constant and nested-expression roles are not top-level key clauses."""
    kind = "TEXT" if backend == "sqlite" else "VARCHAR(64)"
    definition = f"`primary` {kind} NOT NULL DEFAULT 'PRIMARY KEY DESC AUTOINCREMENT' CHECK (`primary` <> 'KEY')"
    column = m.ColumnState(
        name="primary",
        definition=definition,
        nullable=False,
        storage="TEXT",
        query_type="str",
    )
    table = m.TableState(
        name="words",
        quoted_name="`words`",
        columns=(column,),
        sql=f"CREATE TABLE words ({definition})"
        + (" STRICT" if backend == "sqlite" else " ENGINE=InnoDB"),
    )
    draft = m.Draft(
        revision="001",
        predecessor=None,
        before=m.State(backend=backend),
        target=m.State(backend=backend, tables=(table,)),
        operations=(m.CreateTable(table=table),),
    )
    package = m.compile(draft)
    assert_eq(m.Package.load(package.dump()).digest, package.digest)

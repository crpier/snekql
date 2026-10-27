"""Inline primary-key labels bind independently of key behavior/nullability."""

from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Literal

from snektest import Param, assert_eq, assert_raises, test

from snekql import sqlite
from snekql.errors import ExecutionError
from snekql.experimental import migrations as m
from tests.experimental.test_migration_nullability import NativeRequired, Required


def _draft(
    backend: Literal["sqlite", "mariadb"], declaration: str, construction: str
) -> m.Draft:
    """Review the id key independently from its executable construction clause."""
    draft = m.generate(
        "001", [Required] if backend == "sqlite" else [NativeRequired], backend=backend
    )
    table = draft.target.tables[0]
    old = table.columns[0]
    column = old.model_copy(
        update={"definition": old.definition.replace("PRIMARY KEY", declaration)}
    )
    table = table.model_copy(
        update={
            "columns": (column, table.columns[1]),
            "sql": table.sql.replace(
                old.definition, old.definition.replace("PRIMARY KEY", construction)
            ),
        }
    )
    return draft.model_copy(
        update={
            "target": draft.target.model_copy(update={"tables": (table,)}),
            "operations": (m.CreateTable(table=table),),
        }
    )


@test(mark="fast")
async def matching_key_behavior_cannot_rename_an_explicit_primary_key_label() -> None:
    """Equal key direction/conflict/identity/nullability is not label agreement."""
    with assert_raises(m.PackageError) as error:
        m.compile(
            _draft(
                "sqlite",
                'CONSTRAINT "recorded" PRIMARY KEY',
                'CONSTRAINT "other" PRIMARY KEY',
            )
        )
    assert "inline primary key" in str(error.exception)


@test(mark="fast")
async def named_native_inline_key_needs_an_adapter_even_with_matching_bytes() -> None:
    """Do not infer how a native server stores/ignores an explicit inline PK symbol."""
    clause = 'CONSTRAINT "recorded" PRIMARY KEY'
    with assert_raises(m.PackageError) as error:
        m.compile(_draft("mariadb", clause, clause))
    assert "inline primary key" in str(error.exception)


@test(mark="fast")
async def string_role_primary_key_names_require_an_adapter_even_when_equal() -> None:
    """The bounded key-name language does not infer SQLite's permissive string roles."""
    clause = "CONSTRAINT 'recorded' PRIMARY KEY"
    with assert_raises(m.PackageError) as error:
        m.compile(_draft("sqlite", clause, clause))
    assert "inline primary key" in str(error.exception)


@test(
    [
        Param(value=pair, name=str(i))
        for i, pair in enumerate(
            (
                ("PRIMARY KEY", 'CONSTRAINT "recorded" PRIMARY KEY'),
                ('CONSTRAINT "recorded" PRIMARY KEY', "PRIMARY KEY"),
                (
                    'CONSTRAINT "Recorded" PRIMARY KEY',
                    'CONSTRAINT "recorded" PRIMARY KEY',
                ),
            )
        )
    ],
    mark="fast",
)
async def explicit_key_label_presence_and_case_do_not_fold(
    pair: tuple[str, str],
) -> None:
    """Equal physical key behavior does not erase/add/fold recorded identity."""
    with assert_raises(m.PackageError) as error:
        m.compile(_draft("sqlite", *pair))
    assert "inline primary key" in str(error.exception)


@test(
    [
        Param(value=pair, name=str(i))
        for i, pair in enumerate(
            (
                (
                    'CONSTRAINT "recorded" PRIMARY KEY',
                    "CONSTRAINT [recorded] primary key asc on conflict abort",
                ),
                ('CONSTRAINT "quo""te" PRIMARY KEY', 'CONSTRAINT `quo"te` PRIMARY KEY'),
                (
                    'CONSTRAINT "PRIMARY KEY" PRIMARY KEY',
                    "CONSTRAINT [PRIMARY KEY] PRIMARY KEY",
                ),
            )
        )
    ],
    mark="fast",
)
async def known_label_quotes_and_default_key_policy_normalize(
    pair: tuple[str, str],
) -> None:
    """Decoded identifiers agree without interpreting quoted keywords as extra keys."""
    package = m.compile(_draft("sqlite", *pair))
    assert_eq(m.Package.load(package.dump()).digest, package.digest)


@test(
    [Param(value=scope, name=scope) for scope in ("before", "create", "adopt")],
    mark="fast",
)
async def handoff_cannot_hide_a_key_label_contradiction(scope: str) -> None:
    """Before/intermediate payload claims survive the empty final owned state."""
    table = _draft(
        "sqlite", 'CONSTRAINT "recorded" PRIMARY KEY', 'CONSTRAINT "other" PRIMARY KEY'
    ).target.tables[0]
    empty = m.State(backend="sqlite")
    if scope == "before":
        draft = m.Draft(
            revision="002",
            predecessor="previous",
            before=m.State(backend="sqlite", tables=(table,)),
            target=empty,
            operations=(m.RelinquishTable(table_name="entries"),),
        )
    else:
        operation = (
            m.CreateTable(table=table)
            if scope == "create"
            else m.AdoptTable(table=table)
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
    assert "inline primary key" in str(error.exception)


@test(mark="fast")
async def a_following_constraint_label_cannot_mask_the_key_label() -> None:
    """NOT NULL and UNIQUE labels belong to their own clauses, not the preceding PK."""
    tail = ' CONSTRAINT "required" NOT NULL ON CONFLICT IGNORE CONSTRAINT "distinct" UNIQUE'
    with assert_raises(m.PackageError) as error:
        m.compile(
            _draft(
                "sqlite",
                'CONSTRAINT "recorded" PRIMARY KEY' + tail,
                'CONSTRAINT "other" PRIMARY KEY' + tail,
            )
        )
    assert "inline primary key" in str(error.exception)


@test([Param(value=kind, name=kind) for kind in ("add", "default")], mark="fast")
async def standalone_payloads_admit_key_label_roles_without_final_ownership(
    kind: str,
) -> None:
    """Equal unsupported label roles cannot hide in operations before relinquishment."""
    first = m.compile(_draft("sqlite", "PRIMARY KEY", "PRIMARY KEY"))
    if kind == "add":
        column = m.ColumnState(
            name="extra",
            definition="`extra` INTEGER CONSTRAINT 'recorded' PRIMARY KEY",
            nullable=True,
            storage="INTEGER",
            query_type=None,
        )
        operation = m.AddColumn(table_name="entries", column=column)
    else:
        column = (
            first.target.tables[0]
            .columns[0]
            .model_copy(
                update={
                    "definition": "`id` INTEGER CONSTRAINT 'recorded' PRIMARY KEY DEFAULT 8"
                }
            )
        )
        operation = m.ChangeDefault(table_name="entries", column=column)
    draft = m.Draft(
        revision="002",
        predecessor=first.digest,
        before=first.target,
        target=m.State(backend="sqlite"),
        operations=(operation, m.RelinquishTable(table_name="entries")),
    )
    with assert_raises(m.PackageError) as error:
        m.compile(draft)
    assert "inline primary key" in str(error.exception)


@test(
    [Param(value=operation, name=operation) for operation in ("check", "index")],
    mark="fast",
)
async def an_inline_primary_key_symbol_does_not_authorize_other_object_removal(
    operation: str,
) -> None:
    """Label recording is not CHECK/index namespace ownership or destructive authority."""
    clause = 'CONSTRAINT "recorded" PRIMARY KEY'
    first = m.compile(_draft("sqlite", clause, clause))
    op = (
        m.DropCheck(table_name="entries", check_name="recorded")
        if operation == "check"
        else m.DropIndex(table_name="entries", index_name="recorded")
    )
    draft = m.Draft(
        revision="002",
        predecessor=first.digest,
        before=first.target,
        target=first.target,
        operations=(op,),
    )
    with assert_raises(m.PackageError):
        m.compile(draft)


@test(
    [
        Param(value=suffix, name=str(i))
        for i, suffix in enumerate(("", " DESC", " AUTOINCREMENT"))
    ],
    mark="medium",
)
async def named_sqlite_keys_preserve_default7_and_primary_key_enforcement(
    suffix: str,
) -> None:
    """Label admission preserves rowid/direction/identity policy, not just compilation."""
    clause = 'CONSTRAINT "recorded" PRIMARY KEY' + suffix
    package = m.Package.load(m.compile(_draft("sqlite", clause, clause)).dump())
    with TemporaryDirectory() as directory:
        config = sqlite.Config(database=Path(directory) / "keys.db")
        async with m.connect(config) as target:
            await target.apply(await target.prepare(package))
        async with await sqlite.Database.initialize(config) as db:
            async with db.transaction() as tx:
                await tx.execute(sqlite.raw("INSERT INTO entries(id) VALUES(42)"))
            with assert_raises(ExecutionError):
                async with db.transaction() as tx:
                    await tx.execute(sqlite.raw("INSERT INTO entries(id) VALUES(42)"))
            async with db.transaction() as tx:
                assert_eq(
                    await tx.fetch_all(sqlite.raw("SELECT id,value FROM entries")),
                    [{"id": 42, "value": 7}],
                )
                if suffix == " AUTOINCREMENT":
                    await tx.execute(sqlite.raw("DELETE FROM entries"))
                    await tx.execute(sqlite.raw("INSERT INTO entries DEFAULT VALUES"))
                    assert_eq(
                        await tx.fetch_all(sqlite.raw("SELECT id,value FROM entries")),
                        [{"id": 43, "value": 7}],
                    )


@test(mark="medium")
async def old_key_label_contradiction_refuses_without_converting_valid_identity() -> (
    None
):
    """A real archived format2 identity contradiction refuses before effects/history."""
    root = Path(__file__).parent / "fixtures" / "inline-key-labels"
    invalid = (root / "invalid-old.json").read_text()
    bad = m.Package.model_validate_json(invalid)
    assert_eq(
        bad.digest, "c8bce3f55f501b4be218d20dbb83ab6e56cacdda0edfaea963dec3630329da7f"
    )
    with assert_raises(m.PackageError) as error:
        m.Package.load(invalid)
    assert "inline primary key" in str(error.exception)
    valid = (root / "valid-old.json").read_text()
    good = m.Package.load(valid)
    assert_eq(
        good.digest, "8233d25f2c8eb2bd3d75ca2abcbadc3736680148f781060b47e87e30bedc0d17"
    )
    assert_eq(good.dump(), valid)
    with TemporaryDirectory() as directory:
        config = sqlite.Config(database=Path(directory) / "keys.db")
        async with m.connect(config) as target:
            with assert_raises(m.PackageError) as error:
                await target.prepare(bad)
            assert "inline primary key" in str(error.exception)
            assert_eq(await target.status(), ())
        async with (
            await sqlite.Database.initialize(config) as db,
            db.transaction() as tx,
        ):
            assert_eq(
                await tx.fetch_all(
                    sqlite.raw("SELECT name FROM sqlite_schema WHERE type='table'")
                ),
                [],
            )
        async with m.connect(config) as target:
            await target.apply(await target.prepare(good))
        async with await sqlite.Database.initialize(config) as db:
            async with db.transaction() as tx:
                await tx.execute(sqlite.raw("INSERT INTO entries(id) VALUES(42)"))
                assert_eq(
                    await tx.fetch_all(sqlite.raw("SELECT id,value FROM entries")),
                    [{"id": 42, "value": 7}],
                )
            with assert_raises(ExecutionError):
                async with db.transaction() as tx:
                    await tx.execute(sqlite.raw("INSERT INTO entries(id) VALUES(42)"))


@test(mark="fast")
async def an_extra_sql_named_key_does_not_manufacture_recorded_columns_or_indexes() -> (
    None
):
    """One-way extra construction facts do not create owned/destructive authority."""
    draft = _draft("sqlite", "PRIMARY KEY", "PRIMARY KEY")
    table = draft.target.tables[0]
    old = table.columns[0]
    column = old.model_copy(
        update={
            "definition": old.definition.replace(" PRIMARY KEY", ""),
            "nullable": True,
            "query_type": "int | None",
        }
    )
    table = table.model_copy(
        update={
            "columns": (column, table.columns[1]),
            "sql": table.sql.replace(old.definition, column.definition).replace(
                ") STRICT",
                ', "extra" INTEGER CONSTRAINT "extra_key" PRIMARY KEY) STRICT',
            ),
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
    assert_eq(tuple(c.name for c in package.target.tables[0].columns), ("id", "value"))
    assert_eq(package.target.tables[0].indexes, ())

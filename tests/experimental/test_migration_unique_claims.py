"""Inline UNIQUE declaration binding through frozen public migration seams."""

from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Literal

from snektest import Param, assert_eq, assert_raises, load_fixture, test

from snekql import mariadb, sqlite
from snekql.errors import ExecutionError
from snekql.experimental import migrations as m
from tests.experimental.test_migration_nullability import NativeRequired, Required
from tests.experimental.test_migration_targets import provide_package_server


def _draft(
    backend: Literal["sqlite", "mariadb"], declaration: str, construction: str
) -> m.Draft:
    """Review one column's suffix independently from its executable declaration."""
    draft = m.generate(
        "001", [Required] if backend == "sqlite" else [NativeRequired], backend=backend
    )
    table = draft.target.tables[0]
    old = table.columns[1]
    column = old.model_copy(update={"definition": old.definition + declaration})
    table = table.model_copy(
        update={
            "columns": (table.columns[0], column),
            "sql": table.sql.replace(old.definition, old.definition + construction),
        }
    )
    return draft.model_copy(
        update={
            "target": draft.target.model_copy(update={"tables": (table,)}),
            "operations": (m.CreateTable(table=table),),
        }
    )


@test(
    [
        Param[Literal["sqlite", "mariadb"]](value="sqlite", name="sqlite"),
        Param[Literal["sqlite", "mariadb"]](value="mariadb", name="mariadb"),
    ],
    mark="fast",
)
async def construction_cannot_erase_a_recorded_inline_unique(
    backend: Literal["sqlite", "mariadb"],
) -> None:
    """Type/default/nullability agreement is not a uniqueness declaration."""
    with assert_raises(m.PackageError) as error:
        m.compile(_draft(backend, " UNIQUE", ""))
    assert "inline UNIQUE" in str(error.exception)


@test(mark="fast")
async def matching_unique_markers_cannot_hide_a_conflict_policy_change() -> None:
    """IGNORE and REPLACE are not the default ABORT write policy."""
    with assert_raises(m.PackageError) as error:
        m.compile(
            _draft(
                "sqlite", " UNIQUE ON CONFLICT IGNORE", " UNIQUE ON CONFLICT REPLACE"
            )
        )
    assert "inline UNIQUE" in str(error.exception)


@test(mark="fast")
async def matching_unique_policies_cannot_rename_explicit_sqlite_constraints() -> None:
    """A reviewed constraint label is distinct from keyword case/quoting cosmetics."""
    with assert_raises(m.PackageError) as error:
        m.compile(
            _draft(
                "sqlite", ' CONSTRAINT "chosen" UNIQUE', ' CONSTRAINT "other" UNIQUE'
            )
        )
    assert "inline UNIQUE" in str(error.exception)


@test(mark="fast")
async def native_named_inline_unique_requires_an_adapter_even_with_matching_bytes() -> (
    None
):
    """Do not infer cross-version native inline constraint-name syntax/identity support."""
    draft = _draft("mariadb", " CONSTRAINT picked UNIQUE", " CONSTRAINT picked UNIQUE")
    table = draft.target.tables[0]
    table = table.model_copy(
        update={
            "columns": tuple(
                c.model_copy(
                    update={"definition": c.definition.replace(" DEFAULT 7", "")}
                )
                for c in table.columns
            ),
            "sql": table.sql.replace(" DEFAULT 7", ""),
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
    assert "inline UNIQUE" in str(error.exception)


@test(
    [
        Param[Literal["sqlite", "mariadb"]](value="sqlite", name="sqlite"),
        Param[Literal["sqlite", "mariadb"]](value="mariadb", name="mariadb"),
    ],
    mark="fast",
)
async def construction_cannot_add_a_hidden_inline_unique(
    backend: Literal["sqlite", "mariadb"],
) -> None:
    """Absence binds too; stronger construction is not silently substituted."""
    with assert_raises(m.PackageError) as error:
        m.compile(_draft(backend, "", " UNIQUE"))
    assert "inline UNIQUE" in str(error.exception)


@test(
    [Param(value=scope, name=scope) for scope in ("before", "create", "adopt")],
    mark="fast",
)
async def relinquishment_cannot_hide_unique_claims(scope: str) -> None:
    """Before/intermediate CREATE/ADOPT claims remain meaningful after handoff."""
    table = _draft("sqlite", " UNIQUE", "").target.tables[0]
    empty = m.State(backend="sqlite")
    if scope == "before":
        draft = m.Draft(
            revision="002",
            predecessor="prior",
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
    assert "inline UNIQUE" in str(error.exception)


@test(
    [
        Param(value=suffix, name=str(i))
        for i, suffix in enumerate(
            (
                " UNIQUE UNIQUE",
                " UNIQUE DESC",
                " UNIQUE KEY",
                " UNIQUE ON CONFLICT MYSTERY",
                " CONSTRAINT 'picked' UNIQUE",
            )
        )
    ],
    mark="fast",
)
async def matching_unsupported_unique_clauses_require_adapters(suffix: str) -> None:
    """Byte equality is not admission of unknown/multiple clauses or identifier roles."""
    with assert_raises(m.PackageError) as error:
        m.compile(_draft("sqlite", suffix, suffix))
    assert "inline UNIQUE" in str(error.exception)


@test(
    [
        Param(value=policy, name=policy or "implicit")
        for policy in ("", "ABORT", "FAIL", "ROLLBACK", "IGNORE", "REPLACE")
    ],
    mark="medium",
)
async def sqlite_unique_policy_keeps_its_duplicate_write_behavior(policy: str) -> None:
    """Ignored/replaced rows differ; rejecting writes leave the committed original."""
    suffix = ' CONSTRAINT "chosen" UNIQUE' + (
        f" ON CONFLICT {policy}" if policy else ""
    )
    package = m.Package.load(m.compile(_draft("sqlite", suffix, suffix)).dump())
    with TemporaryDirectory() as directory:
        config = sqlite.Config(database=Path(directory) / "unique.db")
        async with m.connect(config) as target:
            await target.apply(await target.prepare(package))
        async with await sqlite.Database.initialize(config) as db:
            async with db.transaction() as tx:
                await tx.execute(sqlite.raw("INSERT INTO entries(id) VALUES(42)"))
            if policy in {"IGNORE", "REPLACE"}:
                async with db.transaction() as tx:
                    await tx.execute(sqlite.raw("INSERT INTO entries(id) VALUES(43)"))
            else:
                with assert_raises(ExecutionError):
                    async with db.transaction() as tx:
                        await tx.execute(
                            sqlite.raw("INSERT INTO entries(id) VALUES(43)")
                        )
            async with db.transaction() as tx:
                assert_eq(
                    await tx.fetch_all(sqlite.raw("SELECT id,value FROM entries")),
                    [{"id": 43 if policy == "REPLACE" else 42, "value": 7}],
                )


@test(mark="fast")
async def explicit_abort_and_constraint_quoting_are_known_cosmetics() -> None:
    """Normalize known omitted ABORT and identifier quote styles, not label spelling."""
    package = m.compile(
        _draft(
            "sqlite",
            ' CONSTRAINT "chosen" UNIQUE',
            " CONSTRAINT [chosen] unique on conflict abort",
        )
    )
    assert_eq(m.Package.load(package.dump()).digest, package.digest)


@test(mark="fast")
async def a_not_null_policy_is_not_the_unique_policy() -> None:
    """A following named NOT NULL constraint owns its own ON CONFLICT clause."""
    draft = _draft(
        "sqlite",
        ' UNIQUE CONSTRAINT "required" NOT NULL ON CONFLICT IGNORE',
        ' UNIQUE CONSTRAINT "required" NOT NULL ON CONFLICT IGNORE',
    )
    table = draft.target.tables[0]
    column = table.columns[1].model_copy(
        update={
            "definition": table.columns[1].definition.replace(
                " NOT NULL DEFAULT 7", " DEFAULT 7"
            )
        }
    )
    table = table.model_copy(
        update={
            "columns": (table.columns[0], column),
            "sql": table.sql.replace(" NOT NULL DEFAULT 7", " DEFAULT 7"),
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
    assert_eq(m.Package.load(package.dump()).digest, package.digest)


@test(mark="fast")
async def naming_inline_unique_does_not_authorize_dropping_an_index() -> None:
    """Constraint declaration identity does not create separately recorded DROP authority."""
    suffix = ' CONSTRAINT "chosen" UNIQUE'
    first = m.compile(_draft("sqlite", suffix, suffix))
    draft = m.Draft(
        revision="002",
        predecessor=first.digest,
        before=first.target,
        target=first.target,
        operations=(m.DropIndex(table_name="entries", index_name="chosen"),),
    )
    with assert_raises(m.PackageError):
        m.compile(draft)


@test(
    [
        Param[Literal["sqlite", "mariadb"]](value="sqlite", name="sqlite"),
        Param[Literal["sqlite", "mariadb"]](value="mariadb", name="mariadb"),
    ],
    mark="slow",
)
async def real_old_unique_contradiction_refuses_before_effects_while_valid_identity_deploys(
    backend: Literal["sqlite", "mariadb"],
) -> None:
    """Actual old false completions refuse; valid literal companions enforce uniqueness."""
    server = (
        await load_fixture(provide_package_server()) if backend == "mariadb" else None
    )
    root = Path(__file__).parent / "fixtures" / "inline-unique"
    text = (root / f"{backend}-invalid-old.json").read_text()
    old = m.Package.model_validate_json(text)
    assert_eq(
        old.digest,
        {
            "sqlite": "d0b038bead4f5d783ca968f56edb95e8c1c2278603c34a3135a1aa9954745c86",
            "mariadb": "1eeb8dd5ee03198d49bdc72b68297e74e487af38b0cbee6a23facb8e20b58d47",
        }[backend],
    )
    with assert_raises(m.PackageError) as error:
        m.Package.load(text)
    assert "inline UNIQUE" in str(error.exception)
    valid = (root / f"{backend}-valid-old.json").read_text()
    good = m.Package.load(valid)
    assert_eq(good.dump(), valid)
    assert_eq(
        good.digest,
        {
            "sqlite": "c9b3e42426d688176ecc048ec9e0bdbe365c72f9fdccaf90c101e8437d9175d4",
            "mariadb": "b526aa24f7cb4e4556fceb13833b5717704697674785204ca0351a030287a0a9",
        }[backend],
    )
    with TemporaryDirectory() as directory:
        config = (
            sqlite.Config(database=Path(directory) / "unique.db")
            if server is None
            else server.config()
        )
        async with m.connect(config) as target:
            with assert_raises(m.PackageError) as error:
                await target.prepare(old, schema_writers_excluded=backend == "mariadb")
            assert "inline UNIQUE" in str(error.exception)
            assert_eq(await target.status(), ())
        if isinstance(config, sqlite.Config):
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
        else:
            async with (
                await mariadb.Database.initialize(config) as db,
                db.transaction() as tx,
            ):
                assert_eq(await tx.fetch_all(mariadb.raw("SHOW FULL TABLES")), [])
        async with m.connect(config) as target:
            await target.apply(
                await target.prepare(good, schema_writers_excluded=backend == "mariadb")
            )
        if isinstance(config, sqlite.Config):
            async with await sqlite.Database.initialize(config) as db:
                async with db.transaction() as tx:
                    await tx.execute(sqlite.raw("INSERT INTO entries(id) VALUES(42)"))
                with assert_raises(ExecutionError):
                    async with db.transaction() as tx:
                        await tx.execute(
                            sqlite.raw("INSERT INTO entries(id) VALUES(43)")
                        )
                async with db.transaction() as tx:
                    assert_eq(
                        await tx.fetch_all(sqlite.raw("SELECT id,value FROM entries")),
                        [{"id": 42, "value": 7}],
                    )
        else:
            async with await mariadb.Database.initialize(config) as db:
                async with db.transaction() as tx:
                    await tx.execute(mariadb.raw("INSERT INTO entries(id) VALUES(42)"))
                with assert_raises(ExecutionError):
                    async with db.transaction() as tx:
                        await tx.execute(
                            mariadb.raw("INSERT INTO entries(id) VALUES(43)")
                        )
                async with db.transaction() as tx:
                    assert_eq(
                        await tx.fetch_all(mariadb.raw("SELECT id,value FROM entries")),
                        [{"id": 42, "value": 7}],
                    )


@test(mark="slow")
async def native_unique_key_spelling_preserves_canonical_inline_unique() -> None:
    """Native optional KEY is known syntax, not an inferred named/secondary-index ABI."""
    server = await load_fixture(provide_package_server())
    package = m.Package.load(
        m.compile(_draft("mariadb", " UNIQUE", " UNIQUE KEY")).dump()
    )
    async with m.connect(server.config()) as target:
        await target.apply(await target.prepare(package, schema_writers_excluded=True))
    async with await mariadb.Database.initialize(server.config()) as db:
        async with db.transaction() as tx:
            await tx.execute(mariadb.raw("INSERT INTO entries(id) VALUES(42)"))
        with assert_raises(ExecutionError):
            async with db.transaction() as tx:
                await tx.execute(mariadb.raw("INSERT INTO entries(id) VALUES(43)"))


@test(
    [
        Param[Literal["sqlite", "mariadb"]](value="sqlite", name="sqlite"),
        Param[Literal["sqlite", "mariadb"]](value="mariadb", name="mariadb"),
    ],
    mark="fast",
)
async def literal_identifier_and_nested_unique_mentions_are_not_clauses(
    backend: Literal["sqlite", "mariadb"],
) -> None:
    """Lexical roles survive keyword-looking identifiers/defaults/check expressions."""
    definition = (
        "`unique` "
        + ("TEXT" if backend == "sqlite" else "VARCHAR(128)")
        + " NOT NULL DEFAULT 'UNIQUE ON CONFLICT REPLACE' CHECK (`unique` <> 'UNIQUE')"
    )
    column = m.ColumnState(
        name="unique",
        definition=definition,
        nullable=False,
        storage="TEXT",
        query_type="str",
    )
    table = m.TableState(
        name="entries",
        quoted_name="`entries`",
        columns=(column,),
        sql=f"CREATE TABLE entries ({definition})"
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


@test(mark="medium")
async def nullable_unique_does_not_imply_not_null_or_one_null_only() -> None:
    """UNIQUE remains separate from key-implied requiredness; multiple NULLs survive."""
    draft = _draft("sqlite", " UNIQUE", " UNIQUE")
    table = draft.target.tables[0]
    column = table.columns[1].model_copy(
        update={
            "definition": table.columns[1].definition.replace(" NOT NULL", ""),
            "nullable": True,
            "query_type": "int | None",
        }
    )
    table = table.model_copy(
        update={
            "columns": (table.columns[0], column),
            "sql": table.sql.replace(" NOT NULL", ""),
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
    with TemporaryDirectory() as directory:
        config = sqlite.Config(database=Path(directory) / "unique.db")
        async with m.connect(config) as target:
            await target.apply(await target.prepare(package))
        async with (
            await sqlite.Database.initialize(config) as db,
            db.transaction() as tx,
        ):
            await tx.execute(
                sqlite.raw("INSERT INTO entries(id,value) VALUES(42,NULL),(43,NULL)")
            )
            assert_eq(
                await tx.fetch_all(sqlite.raw("SELECT value FROM entries ORDER BY id")),
                [{"value": None}, {"value": None}],
            )


@test([Param(value=kind, name=kind) for kind in ("add", "default")], mark="fast")
async def standalone_payload_unique_language_cannot_hide_after_relinquishment(
    kind: str,
) -> None:
    """Admit operation definitions independently of an empty final owned state."""
    first = m.compile(_draft("sqlite", " UNIQUE", " UNIQUE"))
    if kind == "add":
        column = m.ColumnState(
            name="extra",
            definition='"extra" INTEGER UNIQUE DESC',
            nullable=True,
            storage="INTEGER",
            query_type=None,
        )
        operation = m.AddColumn(table_name="entries", column=column)
    else:
        column = (
            first.target.tables[0]
            .columns[1]
            .model_copy(
                update={"definition": '"value" INTEGER NOT NULL DEFAULT 8 UNIQUE DESC'}
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
    assert "inline UNIQUE" in str(error.exception)


@test(mark="fast")
async def equivalent_looking_table_unique_does_not_satisfy_an_inline_claim() -> None:
    """Relocating a constraint may change identity/policy; no SQL-equivalence fallback."""
    draft = _draft("sqlite", " UNIQUE", "")
    table = draft.target.tables[0]
    table = table.model_copy(
        update={"sql": table.sql.replace(") STRICT", ', UNIQUE ("value")) STRICT')}
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
    assert "inline UNIQUE" in str(error.exception)


@test(
    [
        Param(value=pair, name=str(i))
        for i, pair in enumerate(
            (
                (" UNIQUE", ' CONSTRAINT "picked" UNIQUE'),
                (' CONSTRAINT "picked" UNIQUE', " UNIQUE"),
                (' CONSTRAINT "Picked" UNIQUE', ' CONSTRAINT "picked" UNIQUE'),
            )
        )
    ],
    mark="fast",
)
async def unique_constraint_identity_does_not_fold_or_disappear(
    pair: tuple[str, str],
) -> None:
    """Only identifier quoting is cosmetic; label presence/spelling remain recorded facts."""
    with assert_raises(m.PackageError) as error:
        m.compile(_draft("sqlite", *pair))
    assert "inline UNIQUE" in str(error.exception)


@test(mark="fast")
async def a_following_not_null_policy_cannot_mask_a_unique_policy_mismatch() -> None:
    """A last-ON-CONFLICT scan would miss this UNIQUE change behind the same NOT NULL."""
    draft = _draft(
        "sqlite",
        ' UNIQUE ON CONFLICT IGNORE CONSTRAINT "required" NOT NULL ON CONFLICT REPLACE',
        ' UNIQUE ON CONFLICT REPLACE CONSTRAINT "required" NOT NULL ON CONFLICT REPLACE',
    )
    table = draft.target.tables[0]
    column = table.columns[1].model_copy(
        update={
            "definition": table.columns[1].definition.replace(
                " NOT NULL DEFAULT 7", " DEFAULT 7"
            )
        }
    )
    table = table.model_copy(
        update={
            "columns": (table.columns[0], column),
            "sql": table.sql.replace(" NOT NULL DEFAULT 7", " DEFAULT 7"),
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
    assert "inline UNIQUE" in str(error.exception)


@test(mark="fast")
async def extra_unique_columns_do_not_become_recorded_column_claims() -> None:
    """One-way declaration coverage still does not manufacture managed columns/indexes."""
    draft = _draft("sqlite", "", "")
    table = draft.target.tables[0]
    table = table.model_copy(
        update={
            "sql": table.sql.replace(") STRICT", ', "extra" INTEGER UNIQUE) STRICT')
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

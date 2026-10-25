"""SQLite managed inline CHECK identity agrees with executable column construction."""

from pathlib import Path
from tempfile import TemporaryDirectory

import aiosqlite
from snektest import Param, assert_eq, assert_raises, test

from snekql import sqlite
from snekql.errors import ExecutionError
from snekql.experimental import migrations as m


def _draft(declaration: str, construction: str) -> m.Draft:
    """Review a required value/default independently of an inline CHECK clause."""
    prefix = "`value` INTEGER NOT NULL DEFAULT 7"
    column = m.ColumnState(
        name="value",
        definition=prefix + (" " + declaration if declaration else ""),
        nullable=False,
        storage="INTEGER",
        query_type="int",
    )
    table = m.TableState(
        name="entries",
        quoted_name="`entries`",
        columns=(column,),
        sql="CREATE TABLE `entries` ("
        + prefix
        + (" " + construction if construction else "")
        + ") STRICT",
    )
    return m.Draft(
        revision="001",
        predecessor=None,
        before=m.State(backend="sqlite"),
        target=m.State(backend="sqlite", tables=(table,)),
        operations=(m.CreateTable(table=table),),
    )


@test(mark="fast")
async def inline_check_cannot_disappear_from_executable_construction() -> None:
    """A CHECK in metadata is not proof when the actual column accepts negative values."""
    with assert_raises(m.PackageError) as error:
        m.compile(_draft("CHECK (`value` >= 0)", ""))
    assert "construction inline CHECK differs" in str(error.exception)


@test(mark="fast")
async def equal_unknown_inline_check_expressions_need_an_explicit_adapter() -> None:
    """Token equality is not permission to certify an arbitrary function expression."""
    clause = "CHECK (abs(`value`) > 0)"
    with assert_raises(m.PackageError) as error:
        m.compile(_draft(clause, clause))
    assert "unsupported construction inline CHECK expression" in str(error.exception)


@test(mark="fast")
async def a_check_label_is_part_of_its_own_inline_construction_identity() -> None:
    """A matching predicate does not make differently named constraints identical."""
    with assert_raises(m.PackageError) as error:
        m.compile(
            _draft(
                'CONSTRAINT "recorded" CHECK (`value` >= 0)',
                'CONSTRAINT "other" CHECK (`value` >= 0)',
            )
        )
    assert "construction inline CHECK differs" in str(error.exception)


@test(mark="fast")
async def equal_unsupported_inline_check_suffix_cannot_use_token_equality() -> None:
    """Own trailing ON CONFLICT is not another constraint's known conflict policy."""
    clause = "CHECK (`value` >= 0) ON CONFLICT IGNORE"
    with assert_raises(m.PackageError) as error:
        m.compile(_draft(clause, clause))
    assert "unsupported construction inline CHECK suffix" in str(error.exception)


@test(mark="fast")
async def quoted_missing_check_members_are_not_assumed_to_be_column_references() -> (
    None
):
    """SQLite double quotes can fall back to string literals when a member is absent."""
    clause = 'CHECK ("missing" >= 0)'
    with assert_raises(m.PackageError) as error:
        m.compile(_draft(clause, clause))
    assert "unsupported construction inline CHECK member" in str(error.exception)


@test(
    [
        Param(value=pair, name=str(i))
        for i, pair in enumerate(
            (
                ("", "CHECK (`value` >= 0)"),
                ("CHECK (`value` >= 0)", "CHECK (`value` > 0)"),
                ("CHECK (`value` >= 0) CHECK (`value` >= 0)", "CHECK (`value` >= 0)"),
                ("CHECK (`value` >= 0)", "CHECK (NOT (`value` < 0))"),
            )
        )
    ],
    mark="fast",
)
async def inline_check_absence_body_multiplicity_and_non_equivalence_bind(
    pair: tuple[str, str],
) -> None:
    """No asymmetric subset, deduplication or AST algebraic normalization certifies clauses."""
    with assert_raises(m.PackageError) as error:
        m.compile(_draft(*pair))
    assert "construction inline CHECK differs" in str(error.exception)


@test(
    [
        Param(value=pair, name=str(i))
        for i, pair in enumerate(
            (
                (
                    'CONSTRAINT "chosen" CHECK (`value` >= 0)',
                    'CONSTRAINT [chosen] check ("VALUE" >= 0)',
                ),
                (
                    "CHECK (`value` >= 0) CHECK (`value` <= 9)",
                    "check (`value` >= 0) CHECK (`VALUE` <= 9)",
                ),
            )
        )
    ],
    mark="fast",
)
async def known_quote_keyword_and_identifier_case_cosmetics_retain_roundtrip(
    pair: tuple[str, str],
) -> None:
    """Known identifier quotes/case normalize, preserving expression shape and string values."""
    package = m.compile(_draft(*pair))
    assert_eq(m.Package.load(package.dump()).digest, package.digest)


@test(
    [
        Param(value=pair, name=str(i))
        for i, pair in enumerate(
            (
                ("CHECK (`value` >= 0)", "CONSTRAINT chosen CHECK (`value` >= 0)"),
                (
                    "CONSTRAINT Chosen CHECK (`value` >= 0)",
                    "CONSTRAINT chosen CHECK (`value` >= 0)",
                ),
                ("CHECK (`value` <> 'Case')", "CHECK (`value` <> 'case')"),
            )
        )
    ],
    mark="fast",
)
async def labels_and_literal_case_are_not_cosmetic(pair: tuple[str, str]) -> None:
    """Case-insensitive member binding does not fold label or string-literal identity."""
    with assert_raises(m.PackageError):
        m.compile(_draft(*pair))


@test(
    [
        Param(value=clause, name=str(i))
        for i, clause in enumerate(
            (
                "CONSTRAINT 'chosen' CHECK (`value` >= 0)",
                "CHECK (`value` >= 0) MYSTERY",
                "CHECK (`value` >= 0) ON CONFLICT ABORT",
                "CHECK (1)",
                "CHECK (`value`)",
                "CHECK (`value` >= CURRENT_TIMESTAMP)",
                "CHECK (`value` >= abs(-7))",
            )
        )
    ],
    mark="fast",
)
async def equal_unknown_inline_check_roles_still_require_adapters(clause: str) -> None:
    """Trusted SQL is not a permission to claim unsupported predicates/names/suffixes."""
    with assert_raises(m.PackageError) as error:
        m.compile(_draft(clause, clause))
    assert "construction inline CHECK" in str(error.exception)


@test(
    [Param(value=scope, name=scope) for scope in ("before", "create", "adopt")],
    mark="fast",
)
async def relinquishment_does_not_erase_inline_check_construction_claims(
    scope: str,
) -> None:
    """Before/intermediate CREATE/SQLite ADOPT payloads still bind despite empty final owner."""
    table = _draft("CHECK (`value` >= 0)", "").target.tables[0]
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
        op = (
            m.CreateTable(table=table)
            if scope == "create"
            else m.AdoptTable(table=table)
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
    assert "construction inline CHECK differs" in str(error.exception)


@test([Param(value=kind, name=kind) for kind in ("add", "default")], mark="fast")
async def standalone_check_admission_precedes_final_ownership_and_operation_permission(
    kind: str,
) -> None:
    """An unsupported payload cannot hide behind later relinquishment."""
    first = m.compile(_draft("", ""))
    name = "extra" if kind == "add" else "value"
    column = m.ColumnState(
        name=name,
        definition=f"`{name}` INTEGER NOT NULL DEFAULT 7 CHECK (abs(`{name}`) > 0)",
        nullable=False,
        storage="INTEGER",
        query_type=None,
    )
    op = (
        m.AddColumn(table_name="entries", column=column)
        if kind == "add"
        else m.ChangeDefault(table_name="entries", column=column)
    )
    draft = m.Draft(
        revision="002",
        predecessor=first.digest,
        before=first.target,
        target=m.State(backend="sqlite"),
        operations=(op, m.RelinquishTable(table_name="entries")),
    )
    with assert_raises(m.PackageError) as error:
        m.compile(draft)
    assert "unsupported construction inline CHECK expression" in str(error.exception)


@test(mark="fast")
async def check_and_following_constraint_labels_and_policies_stay_separate() -> None:
    """Following named UNIQUE owns IGNORE; an inline CHECK gets no table DROP authority."""
    clause = 'CONSTRAINT "check_name" CHECK (`value` >= 0) CONSTRAINT "unique_name" UNIQUE ON CONFLICT IGNORE'
    first = m.compile(_draft(clause, clause))
    assert_eq(m.Package.load(first.dump()).digest, first.digest)
    draft = m.Draft(
        revision="002",
        predecessor=first.digest,
        before=first.target,
        target=first.target,
        operations=(m.DropCheck(table_name="entries", check_name="check_name"),),
    )
    with assert_raises(m.PackageError):
        m.compile(draft)


@test(mark="fast")
async def extra_sql_checks_and_referenced_members_do_not_manufacture_ownership() -> (
    None
):
    """Known extra members can be referenced without certifying their own opaque CHECK."""
    draft = _draft("CHECK (`extra` >= 0)", "CHECK (`extra` >= 0)")
    table = draft.target.tables[0]
    table = table.model_copy(
        update={
            "sql": table.sql.replace(
                ") STRICT", ", extra INTEGER CHECK (abs(extra) > 0)) STRICT"
            )
        }
    )
    first = m.compile(
        draft.model_copy(
            update={
                "target": draft.target.model_copy(update={"tables": (table,)}),
                "operations": (m.CreateTable(table=table),),
            }
        )
    )
    assert_eq(tuple(c.name for c in first.target.tables[0].columns), ("value",))
    followup = m.Draft(
        revision="002",
        predecessor=first.digest,
        before=first.target,
        target=first.target,
        operations=(m.DropColumn(table_name="entries", column_name="extra"),),
    )
    with assert_raises(m.PackageError):
        m.compile(followup)


@test(mark="fast")
async def check_mentions_in_literals_identifiers_and_nested_expressions_are_not_clauses() -> (
    None
):
    """A text default and quoted field name containing CHECK remain ordinary data/names."""
    draft = _draft("", "")
    column = m.ColumnState(
        name="check",
        definition="`check` TEXT NOT NULL DEFAULT 'CHECK (abs(value)>0)'",
        nullable=False,
        storage="TEXT",
        query_type=None,
    )
    table = m.TableState(
        name="entries",
        quoted_name="`entries`",
        columns=(column,),
        sql="CREATE TABLE entries (" + column.definition + ") STRICT",
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
async def inline_check_reuses_finite_token_parenthesis_tree_and_work_limits() -> None:
    """Same oversized bodies refuse before recursive parser/normalization work."""
    for expression in (
        "(" * 33 + "`value` >= 0" + ")" * 33,
        "`value` IN (" + ",".join("1" for _ in range(2200)) + ")",
        "NOT " * 80 + "`value` >= 0",
    ):
        clause = f"CHECK ({expression})"
        with assert_raises(m.PackageError) as error:
            m.compile(_draft(clause, clause))
        assert "unsupported construction inline CHECK expression" in str(
            error.exception
        )


@test(mark="medium")
async def old_false_completion_refuses_pre_effects_and_valid_literal_identity_survives() -> (
    None
):
    """Actual archived format2 missing-CHECK completion accepted -1; new prepare is effect-free."""
    root = Path(__file__).parent / "fixtures" / "inline-check"
    invalid = (root / "invalid-old.json").read_text()
    bad = m.Package.model_validate_json(invalid)
    assert_eq(
        bad.digest, "be19c2fd3013832a9e5df3e7aa1d010a6523e8b2a12850a261b9b8275e0cacc8"
    )
    with assert_raises(m.PackageError):
        m.Package.load(invalid)
    valid = (root / "valid-old.json").read_text()
    good = m.Package.load(valid)
    assert_eq(good.dump(), valid)
    assert_eq(
        good.digest, "09a1e5a0a3be4142efd9e71061e43670f6e2eb3bf76ea1031e53c6c9791372d8"
    )
    with TemporaryDirectory() as directory:
        config = sqlite.Config(database=Path(directory) / "checks.db")
        async with m.connect(config) as target:
            with assert_raises(m.PackageError):
                await target.prepare(bad)
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
                await tx.execute(sqlite.raw("INSERT INTO entries DEFAULT VALUES"))
            with assert_raises(ExecutionError):
                async with db.transaction() as tx:
                    await tx.execute(
                        sqlite.raw("INSERT INTO entries (value) VALUES (-1)")
                    )
            async with db.transaction() as tx:
                assert_eq(
                    await tx.fetch_all(sqlite.raw("SELECT value FROM entries")),
                    [{"value": 7}],
                )


@test(mark="medium")
async def nullable_check_values_follow_sql_unknown_acceptance_not_ordinary_not_null() -> (
    None
):
    """CHECK value>=0 accepts SQL NULL; it is not a hidden NOT NULL flag/solver."""
    clause = "CHECK (`value` >= 0)"
    draft = _draft(clause, clause)
    table = draft.target.tables[0]
    column = table.columns[0].model_copy(
        update={
            "nullable": True,
            "definition": table.columns[0].definition.replace(
                " NOT NULL DEFAULT 7", ""
            ),
        }
    )
    table = table.model_copy(
        update={
            "columns": (column,),
            "sql": table.sql.replace(" NOT NULL DEFAULT 7", ""),
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
        config = sqlite.Config(database=Path(directory) / "nullable.db")
        async with m.connect(config) as target:
            await target.apply(await target.prepare(package))
        async with await sqlite.Database.initialize(config) as db:
            async with db.transaction() as tx:
                await tx.execute(
                    sqlite.raw("INSERT INTO entries (value) VALUES (NULL),(0),(7)")
                )
            with assert_raises(ExecutionError):
                async with db.transaction() as tx:
                    await tx.execute(
                        sqlite.raw("INSERT INTO entries (value) VALUES (-1)")
                    )
            async with db.transaction() as tx:
                assert_eq(
                    await tx.fetch_all(
                        sqlite.raw("SELECT value FROM entries ORDER BY value")
                    ),
                    [{"value": None}, {"value": 0}, {"value": 7}],
                )


@test(mark="medium")
async def physical_inline_check_drift_still_blocks_valid_followup() -> None:
    """New admission does not replace independent catalog drift after accepted completion."""
    first = m.compile(_draft("CHECK (`value` >= 0)", "CHECK (`value` >= 0)"))
    with TemporaryDirectory() as directory:
        config = sqlite.Config(database=Path(directory) / "drift.db")
        async with m.connect(config) as target:
            await target.apply(await target.prepare(first))
        async with (
            await sqlite.Database.initialize(config) as db,
            db.transaction() as tx,
        ):
            await tx.execute(sqlite.raw("DROP TABLE entries"))
            await tx.execute(
                sqlite.raw(
                    "CREATE TABLE entries (`value` INTEGER NOT NULL DEFAULT 7 CHECK (`value` > 0)) STRICT"
                )
            )
        followup = m.compile(
            m.Draft(
                revision="002",
                predecessor=first.digest,
                before=first.target,
                target=first.target,
                operations=(),
            )
        )
        async with m.connect(config) as target:
            with assert_raises(m.PackageError):
                await target.prepare(followup)


@test(mark="medium")
async def valid_inline_check_adoption_handoff_and_readoption_keep_rows_and_enforcement() -> (
    None
):
    """Model-free ownership transfer does not recreate or delete a truthful checked table."""
    clause = 'CONSTRAINT "nonnegative" CHECK (`value` >= 0)'
    draft = _draft(clause, clause)
    table = draft.target.tables[0]
    first = m.Package.load(m.compile(draft.adopt("entries")).dump())
    handoff = m.compile(
        m.Draft(
            revision="002",
            predecessor=first.digest,
            before=first.target,
            target=m.State(backend="sqlite"),
            operations=(m.RelinquishTable(table_name="entries"),),
        )
    )
    again = m.compile(
        m.Draft(
            revision="003",
            predecessor=handoff.digest,
            before=handoff.target,
            target=first.target,
            operations=(m.AdoptTable(table=table),),
        )
    )
    with TemporaryDirectory() as directory:
        config = sqlite.Config(database=Path(directory) / "adoption.db")
        async with (
            await sqlite.Database.initialize(config) as db,
            db.transaction() as tx,
        ):
            await tx.execute(sqlite.raw(table.sql))
            await tx.execute(sqlite.raw("INSERT INTO entries DEFAULT VALUES"))
        async with m.connect(config) as target:
            await target.apply(await target.prepare(first))
            await target.apply(await target.prepare(handoff))
            await target.apply(await target.prepare(again))
            assert_eq(
                [p.phase for p in await target.status()],
                ["complete", "complete", "complete"],
            )
        async with await sqlite.Database.initialize(config) as db:
            with assert_raises(ExecutionError):
                async with db.transaction() as tx:
                    await tx.execute(
                        sqlite.raw("INSERT INTO entries (value) VALUES (-1)")
                    )
            async with db.transaction() as tx:
                assert_eq(
                    await tx.fetch_all(sqlite.raw("SELECT value FROM entries")),
                    [{"value": 7}],
                )
                assert_eq(
                    await tx.fetch_all(
                        sqlite.raw("SELECT sql FROM sqlite_schema WHERE name='entries'")
                    ),
                    [{"sql": table.sql}],
                )


@test(mark="medium")
async def changing_default_rebuild_keeps_owned_check_and_unmanaged_opaque_check() -> (
    None
):
    """A reviewed bounded inline claim need not certify preserved extra-field expressions."""
    clause = "CHECK (`value` >= 0)"
    first = m.compile(_draft(clause, clause))
    table = first.target.tables[0]
    column = table.columns[0].model_copy(
        update={
            "definition": table.columns[0].definition.replace("DEFAULT 7", "DEFAULT 8")
        }
    )
    table = table.model_copy(
        update={
            "columns": (column,),
            "sql": table.sql.replace("DEFAULT 7", "DEFAULT 8"),
        }
    )
    second = m.Package.load(
        m.compile(
            m.Draft(
                revision="002",
                predecessor=first.digest,
                before=first.target,
                target=m.State(backend="sqlite", tables=(table,)),
                operations=(m.ChangeDefault(table_name="entries", column=column),),
            )
        ).dump()
    )
    with TemporaryDirectory() as directory:
        config = sqlite.Config(database=Path(directory) / "rebuild.db")
        async with m.connect(config) as target:
            await target.apply(await target.prepare(first))
        async with aiosqlite.connect(str(config.database)) as app:
            await app.execute(
                "ALTER TABLE entries ADD COLUMN extra TEXT NOT NULL DEFAULT 'kept' CHECK (length(extra) > 0)"
            )
            await app.execute("INSERT INTO entries DEFAULT VALUES")
            await app.commit()
        async with m.connect(config) as target:
            await target.apply(await target.prepare(second, preserve_unmanaged=True))
        async with await sqlite.Database.initialize(config) as db:
            async with db.transaction() as tx:
                await tx.execute(sqlite.raw("INSERT INTO entries DEFAULT VALUES"))
            with assert_raises(ExecutionError):
                async with db.transaction() as tx:
                    await tx.execute(
                        sqlite.raw("INSERT INTO entries (value) VALUES (-1)")
                    )
            with assert_raises(ExecutionError):
                async with db.transaction() as tx:
                    await tx.execute(
                        sqlite.raw("INSERT INTO entries (extra) VALUES ('')")
                    )
            async with db.transaction() as tx:
                assert_eq(
                    await tx.fetch_all(
                        sqlite.raw("SELECT value,extra FROM entries ORDER BY value")
                    ),
                    [{"value": 7, "extra": "kept"}, {"value": 8, "extra": "kept"}],
                )


@test(mark="fast")
async def unknown_nested_check_collation_requires_check_not_column_collation_adapter() -> (
    None
):
    """A nested opaque comparison domain is not promoted into the column attribute gate."""
    clause = "CHECK (`value` COLLATE application_custom >= 0)"
    with assert_raises(m.PackageError) as error:
        m.compile(_draft(clause, clause))
    assert "unsupported construction inline CHECK expression" in str(error.exception)

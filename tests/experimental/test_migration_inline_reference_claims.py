"""Bounded SQLite inline reference identity agrees with executable construction."""

from pathlib import Path
from tempfile import TemporaryDirectory

from snektest import Param, assert_eq, assert_raises, test

from snekql import sqlite
from snekql.errors import ExecutionError
from snekql.experimental import migrations as m


def _draft(declaration: str, construction: str) -> m.Draft:
    """Keep explicit parent ownership separate from the child reference declaration."""
    parent_column = m.ColumnState(
        name="id",
        definition="`id` INTEGER PRIMARY KEY",
        nullable=False,
        storage="INTEGER",
        query_type="int",
    )
    parent = m.TableState(
        name="parents",
        quoted_name="`parents`",
        columns=(parent_column,),
        sql="CREATE TABLE `parents` (`id` INTEGER PRIMARY KEY) STRICT",
    )
    prefix = "`parent_id` INTEGER"
    child_column = m.ColumnState(
        name="parent_id",
        definition=prefix + (" " + declaration if declaration else ""),
        nullable=True,
        storage="INTEGER",
        query_type=None,
    )
    child = m.TableState(
        name="children",
        quoted_name="`children`",
        columns=(child_column,),
        sql="CREATE TABLE `children` ("
        + prefix
        + (" " + construction if construction else "")
        + ") STRICT",
    )
    return m.Draft(
        revision="001",
        predecessor=None,
        before=m.State(backend="sqlite"),
        target=m.State(backend="sqlite", tables=(parent, child)),
        operations=(m.CreateTable(table=parent), m.CreateTable(table=child)),
    )


@test(mark="fast")
async def inline_reference_cannot_disappear_from_executable_construction() -> None:
    """A metadata relationship does not prevent orphan writes without actual DDL."""
    with assert_raises(m.PackageError) as error:
        m.compile(_draft("REFERENCES `parents` (`id`)", ""))
    assert "construction inline REFERENCES differs" in str(error.exception)


@test(mark="fast")
async def matching_deferred_reference_language_requires_an_explicit_adapter() -> None:
    """Token equality is not admission of unknown timing/implicit-target semantics."""
    clause = "REFERENCES `parents` (`id`) DEFERRABLE INITIALLY DEFERRED"
    with assert_raises(m.PackageError) as error:
        m.compile(_draft(clause, clause))
    assert "unsupported construction inline REFERENCES" in str(error.exception)


@test(mark="fast")
async def reference_labels_bind_independently_of_target_and_actions() -> None:
    """Matching relationship facts don't erase an explicit SQLite constraint symbol."""
    with assert_raises(m.PackageError) as error:
        m.compile(
            _draft(
                'CONSTRAINT "recorded" REFERENCES `parents` (`id`)',
                'CONSTRAINT "other" REFERENCES `parents` (`id`)',
            )
        )
    assert "construction inline REFERENCES differs" in str(error.exception)


@test(mark="fast")
async def explicit_unknown_reference_timing_is_not_an_ordinary_not_null_clause() -> (
    None
):
    """NOT DEFERRABLE cannot hide behind an admitted NOT NULL boundary."""
    clause = "REFERENCES `parents` (`id`) NOT DEFERRABLE"
    with assert_raises(m.PackageError) as error:
        m.compile(_draft(clause, clause))
    assert "unsupported construction inline REFERENCES suffix" in str(error.exception)


@test(
    [
        Param(value=pair, name=str(i))
        for i, pair in enumerate(
            (
                ("", "REFERENCES `parents` (`id`)"),
                ("REFERENCES `parents` (`id`)", "REFERENCES `other` (`id`)"),
                ("REFERENCES `parents` (`id`)", "REFERENCES `parents` (`other`)"),
                (
                    "REFERENCES `parents` (`id`) ON DELETE CASCADE",
                    "REFERENCES `parents` (`id`)",
                ),
                (
                    "REFERENCES `parents` (`id`) ON UPDATE CASCADE",
                    "REFERENCES `parents` (`id`)",
                ),
                (
                    "REFERENCES `parents` (`id`) ON UPDATE NO ACTION",
                    "REFERENCES `parents` (`id`) ON UPDATE RESTRICT",
                ),
            )
        )
    ],
    mark="fast",
)
async def reference_absence_target_member_and_actions_bind(
    pair: tuple[str, str],
) -> None:
    """NO ACTION and RESTRICT aren't folded together by native immediate-action rules."""
    with assert_raises(m.PackageError) as error:
        m.compile(_draft(*pair))
    assert "construction inline REFERENCES differs" in str(error.exception)


@test(
    [
        Param(value=pair, name=str(i))
        for i, pair in enumerate(
            (
                (
                    'CONSTRAINT "chosen" REFERENCES `parents` (`id`)',
                    'CONSTRAINT [chosen] references "PARENTS" ([ID]) ON UPDATE NO ACTION ON DELETE NO ACTION',
                ),
                (
                    "REFERENCES parents(id) ON DELETE CASCADE ON UPDATE RESTRICT",
                    "REFERENCES `PARENTS` (`ID`) ON UPDATE RESTRICT ON DELETE CASCADE",
                ),
            )
        )
    ],
    mark="fast",
)
async def known_reference_quotes_case_default_actions_and_clause_order_roundtrip(
    pair: tuple[str, str],
) -> None:
    """One explicit full member with known immediate actions has a bounded signature."""
    package = m.compile(_draft(*pair))
    assert_eq(m.Package.load(package.dump()).digest, package.digest)


@test(
    [
        Param(value=clause, name=str(i))
        for i, clause in enumerate(
            (
                "REFERENCES parents",
                "REFERENCES parents(id,other)",
                "REFERENCES main.parents(id)",
                "REFERENCES 'parents'(id)",
                "REFERENCES parents('id')",
                "REFERENCES parents(id DESC)",
                "REFERENCES parents(id) MATCH SIMPLE",
                "REFERENCES parents(id) ON UPDATE SET NULL",
                "REFERENCES parents(id) ON DELETE SET DEFAULT",
                "REFERENCES parents(id) ON UPDATE CASCADE ON UPDATE CASCADE",
                "REFERENCES parents(id) REFERENCES parents(id)",
                "CONSTRAINT 'chosen' REFERENCES parents(id)",
            )
        )
    ],
    mark="fast",
)
async def equal_unknown_reference_shapes_require_explicit_adapters(clause: str) -> None:
    """No implicit parent-key lookup, expressions, timing/MATCH/SET or quote-role guesses."""
    with assert_raises(m.PackageError):
        m.compile(_draft(clause, clause))


@test(mark="fast")
async def reference_label_presence_case_and_following_constraint_identity_are_separate() -> (
    None
):
    """Following UNIQUE owns its own label; an FK symbol is not table CHECK authority."""
    for pair in (
        ("REFERENCES parents(id)", 'CONSTRAINT "chosen" REFERENCES parents(id)'),
        (
            'CONSTRAINT "Chosen" REFERENCES parents(id)',
            'CONSTRAINT "chosen" REFERENCES parents(id)',
        ),
    ):
        with assert_raises(m.PackageError):
            m.compile(_draft(*pair))
    clause = 'CONSTRAINT "fk_parent" REFERENCES parents(id) CONSTRAINT "uq_parent" UNIQUE ON CONFLICT IGNORE'
    first = m.compile(_draft(clause, clause))
    assert_eq(m.Package.load(first.dump()).digest, first.digest)
    draft = m.Draft(
        revision="002",
        predecessor=first.digest,
        before=first.target,
        target=first.target,
        operations=(m.DropCheck(table_name="children", check_name="fk_parent"),),
    )
    with assert_raises(m.PackageError):
        m.compile(draft)


@test(
    [Param(value=scope, name=scope) for scope in ("before", "create", "adopt")],
    mark="fast",
)
async def relinquishment_does_not_erase_reference_construction_claims(
    scope: str,
) -> None:
    """Even intermediate reference declarations bind when the final owner set is empty."""
    first = _draft("REFERENCES parents(id)", "")
    empty = m.State(backend="sqlite")
    parent, child = first.target.tables
    if scope == "before":
        draft = m.Draft(
            revision="002",
            predecessor="previous",
            before=first.target,
            target=empty,
            operations=(
                m.RelinquishTable(table_name="children"),
                m.RelinquishTable(table_name="parents"),
            ),
        )
    else:
        op = (
            m.CreateTable(table=child)
            if scope == "create"
            else m.AdoptTable(table=child)
        )
        draft = m.Draft(
            revision="001",
            predecessor=None,
            before=empty,
            target=empty,
            operations=(
                m.CreateTable(table=parent),
                op,
                m.RelinquishTable(table_name="children"),
                m.RelinquishTable(table_name="parents"),
            ),
        )
    with assert_raises(m.PackageError) as error:
        m.compile(draft)
    assert "construction inline REFERENCES differs" in str(error.exception)


@test([Param(value=kind, name=kind) for kind in ("add", "default")], mark="fast")
async def standalone_reference_language_is_checked_before_handoff(kind: str) -> None:
    """Unsupported operation payloads don't escape admission through an empty final owner."""
    first = m.compile(_draft("", ""))
    name = "extra" if kind == "add" else "parent_id"
    column = m.ColumnState(
        name=name,
        definition=f"`{name}` INTEGER REFERENCES parents(id) DEFERRABLE",
        nullable=True,
        storage="INTEGER",
        query_type=None,
    )
    op = (
        m.AddColumn(table_name="children", column=column)
        if kind == "add"
        else m.ChangeDefault(table_name="children", column=column)
    )
    draft = m.Draft(
        revision="002",
        predecessor=first.digest,
        before=first.target,
        target=m.State(backend="sqlite"),
        operations=(
            op,
            m.RelinquishTable(table_name="children"),
            m.RelinquishTable(table_name="parents"),
        ),
    )
    with assert_raises(m.PackageError) as error:
        m.compile(draft)
    assert "unsupported construction inline REFERENCES" in str(error.exception)


@test(mark="fast")
async def references_in_names_literals_and_nested_checks_are_not_relationships() -> (
    None
):
    """Only a top-level REFERENCES clause has target/action identity."""
    draft = _draft("", "")
    parent, child = draft.target.tables
    definition = (
        "`REFERENCES` TEXT DEFAULT 'REFERENCES parents(id)' CHECK (`REFERENCES` <> '')"
    )
    column = m.ColumnState(
        name="REFERENCES",
        definition=definition,
        nullable=True,
        storage="TEXT",
        query_type=None,
    )
    child = child.model_copy(
        update={
            "columns": (column,),
            "sql": "CREATE TABLE `children` (" + definition + ") STRICT",
        }
    )
    package = m.compile(
        draft.model_copy(
            update={
                "target": draft.target.model_copy(update={"tables": (parent, child)}),
                "operations": (m.CreateTable(table=parent), m.CreateTable(table=child)),
            }
        )
    )
    assert_eq(m.Package.load(package.dump()).digest, package.digest)


@test(mark="fast")
async def references_and_extra_child_fields_do_not_manufacture_parent_ownership() -> (
    None
):
    """A declared relation doesn't adopt an external parent or claim extra SQL child fields."""
    draft = _draft("REFERENCES parents(id)", "REFERENCES parents(id)")
    child = draft.target.tables[1]
    child = child.model_copy(
        update={
            "sql": child.sql.replace(
                ") STRICT",
                ", extra INTEGER REFERENCES other(id) DEFERRABLE INITIALLY DEFERRED) STRICT",
            )
        }
    )
    package = m.compile(
        draft.model_copy(
            update={
                "target": m.State(backend="sqlite", tables=(child,)),
                "operations": (m.CreateTable(table=child),),
            }
        )
    )
    assert_eq(tuple(t.name for t in package.target.tables), ("children",))
    assert_eq(tuple(c.name for c in package.target.tables[0].columns), ("parent_id",))


@test(mark="medium")
async def old_missing_reference_false_completion_refuses_pre_effects_and_valid_identity_survives() -> (
    None
):
    """Actual old format2 completed/orphan999 with foreign_keys1; now refusal precedes schema/history."""
    root = Path(__file__).parent / "fixtures" / "inline-reference"
    invalid = (root / "invalid-old.json").read_text()
    bad = m.Package.model_validate_json(invalid)
    assert_eq(
        bad.digest, "90e56f66348fe21f7e5db99bf9a8dbe85e2e77e6e68879dad8bd836caa831c1c"
    )
    with assert_raises(m.PackageError):
        m.Package.load(invalid)
    valid = (root / "valid-old.json").read_text()
    good = m.Package.load(valid)
    assert_eq(good.dump(), valid)
    assert_eq(
        good.digest, "1ca4def98fd723778865f8eda9505fa3298600a89c6a365e795c7e5864c36a74"
    )
    with TemporaryDirectory() as directory:
        config = sqlite.Config(database=Path(directory) / "reference.db")
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
                assert_eq(
                    await tx.fetch_all(sqlite.raw("PRAGMA foreign_keys")),
                    [{"foreign_keys": 1}],
                )
                await tx.execute(sqlite.raw("INSERT INTO parents(id) VALUES (1)"))
                await tx.execute(
                    sqlite.raw("INSERT INTO children(parent_id) VALUES (1),(NULL)")
                )
            with assert_raises(ExecutionError):
                async with db.transaction() as tx:
                    await tx.execute(
                        sqlite.raw("INSERT INTO children(parent_id) VALUES (999)")
                    )
            async with db.transaction() as tx:
                assert_eq(
                    await tx.fetch_all(
                        sqlite.raw("SELECT parent_id FROM children ORDER BY parent_id")
                    ),
                    [{"parent_id": None}, {"parent_id": 1}],
                )


@test(mark="medium")
async def known_cascade_actions_retain_actual_delete_and_update_behavior() -> None:
    """Bounded clause agreement accompanies current-session relationship enforcement."""
    clause = "REFERENCES parents(id) ON UPDATE CASCADE ON DELETE CASCADE"
    package = m.Package.load(m.compile(_draft(clause, clause)).dump())
    with TemporaryDirectory() as directory:
        config = sqlite.Config(database=Path(directory) / "cascade.db")
        async with m.connect(config) as target:
            await target.apply(await target.prepare(package))
        async with (
            await sqlite.Database.initialize(config) as db,
            db.transaction() as tx,
        ):
            await tx.execute(sqlite.raw("INSERT INTO parents(id) VALUES (1)"))
            await tx.execute(sqlite.raw("INSERT INTO children(parent_id) VALUES (1)"))
            await tx.execute(sqlite.raw("UPDATE parents SET id=2 WHERE id=1"))
            assert_eq(
                await tx.fetch_all(sqlite.raw("SELECT parent_id FROM children")),
                [{"parent_id": 2}],
            )
            await tx.execute(sqlite.raw("DELETE FROM parents WHERE id=2"))
            assert_eq(
                await tx.fetch_all(sqlite.raw("SELECT parent_id FROM children")), []
            )


@test(mark="medium")
async def later_physical_reference_drift_still_blocks_valid_followup() -> None:
    """Construction identity doesn't replace independent accepted-catalog drift proof."""
    clause = "REFERENCES parents(id)"
    first = m.compile(_draft(clause, clause))
    with TemporaryDirectory() as directory:
        config = sqlite.Config(database=Path(directory) / "drift.db")
        async with m.connect(config) as target:
            await target.apply(await target.prepare(first))
        async with (
            await sqlite.Database.initialize(config) as db,
            db.transaction() as tx,
        ):
            await tx.execute(sqlite.raw("DROP TABLE children"))
            await tx.execute(
                sqlite.raw(
                    "CREATE TABLE children(parent_id INTEGER REFERENCES parents(id) ON DELETE CASCADE) STRICT"
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

"""SQLite parent base-table observation is separate from ownership and FK key proof."""

from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Literal

from snektest import Param, assert_eq, assert_raises, test

from snekql import sqlite
from snekql.errors import ExecutionError
from snekql.experimental import migrations as m
from tests.experimental.test_migration_inline_reference_claims import _draft


def _child_package() -> m.Package:
    """Compile an owned child while leaving its referenced parent outside ownership."""
    draft = _draft("REFERENCES parents(id)", "REFERENCES parents(id)")
    child = draft.target.tables[1]
    return m.compile(
        draft.model_copy(
            update={
                "target": m.State(backend="sqlite", tables=(child,)),
                "operations": (m.CreateTable(table=child),),
            }
        )
    )


@test(mark="medium")
async def preparation_refuses_missing_referenced_parent_without_schema_or_history_effects() -> (
    None
):
    """A real child FK declaration does not prove that its parent table exists."""
    with TemporaryDirectory() as directory:
        config = sqlite.Config(database=Path(directory) / "missing.db")
        async with m.connect(config) as target:
            with assert_raises(m.PackageError) as error:
                await target.prepare(_child_package())
            assert "SQLite referenced parent" in str(error.exception)
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


@test(mark="medium")
async def virtual_referenced_parent_is_not_an_ordinary_base_table() -> None:
    """Catalog type table alone does not prove a usable ordinary referenced relation."""
    with TemporaryDirectory() as directory:
        config = sqlite.Config(database=Path(directory) / "virtual.db")
        async with (
            await sqlite.Database.initialize(config) as db,
            db.transaction() as tx,
        ):
            await tx.execute(sqlite.raw("CREATE VIRTUAL TABLE parents USING fts5(id)"))
        async with m.connect(config) as target:
            with assert_raises(m.PackageError) as error:
                await target.prepare(_child_package())
            assert "SQLite referenced parent" in str(error.exception)


@test(mark="medium")
async def compiler_style_table_foreign_keys_need_parent_base_presence_too() -> None:
    """A table-level FOREIGN KEY cannot evade the independent parent observation gate."""
    draft = _draft("", "")
    child = draft.target.tables[1]
    child = child.model_copy(
        update={
            "sql": child.sql.replace(
                ") STRICT", ", FOREIGN KEY(parent_id) REFERENCES parents(id)) STRICT"
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
    with TemporaryDirectory() as directory:
        async with m.connect(
            sqlite.Config(database=Path(directory) / "table-fk.db")
        ) as target:
            with assert_raises(m.PackageError):
                await target.prepare(package)


@test(mark="medium")
async def relinquishment_cannot_hide_created_child_parent_readiness() -> None:
    """An intermediate owned child still needs its missing parent despite final handoff."""
    first = _child_package()
    child = first.target.tables[0]
    package = m.compile(
        first.draft.model_copy(
            update={
                "target": m.State(backend="sqlite"),
                "operations": (
                    m.CreateTable(table=child),
                    m.RelinquishTable(table_name="children"),
                ),
            }
        )
    )
    with TemporaryDirectory() as directory:
        async with m.connect(
            sqlite.Config(database=Path(directory) / "handoff.db")
        ) as target:
            with assert_raises(m.PackageError):
                await target.prepare(package)


@test(mark="fast")
async def parent_validation_does_not_grant_constrained_addition_permission() -> None:
    """Parent observation is not a new inline-FK ADD operation or operation bypass."""
    draft = _draft("", "")
    child = draft.target.tables[1]
    first = m.compile(
        draft.model_copy(
            update={
                "target": m.State(backend="sqlite", tables=(child,)),
                "operations": (m.CreateTable(table=child),),
            }
        )
    )
    column = m.ColumnState(
        name="extra",
        definition="`extra` INTEGER REFERENCES parents(id)",
        nullable=True,
        storage="INTEGER",
        query_type=None,
    )
    with assert_raises(m.PackageError) as error:
        m.compile(
            m.Draft(
                revision="002",
                predecessor=first.digest,
                before=first.target,
                target=m.State(backend="sqlite"),
                operations=(
                    m.AddColumn(table_name="children", column=column),
                    m.RelinquishTable(table_name="children"),
                ),
            )
        )
    assert "only unconstrained nullable additions" in str(error.exception)


@test(mark="medium")
async def view_parent_is_not_a_base_table_and_does_not_become_owned() -> None:
    """A name-resolution hit on a view is not an ordinary referenced table."""
    with TemporaryDirectory() as directory:
        config = sqlite.Config(database=Path(directory) / "view.db")
        async with (
            await sqlite.Database.initialize(config) as db,
            db.transaction() as tx,
        ):
            await tx.execute(sqlite.raw("CREATE VIEW parents AS SELECT 1 AS id"))
        async with m.connect(config) as target:
            with assert_raises(m.PackageError):
                await target.prepare(_child_package())
            assert_eq(await target.status(), ())
        async with (
            await sqlite.Database.initialize(config) as db,
            db.transaction() as tx,
        ):
            assert_eq(
                await tx.fetch_all(
                    sqlite.raw("SELECT type,name FROM sqlite_schema ORDER BY name")
                ),
                [{"type": "view", "name": "parents"}],
            )


@test(
    [
        Param[Literal["parent_first", "child_first"]](value=order, name=order)
        for order in ("parent_first", "child_first")
    ],
    mark="medium",
)
async def explicit_same_package_parent_creation_projects_final_base_presence(
    order: Literal["parent_first", "child_first"],
) -> None:
    """SQLite may create the child first; final projection is not a per-step readiness promise."""
    clause = "REFERENCES parents(id)"
    draft = _draft(clause, clause)
    if order == "child_first":
        draft = draft.model_copy(
            update={"operations": tuple(reversed(draft.operations))}
        )
    package = m.Package.load(m.compile(draft).dump())
    with TemporaryDirectory() as directory:
        config = sqlite.Config(database=Path(directory) / "created.db")
        async with m.connect(config) as target:
            await target.apply(await target.prepare(package))
        async with await sqlite.Database.initialize(config) as db:
            async with db.transaction() as tx:
                await tx.execute(sqlite.raw("INSERT INTO parents(id) VALUES (1)"))
                await tx.execute(
                    sqlite.raw("INSERT INTO children(parent_id) VALUES (1)")
                )
            with assert_raises(ExecutionError):
                async with db.transaction() as tx:
                    await tx.execute(
                        sqlite.raw("INSERT INTO children(parent_id) VALUES (999)")
                    )


@test(mark="medium")
async def observed_external_parent_retains_frozen_identity_without_adoption() -> None:
    """Actual archived contract loads unchanged; observation supplies parent presence, not ownership."""
    text = (
        Path(__file__).parent
        / "fixtures"
        / "sqlite-reference-parents"
        / "frozen-old.json"
    ).read_text()
    package = m.Package.load(text)
    assert_eq(
        package.digest,
        "d6a09e1a4489ca946611a82f4747a01a578c388c140e91ba75457ccc96b6e53e",
    )
    assert_eq(package.dump(), text)
    assert_eq(tuple(t.name for t in package.target.tables), ("children",))
    with TemporaryDirectory() as directory:
        config = sqlite.Config(database=Path(directory) / "external.db")
        async with m.connect(config) as target:
            with assert_raises(m.PackageError):
                await target.prepare(package)
            assert_eq(await target.status(), ())
        async with (
            await sqlite.Database.initialize(config) as db,
            db.transaction() as tx,
        ):
            await tx.execute(
                sqlite.raw('CREATE TABLE "PARENTS" (id INTEGER PRIMARY KEY)')
            )
            await tx.execute(sqlite.raw("INSERT INTO parents(id) VALUES (1)"))
        async with m.connect(config) as target:
            await target.apply(await target.prepare(package))
        async with await sqlite.Database.initialize(config) as db:
            async with db.transaction() as tx:
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
                    await tx.fetch_all(sqlite.raw("SELECT id FROM parents")),
                    [{"id": 1}],
                )


@test(mark="medium")
async def parent_replaced_after_preparation_invalidates_application_before_effects() -> (
    None
):
    """Catalog coordination revalidation includes unowned parent changes too."""
    with TemporaryDirectory() as directory:
        config = sqlite.Config(database=Path(directory) / "stale.db")
        async with (
            await sqlite.Database.initialize(config) as db,
            db.transaction() as tx,
        ):
            await tx.execute(sqlite.raw("CREATE TABLE parents(id INTEGER PRIMARY KEY)"))
        async with m.connect(config) as target:
            plan = await target.prepare(_child_package())
        async with (
            await sqlite.Database.initialize(config) as db,
            db.transaction() as tx,
        ):
            await tx.execute(sqlite.raw("DROP TABLE parents"))
            await tx.execute(sqlite.raw("CREATE VIEW parents AS SELECT 1 AS id"))
        async with m.connect(config) as target:
            with assert_raises(m.PackageError):
                await target.apply(plan)
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


@test(mark="medium")
async def post_completion_external_parent_drift_still_blocks_followup() -> None:
    """New projected observation doesn't replace independent accepted-catalog evidence."""
    first = _child_package()
    with TemporaryDirectory() as directory:
        config = sqlite.Config(database=Path(directory) / "drift.db")
        async with (
            await sqlite.Database.initialize(config) as db,
            db.transaction() as tx,
        ):
            await tx.execute(sqlite.raw("CREATE TABLE parents(id INTEGER PRIMARY KEY)"))
        async with m.connect(config) as target:
            await target.apply(await target.prepare(first))
        async with (
            await sqlite.Database.initialize(config) as db,
            db.transaction() as tx,
        ):
            await tx.execute(sqlite.raw("DROP TABLE parents"))
        second = m.compile(
            m.Draft(
                revision="002",
                predecessor=first.digest,
                before=first.target,
                target=first.target,
                operations=(),
            )
        )
        async with m.connect(config) as target:
            with assert_raises(m.PackageError) as error:
                await target.prepare(second)
            assert "catalog differs from the last accepted execution" in str(
                error.exception
            )


@test(mark="medium")
async def strict_adoption_requires_an_observed_reference_parent_without_stamping() -> (
    None
):
    """An existing child's matching FK DDL cannot certify a missing external parent."""
    first = _child_package()
    child = first.target.tables[0]
    package = m.compile(first.draft.adopt("children"))
    with TemporaryDirectory() as directory:
        config = sqlite.Config(database=Path(directory) / "adopt.db")
        async with (
            await sqlite.Database.initialize(config) as db,
            db.transaction() as tx,
        ):
            await tx.execute(sqlite.raw(child.sql))
        async with m.connect(config) as target:
            with assert_raises(m.PackageError):
                await target.prepare(package)
            assert_eq(await target.status(), ())


@test(mark="medium")
async def unowned_extra_field_references_do_not_manufacture_parent_claims() -> None:
    """The base-parent gate follows managed inline/table FK claims, not opaque SQL extras."""
    draft = _draft("", "")
    child = draft.target.tables[1]
    child = child.model_copy(
        update={
            "sql": child.sql.replace(
                ") STRICT", ", extra INTEGER REFERENCES unknown_parent(id)) STRICT"
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
    with TemporaryDirectory() as directory:
        async with m.connect(
            sqlite.Config(database=Path(directory) / "extra.db")
        ) as target:
            await target.prepare(package)
            assert_eq(await target.status(), ())
    assert_eq(tuple(c.name for c in package.target.tables[0].columns), ("parent_id",))

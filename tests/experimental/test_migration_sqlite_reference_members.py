"""Explicit SQLite referenced members are physical columns, not key/codec readiness."""

from pathlib import Path
from tempfile import TemporaryDirectory

from snektest import Param, assert_eq, assert_raises, test

from snekql import sqlite
from snekql.errors import ExecutionError
from snekql.experimental import migrations as m
from tests.experimental.test_migration_inline_reference_claims import _draft


def _child_package(member: str = "id") -> m.Package:
    """Review a child FK without adopting or importing its parent model."""
    clause = 'REFERENCES parents("' + member.replace('"', '""') + '")'
    draft = _draft(clause, clause)
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
async def ordinary_parent_does_not_prove_a_missing_referenced_column() -> None:
    """A parent table name alone leaves an unusable cross-table FK declaration."""
    with TemporaryDirectory() as directory:
        config = sqlite.Config(database=Path(directory) / "missing.db")
        async with (
            await sqlite.Database.initialize(config) as db,
            db.transaction() as tx,
        ):
            await tx.execute(sqlite.raw("CREATE TABLE parents(id INTEGER PRIMARY KEY)"))
        async with m.connect(config) as target:
            with assert_raises(m.PackageError) as error:
                await target.prepare(_child_package("missing"))
            assert "SQLite referenced member" in str(error.exception)
            assert_eq(await target.status(), ())
        async with (
            await sqlite.Database.initialize(config) as db,
            db.transaction() as tx,
        ):
            assert_eq(
                await tx.fetch_all(
                    sqlite.raw("SELECT name FROM sqlite_schema WHERE type='table'")
                ),
                [{"name": "parents"}],
            )


@test(mark="medium")
async def table_foreign_key_explicit_members_need_parent_columns_too() -> None:
    """Compiler-style table constraints cannot evade referenced-member observation."""
    draft = _draft("", "")
    child = draft.target.tables[1]
    child = child.model_copy(
        update={
            "sql": child.sql.replace(
                ") STRICT",
                ", FOREIGN KEY(parent_id) REFERENCES parents(missing)) STRICT",
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
        config = sqlite.Config(database=Path(directory) / "table.db")
        async with (
            await sqlite.Database.initialize(config) as db,
            db.transaction() as tx,
        ):
            await tx.execute(sqlite.raw("CREATE TABLE parents(id INTEGER PRIMARY KEY)"))
        async with m.connect(config) as target:
            with assert_raises(m.PackageError) as error:
                await target.prepare(package)
            assert "SQLite referenced member" in str(error.exception)


@test(
    [
        Param[tuple[str, str]](value=(member, sql), name=member)
        for member, sql in (
            ("rowid", "CREATE TABLE parents(id INTEGER PRIMARY KEY)"),
            ("_rowid_", "CREATE TABLE parents(id INTEGER PRIMARY KEY)"),
            ("oid", "CREATE TABLE parents(id INTEGER PRIMARY KEY)"),
            ("K", 'CREATE TABLE parents("\u212a" INTEGER PRIMARY KEY)'),
            (
                "label",
                "CREATE TABLE parents(other INTEGER, CONSTRAINT label UNIQUE(other))",
            ),
            ("literal", "CREATE TABLE parents(other TEXT DEFAULT 'literal')"),
        )
    ],
    mark="medium",
)
async def pseudo_aliases_labels_literals_and_unicode_folds_are_not_columns(
    case: tuple[str, str],
) -> None:
    """Do not infer a referenced column from query aliases or unrelated SQL tokens."""
    member, sql = case
    with TemporaryDirectory() as directory:
        config = sqlite.Config(database=Path(directory) / "roles.db")
        async with (
            await sqlite.Database.initialize(config) as db,
            db.transaction() as tx,
        ):
            await tx.execute(sqlite.raw(sql))
        async with m.connect(config) as target:
            with assert_raises(m.PackageError) as error:
                await target.prepare(_child_package(member))
            assert "SQLite referenced member" in str(error.exception)
            assert_eq(await target.status(), ())


@test(
    [
        Param[tuple[str, str]](value=(member, sql), name=member)
        for member, sql in (
            ("id", "CREATE TABLE PARENTS(ID INTEGER PRIMARY KEY)"),
            ("rowid", "CREATE TABLE parents(rowid INTEGER PRIMARY KEY)"),
            ("primary", 'CREATE TABLE parents("primary" INTEGER PRIMARY KEY)'),
            ('o"id', 'CREATE TABLE parents("o""id" INTEGER PRIMARY KEY)'),
            ("\u212a", 'CREATE TABLE parents("\u212a" INTEGER PRIMARY KEY)'),
        )
    ],
    mark="medium",
)
async def declared_columns_retain_physical_names_without_parent_adoption(
    case: tuple[str, str],
) -> None:
    """ASCII/identifier cosmetics work; a real rowid-named column is not an alias."""
    member, sql = case
    with TemporaryDirectory() as directory:
        config = sqlite.Config(database=Path(directory) / "present.db")
        async with (
            await sqlite.Database.initialize(config) as db,
            db.transaction() as tx,
        ):
            await tx.execute(sqlite.raw(sql))
            await tx.execute(sqlite.raw("INSERT INTO parents VALUES (7)"))
        package = m.Package.load(_child_package(member).dump())
        assert_eq(tuple(t.name for t in package.target.tables), ("children",))
        async with m.connect(config) as target:
            await target.apply(await target.prepare(package))
        async with (
            await sqlite.Database.initialize(config) as db,
            db.transaction() as tx,
        ):
            await tx.execute(sqlite.raw("PRAGMA foreign_keys=ON"))
            await tx.execute(
                sqlite.raw("INSERT INTO children(parent_id) VALUES (7),(NULL)")
            )
        with assert_raises(ExecutionError):
            async with (
                await sqlite.Database.initialize(config) as db,
                db.transaction() as tx,
            ):
                await tx.execute(sqlite.raw("PRAGMA foreign_keys=ON"))
                await tx.execute(
                    sqlite.raw("INSERT INTO children(parent_id) VALUES (999)")
                )


@test(mark="medium")
async def same_package_parent_projection_rejects_missing_member() -> None:
    """Planned parent existence does not fill a nonexistent referenced member."""
    package = m.compile(
        _draft("REFERENCES parents(missing)", "REFERENCES parents(missing)")
    )
    with TemporaryDirectory() as directory:
        async with m.connect(
            sqlite.Config(database=Path(directory) / "projected.db")
        ) as target:
            with assert_raises(m.PackageError) as error:
                await target.prepare(package)
            assert "SQLite referenced member" in str(error.exception)
            assert_eq(await target.status(), ())


@test(
    [Param[str](value=mode, name=mode) for mode in ("handoff", "adopt")], mark="medium"
)
async def ownership_changes_do_not_hide_reference_member_claims(mode: str) -> None:
    """Intermediate CREATE and explicit ADOPT keep claims without owning the parent."""
    first = _child_package("missing")
    child = first.target.tables[0]
    draft = (
        first.draft.adopt("children")
        if mode == "adopt"
        else first.draft.model_copy(
            update={
                "target": m.State(backend="sqlite"),
                "operations": (
                    m.CreateTable(table=child),
                    m.RelinquishTable(table_name="children"),
                ),
            }
        )
    )
    package = m.compile(draft)
    with TemporaryDirectory() as directory:
        config = sqlite.Config(database=Path(directory) / "ownership.db")
        async with (
            await sqlite.Database.initialize(config) as db,
            db.transaction() as tx,
        ):
            await tx.execute(sqlite.raw("CREATE TABLE parents(id INTEGER PRIMARY KEY)"))
            if mode == "adopt":
                await tx.execute(sqlite.raw(child.sql))
        async with m.connect(config) as target:
            with assert_raises(m.PackageError) as error:
                await target.prepare(package)
            assert "SQLite referenced member" in str(error.exception)
            assert_eq(await target.status(), ())


def _table_package(suffix: str) -> m.Package:
    """Review one table-level single/composite/implicit reference without parent ownership."""
    draft = _draft("", "")
    child = draft.target.tables[1]
    child = child.model_copy(
        update={"sql": child.sql.replace(") STRICT", suffix + ") STRICT")}
    )
    return m.compile(
        draft.model_copy(
            update={
                "target": m.State(backend="sqlite", tables=(child,)),
                "operations": (m.CreateTable(table=child),),
            }
        )
    )


@test(
    [Param[str](value=member, name=member) for member in ("other", "missing")],
    mark="medium",
)
async def every_explicit_composite_member_is_observed(member: str) -> None:
    """Do not stop after a valid first member; physical presence is not key eligibility."""
    first = _table_package(
        f', `other` INTEGER, CONSTRAINT fk_pair FOREIGN KEY(parent_id,other) REFERENCES parents(id,"{member}")'
    )
    child = first.target.tables[0]
    child = child.model_copy(
        update={
            "columns": (
                *child.columns,
                m.ColumnState(
                    name="other",
                    definition="`other` INTEGER",
                    nullable=True,
                    storage="INTEGER",
                ),
            )
        }
    )
    package = m.compile(
        first.draft.model_copy(
            update={
                "target": m.State(backend="sqlite", tables=(child,)),
                "operations": (m.CreateTable(table=child),),
            }
        )
    )
    with TemporaryDirectory() as directory:
        config = sqlite.Config(database=Path(directory) / "composite.db")
        async with (
            await sqlite.Database.initialize(config) as db,
            db.transaction() as tx,
        ):
            await tx.execute(
                sqlite.raw(
                    "CREATE TABLE parents(id INTEGER,other INTEGER,PRIMARY KEY(id,other))"
                )
            )
            await tx.execute(sqlite.raw("INSERT INTO parents VALUES (7,8)"))
        async with m.connect(config) as target:
            if member == "missing":
                with assert_raises(m.PackageError) as error:
                    await target.prepare(package)
                assert "SQLite referenced member" in str(error.exception)
                return
            await target.apply(await target.prepare(package))
        async with (
            await sqlite.Database.initialize(config) as db,
            db.transaction() as tx,
        ):
            await tx.execute(sqlite.raw("INSERT INTO children VALUES (7,8)"))
        with assert_raises(ExecutionError):
            async with (
                await sqlite.Database.initialize(config) as db,
                db.transaction() as tx,
            ):
                await tx.execute(sqlite.raw("INSERT INTO children VALUES (7,9)"))


@test(mark="medium")
async def implicit_parent_key_resolution_remains_separate_from_explicit_members() -> (
    None
):
    """Retain a valid implicit table FK without claiming this gate solved key lookup."""
    package = _table_package(", FOREIGN KEY(parent_id) REFERENCES parents")
    with TemporaryDirectory() as directory:
        config = sqlite.Config(database=Path(directory) / "implicit.db")
        async with (
            await sqlite.Database.initialize(config) as db,
            db.transaction() as tx,
        ):
            await tx.execute(sqlite.raw("CREATE TABLE parents(id INTEGER PRIMARY KEY)"))
            await tx.execute(sqlite.raw("INSERT INTO parents VALUES (7)"))
        async with m.connect(config) as target:
            await target.apply(await target.prepare(package))
        async with (
            await sqlite.Database.initialize(config) as db,
            db.transaction() as tx,
        ):
            await tx.execute(sqlite.raw("INSERT INTO children VALUES (7)"))
        with assert_raises(ExecutionError):
            async with (
                await sqlite.Database.initialize(config) as db,
                db.transaction() as tx,
            ):
                await tx.execute(sqlite.raw("INSERT INTO children VALUES (8)"))


@test(
    [
        Param[str](value=body, name=str(index))
        for index, body in enumerate(("'id'", "id COLLATE BINARY", "id+0", "id,", ""))
    ],
    mark="medium",
)
async def unknown_explicit_member_roles_require_an_adapter(body: str) -> None:
    """String roles/expressions/options/malformed lists are not member-presence proof."""
    package = _table_package(f", FOREIGN KEY(parent_id) REFERENCES parents({body})")
    with TemporaryDirectory() as directory:
        config = sqlite.Config(database=Path(directory) / "adapter.db")
        async with (
            await sqlite.Database.initialize(config) as db,
            db.transaction() as tx,
        ):
            await tx.execute(sqlite.raw("CREATE TABLE parents(id INTEGER PRIMARY KEY)"))
        async with m.connect(config) as target:
            with assert_raises(m.PackageError) as error:
                await target.prepare(package)
            assert "SQLite referenced member" in str(error.exception)
            assert_eq(await target.status(), ())


@test(mark="medium")
async def same_frozen_contract_keeps_identity_and_depends_on_observed_parent_members() -> (
    None
):
    """Actual archived writer identity is retained, not rewritten to encode observations."""
    text = (
        Path(__file__).parent / "fixtures/sqlite-reference-members/frozen-old.json"
    ).read_text()
    package = m.Package.load(text)
    assert_eq(
        package.digest,
        "7a1f065a02941b376b04514bb4dc335965a3baf6a5f2193732348885df2e6704",
    )
    assert_eq(package.dump(), text)
    assert_eq(tuple(t.name for t in package.target.tables), ("children",))
    with TemporaryDirectory() as directory:
        config = sqlite.Config(database=Path(directory) / "frozen.db")
        async with (
            await sqlite.Database.initialize(config) as db,
            db.transaction() as tx,
        ):
            await tx.execute(
                sqlite.raw("CREATE TABLE parents(other INTEGER PRIMARY KEY)")
            )
        async with m.connect(config) as target:
            with assert_raises(m.PackageError) as error:
                await target.prepare(package)
            assert "SQLite referenced member" in str(error.exception)
            assert_eq(await target.status(), ())
        async with (
            await sqlite.Database.initialize(config) as db,
            db.transaction() as tx,
        ):
            await tx.execute(sqlite.raw("DROP TABLE parents"))
            await tx.execute(sqlite.raw("CREATE TABLE parents(id INTEGER PRIMARY KEY)"))
            await tx.execute(sqlite.raw("INSERT INTO parents VALUES (7)"))
        async with m.connect(config) as target:
            await target.apply(await target.prepare(package))
        assert_eq(package.dump(), text)
        async with (
            await sqlite.Database.initialize(config) as db,
            db.transaction() as tx,
        ):
            assert_eq(
                await tx.fetch_all(sqlite.raw("PRAGMA foreign_keys")),
                [{"foreign_keys": 1}],
            )
            await tx.execute(sqlite.raw("INSERT INTO children VALUES (7),(NULL)"))
        with assert_raises(ExecutionError):
            async with (
                await sqlite.Database.initialize(config) as db,
                db.transaction() as tx,
            ):
                await tx.execute(sqlite.raw("INSERT INTO children VALUES (999)"))


@test(
    [Param[str](value=phase, name=phase) for phase in ("prepared", "completed")],
    mark="medium",
)
async def parent_member_replacement_still_hits_independent_catalog_guards(
    phase: str,
) -> None:
    """Do not replace stale-plan/accepted-catalog proof with the new member observation."""
    first = _child_package()
    with TemporaryDirectory() as directory:
        config = sqlite.Config(database=Path(directory) / "drift.db")
        async with (
            await sqlite.Database.initialize(config) as db,
            db.transaction() as tx,
        ):
            await tx.execute(sqlite.raw("CREATE TABLE parents(id INTEGER PRIMARY KEY)"))
        async with m.connect(config) as target:
            plan = await target.prepare(first)
            if phase == "completed":
                await target.apply(plan)
        async with (
            await sqlite.Database.initialize(config) as db,
            db.transaction() as tx,
        ):
            await tx.execute(sqlite.raw("DROP TABLE parents"))
            await tx.execute(
                sqlite.raw("CREATE TABLE parents(other INTEGER PRIMARY KEY)")
            )
        async with m.connect(config) as target:
            with assert_raises(m.PackageError) as error:
                if phase == "prepared":
                    await target.apply(plan)
                else:
                    await target.prepare(
                        m.compile(
                            m.Draft(
                                revision="002",
                                predecessor=first.digest,
                                before=first.target,
                                target=first.target,
                                operations=(),
                            )
                        )
                    )
            if phase == "completed":
                assert "catalog differs from the last accepted execution" in str(
                    error.exception
                )
            else:
                assert_eq(await target.status(), ())

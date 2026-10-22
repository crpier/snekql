"""Explicit contraction through authoring, preparation, and execution."""

from pathlib import Path
from tempfile import TemporaryDirectory
from typing import ClassVar

import aiosqlite
from snektest import assert_eq, assert_raises, test

from snekql import sqlite
from snekql.experimental import migrations as m


class Expanded[S = sqlite.Pending](sqlite.Model[S]):
    """Historical expand state."""

    __tablename__ = "account"
    __row_type__: ClassVar[sqlite.ReadType[Expanded[sqlite.Row]]]
    id: sqlite.GenCol[int] = sqlite.Integer(
        primary_key=True, auto_increment=True, default=sqlite.PENDING_GENERATION
    )
    is_admin: sqlite.Col[bool] = sqlite.Integer()
    role: sqlite.Col[str | None] = sqlite.Text(nullable=True)


class Contracted[S = sqlite.Pending](sqlite.Model[S]):
    """Desired required-role state."""

    __tablename__ = "account"
    __row_type__: ClassVar[sqlite.ReadType[Contracted[sqlite.Row]]]
    id: sqlite.GenCol[int] = sqlite.Integer(
        primary_key=True, auto_increment=True, default=sqlite.PENDING_GENERATION
    )
    role: sqlite.Col[str] = sqlite.Text()


@test(mark="fast")
def contraction_requires_explicit_removal_and_groups_the_table_change() -> None:
    """A missing field alone cannot authorize deletion."""
    first = m.compile(m.generate("001", [Expanded], backend="sqlite"))
    draft = m.generate("002", [Contracted], backend="sqlite", previous=first)
    with assert_raises(m.PackageError):
        m.compile(draft)
    package = m.compile(
        draft.resolve(m.DropColumn(table_name="account", column_name="is_admin"))
    )
    assert_eq(package.statements, (None,))
    change = package.contractions[0]
    assert change is not None
    assert_eq(change.required, ("role",))
    assert_eq(change.dropped, ("is_admin",))
    assert_eq(m.Package.load(package.dump()), package)


@test(mark="medium")
async def sqlite_contraction_checks_data_then_preserves_rows_and_identity() -> None:
    """One prepared rebuild enforces the final contract without losing identity state."""

    first = m.compile(m.generate("001", [Expanded], backend="sqlite"))
    second = m.compile(
        m.generate("002", [Contracted], backend="sqlite", previous=first).resolve(
            m.DropColumn(table_name="account", column_name="is_admin")
        )
    )
    with TemporaryDirectory() as directory:
        config = sqlite.Config(database=Path(directory) / "app.db")
        async with m.connect(config) as target:
            await target.apply(await target.prepare(first))
            async with aiosqlite.connect(str(config.database)) as app:
                await app.execute("INSERT INTO account VALUES(1,1,NULL),(100,0,'user')")
                await app.execute("DELETE FROM account WHERE id=100")
                await app.commit()
            prepared = await target.prepare(second)
            with assert_raises(m.PackageError):
                await target.apply(prepared)
            assert_eq([p.revision for p in await target.status()], ["001"])
            async with aiosqlite.connect(str(config.database)) as app:
                await app.execute("UPDATE account SET role='admin' WHERE id=1")
                await app.commit()
            assert_eq(await target.apply(prepared), "applied")
            async with aiosqlite.connect(str(config.database)) as app:
                await app.execute("INSERT INTO account(role) VALUES('user')")
                assert_eq(
                    await (
                        await app.execute("SELECT id,role FROM account ORDER BY id")
                    ).fetchall(),
                    [(1, "admin"), (101, "user")],
                )
                assert_eq(
                    [
                        row[1]
                        for row in await (
                            await app.execute("PRAGMA table_info(account)")
                        ).fetchall()
                    ],
                    ["id", "role"],
                )
                with assert_raises(aiosqlite.IntegrityError):
                    await app.execute("INSERT INTO account(role) VALUES(NULL)")


@test(mark="medium")
async def sqlite_rebuild_preserves_explicitly_reviewed_unmanaged_structure() -> None:
    """Preserve extras, dependent data, views, working triggers and generated values."""

    first = m.compile(m.generate("001", [Expanded], backend="sqlite"))
    second = m.compile(
        m.generate("002", [Contracted], backend="sqlite", previous=first).resolve(
            m.DropColumn(table_name="account", column_name="is_admin")
        )
    )
    with TemporaryDirectory() as directory:
        config = sqlite.Config(database=Path(directory) / "app.db")
        async with m.connect(config) as target:
            await target.apply(await target.prepare(first))
            async with aiosqlite.connect(str(config.database)) as app:
                await app.executescript("""
                PRAGMA foreign_keys=ON;
                ALTER TABLE account ADD COLUMN extra TEXT COLLATE NOCASE NOT NULL DEFAULT 'kept' CHECK(extra <> 'forbidden');
                ALTER TABLE account ADD COLUMN upper_extra TEXT AS (upper(extra));
                CREATE TABLE child(parent INTEGER REFERENCES account(id) ON DELETE CASCADE);
                CREATE TABLE audit(value TEXT);
                CREATE INDEX extra_idx ON account(lower(extra)) WHERE extra <> '';
                CREATE TRIGGER audit_role AFTER UPDATE ON account BEGIN INSERT INTO audit VALUES(new.role); END;
                CREATE VIEW roles AS SELECT id,role,extra,upper_extra,'is_admin' AS label FROM account;
                INSERT INTO account(id,is_admin,role) VALUES(1,1,'admin'),(100,0,'user');
                DELETE FROM account WHERE id=100;
                INSERT INTO child VALUES(1);
                """)
            with assert_raises(m.PackageError):
                await target.prepare(second)
            plan = await target.prepare(second, preserve_unmanaged=True)
            await target.apply(plan)
            assert_eq(
                await target.apply(
                    await target.prepare(second, preserve_unmanaged=True)
                ),
                "already_applied",
            )
            async with aiosqlite.connect(str(config.database)) as app:
                assert_eq(
                    await (await app.execute("SELECT * FROM child")).fetchall(), [(1,)]
                )
                assert_eq(
                    await (await app.execute("SELECT * FROM roles")).fetchall(),
                    [(1, "admin", "kept", "KEPT", "is_admin")],
                )
                assert_eq(
                    await (await app.execute("SELECT * FROM audit")).fetchall(), []
                )
                await app.execute("UPDATE account SET role='owner' WHERE id=1")
                assert_eq(
                    await (await app.execute("SELECT * FROM audit")).fetchall(),
                    [("owner",)],
                )
                await app.execute("INSERT INTO account(role) VALUES('user')")
                assert_eq(
                    await (await app.execute("SELECT MAX(id) FROM account")).fetchall(),
                    [(101,)],
                )
                assert_eq(
                    await (await app.execute("PRAGMA foreign_key_check")).fetchall(), []
                )
                with assert_raises(aiosqlite.IntegrityError):
                    await app.execute(
                        "INSERT INTO account(role,extra) VALUES('user','FORBIDDEN')"
                    )
                indexes = await (
                    await app.execute("PRAGMA index_list(account)")
                ).fetchall()
                assert_eq([(row[1], row[4]) for row in indexes], [("extra_idx", 1)])


@test(mark="medium")
async def sqlite_preservation_refuses_dependencies_on_removed_columns() -> None:
    """Preserving objects must never silently discard a dependency on the old field."""
    first = m.compile(m.generate("001", [Expanded], backend="sqlite"))
    second = m.compile(
        m.generate("002", [Contracted], backend="sqlite", previous=first).resolve(
            m.DropColumn(table_name="account", column_name="is_admin")
        )
    )
    for ddl in (
        "CREATE INDEX old_flag ON account(is_admin)",
        "CREATE VIEW old_flag AS SELECT is_admin FROM account",
        "CREATE VIEW old_flag AS SELECT * FROM account",
        "CREATE TABLE events(value INTEGER); CREATE TRIGGER old_flag AFTER INSERT ON events BEGIN SELECT is_admin FROM account; END",
        "ALTER TABLE account ADD COLUMN old_flag INTEGER AS(is_admin)",
        "ALTER TABLE account RENAME COLUMN role TO renamed_role",
    ):
        with TemporaryDirectory() as directory:
            config = sqlite.Config(database=Path(directory) / "app.db")
            async with m.connect(config) as target:
                await target.apply(await target.prepare(first))
                async with aiosqlite.connect(str(config.database)) as app:
                    await app.executescript(ddl)
                    await app.commit()
                with assert_raises(m.PackageError):
                    await target.prepare(second, preserve_unmanaged=True)
                assert_eq([p.revision for p in await target.status()], ["001"])


class Original[S = sqlite.Pending](sqlite.Model[S]):
    """Original boolean-flag contract before expansion."""

    __tablename__ = "account"
    __row_type__: ClassVar[sqlite.ReadType[Original[sqlite.Row]]]
    id: sqlite.GenCol[int] = sqlite.Integer(
        primary_key=True, auto_increment=True, default=sqlite.PENDING_GENERATION
    )
    is_admin: sqlite.Col[bool] = sqlite.Integer()


@test(mark="medium")
async def sqlite_expansion_backfill_and_contraction_share_one_atomic_package() -> None:
    """Preparation projects earlier steps instead of requiring their live execution."""
    first = m.compile(m.generate("001", [Original], backend="sqlite"))
    expansion = m.generate("002", [Expanded], backend="sqlite", previous=first).then(
        m.Checkpoint(name="backfill")
    )
    contract = m.contract_digest(expansion, point="backfill")
    route = m.Draft(
        revision="002",
        predecessor=first.digest,
        before=first.target,
        target=m.generate("desired", [Contracted], backend="sqlite").target,
        operations=(
            *expansion.operations,
            m.DataChange.from_query(
                sqlite.update(Expanded)
                .set(Expanded.role.to("admin"))
                .where(Expanded.is_admin.eq(True)),
                checkpoint="backfill",
                contract_digest=contract,
            ),
            m.DataChange.from_query(
                sqlite.update(Expanded)
                .set(Expanded.role.to("user"))
                .where(Expanded.is_admin.eq(False)),
                checkpoint="backfill",
                contract_digest=contract,
            ),
            m.RequireNotNull(table_name="account", column_name="role"),
            m.DropColumn(table_name="account", column_name="is_admin"),
            m.Checkpoint(name="final"),
        ),
    )
    package = m.compile(route)
    final_contract = m.contract_source(route, point="final", table="account")
    assert "is_admin" not in final_contract
    assert "sqlite.Col[str]" in final_contract
    with TemporaryDirectory() as directory:
        config = sqlite.Config(database=Path(directory) / "app.db")
        async with m.connect(config) as target:
            await target.apply(await target.prepare(first))
            async with aiosqlite.connect(str(config.database)) as app:
                await app.execute("INSERT INTO account VALUES(1,1),(2,0)")
                await app.commit()
            await target.apply(await target.prepare(package))
            async with aiosqlite.connect(str(config.database)) as app:
                assert_eq(
                    await (
                        await app.execute("SELECT * FROM account ORDER BY id")
                    ).fetchall(),
                    [(1, "admin"), (2, "user")],
                )


class KeyedBefore[S = sqlite.Pending](sqlite.Model[S]):
    """A natural-key table whose recorded storage uses WITHOUT ROWID."""

    __tablename__ = "keyed"
    __row_type__: ClassVar[sqlite.ReadType[KeyedBefore[sqlite.Row]]]
    key: sqlite.Col[str] = sqlite.Text(primary_key=True)
    old: sqlite.Col[bool] = sqlite.Integer()
    value: sqlite.Col[str | None] = sqlite.Text(nullable=True)


class KeyedAfter[S = sqlite.Pending](sqlite.Model[S]):
    """Final natural-key contract."""

    __tablename__ = "keyed"
    __row_type__: ClassVar[sqlite.ReadType[KeyedAfter[sqlite.Row]]]
    key: sqlite.Col[str] = sqlite.Text(primary_key=True)
    value: sqlite.Col[str] = sqlite.Text()


@test(mark="medium")
async def sqlite_rebuild_preserves_recorded_without_rowid_and_strict_storage() -> None:
    """A recorded physical contract need not use the model generator's table options."""
    before = m.generate("001", [KeyedBefore], backend="sqlite")
    table = before.target.tables[0]
    table = table.model_copy(update={"sql": table.sql + ", WITHOUT ROWID"})
    before = before.model_copy(
        update={
            "target": m.State(backend="sqlite", tables=(table,)),
            "operations": (m.CreateTable(table=table),),
        }
    )
    first = m.compile(before)
    after = m.generate("desired", [KeyedAfter], backend="sqlite").target.tables[0]
    after = after.model_copy(update={"sql": after.sql + ", WITHOUT ROWID"})
    second = m.compile(
        m.Draft(
            revision="002",
            predecessor=first.digest,
            before=first.target,
            target=m.State(backend="sqlite", tables=(after,)),
            operations=(
                m.RequireNotNull(table_name="keyed", column_name="value"),
                m.DropColumn(table_name="keyed", column_name="old"),
            ),
        )
    )
    with TemporaryDirectory() as directory:
        config = sqlite.Config(database=Path(directory) / "app.db")
        async with m.connect(config) as target:
            await target.apply(await target.prepare(first))
            async with aiosqlite.connect(str(config.database)) as app:
                await app.execute("INSERT INTO keyed VALUES('key',1,'kept')")
                await app.commit()
            await target.apply(await target.prepare(second))
            async with aiosqlite.connect(str(config.database)) as app:
                assert_eq(
                    await (await app.execute("SELECT * FROM keyed")).fetchall(),
                    [("key", "kept")],
                )
                row = next(
                    row
                    for row in await (await app.execute("PRAGMA table_list")).fetchall()
                    if row[1] == "keyed"
                )
                assert_eq(row[4:6], (1, 1))


@test(mark="medium")
async def sqlite_removal_rejects_legacy_quoted_trigger_event_columns() -> None:
    """UPDATE OF 'column' is a dependency even when the body never reads it."""
    first = m.compile(m.generate("001", [Expanded], backend="sqlite"))
    second = m.compile(
        m.generate("002", [Contracted], backend="sqlite", previous=first).resolve(
            m.DropColumn(table_name="account", column_name="is_admin")
        )
    )
    with TemporaryDirectory() as directory:
        config = sqlite.Config(database=Path(directory) / "app.db")
        async with m.connect(config) as target:
            await target.apply(await target.prepare(first))
            async with aiosqlite.connect(str(config.database)) as app:
                await app.executescript("""
                    CREATE TABLE audit(value INTEGER);
                    CREATE TRIGGER begin AFTER UPDATE OF 'is_admin' ON account
                    BEGIN INSERT INTO audit VALUES(1); END;
                    INSERT INTO account(id,is_admin,role) VALUES(1,1,'user');
                    UPDATE account SET is_admin=0;
                """)
                assert_eq(
                    await (await app.execute("SELECT value FROM audit")).fetchall(),
                    [(1,)],
                )
            with assert_raises(m.PackageError):
                await target.prepare(second, preserve_unmanaged=True)
            assert_eq([p.revision for p in await target.status()], ["001"])


@test(mark="medium")
async def sqlite_removal_rejects_legacy_qualified_trigger_columns() -> None:
    """NEW.'column' names a row field, not a harmless string literal."""
    first = m.compile(m.generate("001", [Expanded], backend="sqlite"))
    second = m.compile(
        m.generate("002", [Contracted], backend="sqlite", previous=first).resolve(
            m.DropColumn(table_name="account", column_name="is_admin")
        )
    )
    with TemporaryDirectory() as directory:
        config = sqlite.Config(database=Path(directory) / "app.db")
        async with m.connect(config) as target:
            await target.apply(await target.prepare(first))
            async with aiosqlite.connect(str(config.database)) as app:
                await app.executescript("""
                    CREATE TABLE audit(value INTEGER);
                    CREATE TRIGGER track_change AFTER UPDATE OF role ON account
                    BEGIN INSERT INTO audit VALUES(NEW.'is_admin'); END;
                    INSERT INTO account(id,is_admin,role) VALUES(1,1,'user');
                    UPDATE account SET role='admin';
                """)
                assert_eq(
                    await (await app.execute("SELECT value FROM audit")).fetchall(),
                    [(1,)],
                )
            with assert_raises(m.PackageError):
                await target.prepare(second, preserve_unmanaged=True)


@test(mark="medium")
async def sqlite_rebuild_retains_legacy_trigger_names_and_genuine_string_literals() -> (
    None
):
    """Retained event columns and literal labels keep their behavior after rebuild."""
    first = m.compile(m.generate("001", [Expanded], backend="sqlite"))
    second = m.compile(
        m.generate("002", [Contracted], backend="sqlite", previous=first).resolve(
            m.DropColumn(table_name="account", column_name="is_admin")
        )
    )
    with TemporaryDirectory() as directory:
        config = sqlite.Config(database=Path(directory) / "app.db")
        async with m.connect(config) as target:
            await target.apply(await target.prepare(first))
            async with aiosqlite.connect(str(config.database)) as app:
                await app.executescript("""
                    CREATE TABLE audit(value TEXT);
                    CREATE TRIGGER record_label AFTER UPDATE OF 'role' ON 'account'
                    BEGIN INSERT INTO audit VALUES('is_admin'); END;
                    INSERT INTO account(id,is_admin,role) VALUES(1,1,'user');
                """)
            await target.apply(await target.prepare(second, preserve_unmanaged=True))
            async with aiosqlite.connect(str(config.database)) as app:
                assert_eq(
                    await (await app.execute("SELECT value FROM audit")).fetchall(), []
                )
                await app.execute("UPDATE account SET role='admin'")
                assert_eq(
                    await (await app.execute("SELECT value FROM audit")).fetchall(),
                    [("is_admin",)],
                )
                assert_eq(
                    await (await app.execute("SELECT id,role FROM account")).fetchall(),
                    [(1, "admin")],
                )


@test(mark="medium")
async def sqlite_same_package_rebuild_preserves_keyword_named_unique_index() -> None:
    """An index named 'on' must retain both its identity and uniqueness enforcement."""
    index = 'CREATE UNIQUE INDEX "on" ON "account" ("role")'
    before = (
        m.generate("before", [Expanded], backend="sqlite")
        .target.tables[0]
        .model_copy(update={"indexes": (index,)})
    )
    after = (
        m.generate("after", [Contracted], backend="sqlite")
        .target.tables[0]
        .model_copy(update={"indexes": (index,)})
    )
    package = m.compile(
        m.Draft(
            revision="001",
            predecessor=None,
            before=m.State(backend="sqlite"),
            target=m.State(backend="sqlite", tables=(after,)),
            operations=(
                m.CreateTable(table=before),
                m.RequireNotNull(table_name="account", column_name="role"),
                m.DropColumn(table_name="account", column_name="is_admin"),
            ),
        )
    )
    with TemporaryDirectory() as directory:
        config = sqlite.Config(database=Path(directory) / "app.db")
        async with m.connect(config) as target:
            await target.apply(await target.prepare(package))
            async with aiosqlite.connect(str(config.database)) as app:
                await app.execute("INSERT INTO account(role) VALUES('user')")
                with assert_raises(aiosqlite.IntegrityError):
                    await app.execute("INSERT INTO account(role) VALUES('user')")
                assert_eq(
                    await (
                        await app.execute(
                            "SELECT name FROM sqlite_schema WHERE type='index' AND name='on'"
                        )
                    ).fetchall(),
                    [("on",)],
                )


@test(mark="medium")
async def sqlite_rebuild_copies_unicode_columns_that_resemble_keywords() -> None:
    """A bare chec-Kelvin-sign column is not a CHECK constraint; its values survive."""
    first = m.compile(m.generate("001", [Expanded], backend="sqlite"))
    second = m.compile(
        m.generate("002", [Contracted], backend="sqlite", previous=first).resolve(
            m.DropColumn(table_name="account", column_name="is_admin"),
        )
    )
    with TemporaryDirectory() as directory:
        config = sqlite.Config(database=Path(directory) / "app.db")
        async with m.connect(config) as target:
            await target.apply(await target.prepare(first))
            async with aiosqlite.connect(str(config.database)) as app:
                await app.execute("ALTER TABLE account ADD COLUMN chec\u212a TEXT")
                await app.execute(
                    "ALTER TABLE account ADD COLUMN tag TEXT DEFAULT a\u017f"
                )
                await app.execute(
                    "ALTER TABLE account ADD COLUMN plain TEXT DEFAULT GENERATED"
                )
                await app.execute(
                    "INSERT INTO account VALUES(1,1,'admin','must survive','also kept','literal default')"
                )
                await app.commit()
            await target.apply(await target.prepare(second, preserve_unmanaged=True))
            async with aiosqlite.connect(str(config.database)) as app:
                assert_eq(
                    await (
                        await app.execute("SELECT chec\u212a,tag,plain FROM account")
                    ).fetchall(),
                    [("must survive", "also kept", "literal default")],
                )


@test(mark="medium")
async def sqlite_rebuild_keeps_non_ascii_identifier_tokens_whole() -> None:
    """Combining marks, non-ASCII spaces and symbols are SQLite identifier characters."""
    first = m.compile(m.generate("001", [Expanded], backend="sqlite"))
    second = m.compile(
        m.generate("002", [Contracted], backend="sqlite", previous=first).resolve(
            m.DropColumn(table_name="account", column_name="is_admin"),
        )
    )
    with TemporaryDirectory() as directory:
        config = sqlite.Config(database=Path(directory) / "app.db")
        async with m.connect(config) as target:
            await target.apply(await target.prepare(first))
            async with aiosqlite.connect(str(config.database)) as app:
                await app.executescript(
                    "ALTER TABLE account ADD COLUMN legacy\u0301AS TEXT;"
                    "ALTER TABLE account ADD COLUMN legacy\u00a0AS TEXT;"
                    "ALTER TABLE account ADD COLUMN legacy\U0001f40dAS TEXT;"
                    "INSERT INTO account VALUES(1,1,'admin','combining','space','symbol');"
                )
            await target.apply(await target.prepare(second, preserve_unmanaged=True))
            async with aiosqlite.connect(str(config.database)) as app:
                assert_eq(
                    await (
                        await app.execute(
                            "SELECT legacy\u0301AS,legacy\u00a0AS,legacy\U0001f40dAS FROM account"
                        )
                    ).fetchall(),
                    [("combining", "space", "symbol")],
                )


@test(mark="medium")
async def sqlite_copy_plan_must_agree_with_engine_column_metadata() -> None:
    """A valid but unrecognized BOM spelling stops safely before the copy executes."""
    first = m.compile(m.generate("001", [Expanded], backend="sqlite"))
    second = m.compile(
        m.generate("002", [Contracted], backend="sqlite", previous=first).resolve(
            m.DropColumn(table_name="account", column_name="is_admin"),
        )
    )
    with TemporaryDirectory() as directory:
        config = sqlite.Config(database=Path(directory) / "app.db")
        async with m.connect(config) as target:
            await target.apply(await target.prepare(first))
            async with aiosqlite.connect(str(config.database)) as app:
                await app.execute("DROP TABLE account")
                await app.execute(
                    first.target.tables[0].sql.removesuffix(") STRICT")
                    + ", \ufeffextra TEXT) STRICT"
                )
                await app.execute("INSERT INTO account VALUES(1,1,'admin','kept')")
                await app.commit()
            plan = await target.prepare(second, preserve_unmanaged=True)
            with assert_raises(m.PackageError) as error:
                await target.apply(plan)
            assert "copy contract" in str(error.exception)
            assert_eq([p.revision for p in await target.status()], ["001"])
            async with aiosqlite.connect(str(config.database)) as app:
                assert_eq(
                    await (
                        await app.execute("SELECT is_admin,extra FROM account")
                    ).fetchall(),
                    [(1, "kept")],
                )


@test(mark="medium")
async def sqlite_copy_contract_preserves_generated_values_and_requires_reviewed_plans() -> (
    None
):
    """Engine classification covers virtual/stored columns without copying generated data."""
    first = m.compile(m.generate("001", [Expanded], backend="sqlite"))
    second = m.compile(
        m.generate("002", [Contracted], backend="sqlite", previous=first).resolve(
            m.DropColumn(table_name="account", column_name="is_admin"),
        )
    )
    with TemporaryDirectory() as directory:
        config = sqlite.Config(database=Path(directory) / "app.db")
        async with m.connect(config) as target:
            await target.apply(await target.prepare(first))
            async with aiosqlite.connect(str(config.database)) as app:
                await app.execute(
                    "ALTER TABLE account ADD COLUMN upper_role TEXT AS(upper(role)) VIRTUAL"
                )
                await app.execute(
                    "ALTER TABLE account ADD COLUMN role_size INTEGER GENERATED ALWAYS AS(length(role)) STORED"
                )
                await app.execute(
                    "INSERT INTO account(id,is_admin,role) VALUES(1,1,'admin')"
                )
                await app.commit()
            plan = await target.prepare(second, preserve_unmanaged=True)
            legacy = plan.model_dump(mode="json")
            for step in legacy["steps"]:
                step.pop("copy_columns", None)
                step.pop("dropped_columns", None)
            with assert_raises(m.PackageError) as error:
                await target.apply(m.Prepared.model_validate(legacy))
            assert "prepared execution steps have changed" in str(error.exception)
            assert_eq([p.revision for p in await target.status()], ["001"])
            async with aiosqlite.connect(str(config.database)) as app:
                await app.execute(
                    "INSERT INTO account(id,is_admin,role) VALUES(2,0,'owner')"
                )
                await app.commit()
            await target.apply(plan)
            async with aiosqlite.connect(str(config.database)) as app:
                assert_eq(
                    await (
                        await app.execute(
                            "SELECT id,upper_role,role_size FROM account ORDER BY id"
                        )
                    ).fetchall(),
                    [(1, "ADMIN", 5), (2, "OWNER", 5)],
                )
                await app.execute("UPDATE account SET role='user' WHERE id=1")
                assert_eq(
                    await (
                        await app.execute(
                            "SELECT upper_role,role_size FROM account WHERE id=1"
                        )
                    ).fetchall(),
                    [("USER", 4)],
                )

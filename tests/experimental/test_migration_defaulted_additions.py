"""Explicit old-row policy for frozen nullable/default additions."""

from pathlib import Path
from sqlite3 import IntegrityError
from tempfile import TemporaryDirectory
from typing import ClassVar, Literal

import aiosqlite
from pymysql.err import OperationalError
from snektest import Param, assert_eq, assert_raises, load_fixture, test

from snekql import mariadb, sqlite
from snekql.experimental import migrations as m
from tests.experimental.test_migration_targets import provide_package_server


class Initial[S = sqlite.Pending](sqlite.Model[S]):
    """Populated table before the new column exists."""

    __tablename__ = "entries"
    __row_type__: ClassVar[sqlite.ReadType[Initial[sqlite.Row]]]
    id: sqlite.Col[int] = sqlite.Integer(primary_key=True)


class Added[S = sqlite.Pending](sqlite.Model[S]):
    """A future-write default does not decide how to populate existing rows."""

    __tablename__ = "entries"
    __row_type__: ClassVar[sqlite.ReadType[Added[sqlite.Row]]]
    id: sqlite.Col[int] = sqlite.Integer(primary_key=True)
    value: sqlite.GenCol[int | None] = sqlite.Integer(
        nullable=True, default=sqlite.LiteralDefault(7)
    )


@test(mark="medium")
async def sqlite_defaulted_addition_leaves_old_rows_null_only_by_explicit_policy() -> (
    None
):
    """Frozen deployment preserves old NULLs and defaults only future omitted values."""
    first = m.compile(m.generate("001", [Initial], backend="sqlite"))
    undecided = m.generate("002", [Added], backend="sqlite", previous=first)
    with assert_raises(m.PackageError):
        m.compile(undecided)
    draft = m.generate(
        "002",
        [Added],
        backend="sqlite",
        previous=first,
        defaulted_additions="leave_null",
    )
    second = m.Package.load(m.compile(draft).dump())
    assert_eq(second.version, 3)
    with TemporaryDirectory() as directory:
        config = sqlite.Config(database=Path(directory) / "add.db")
        async with m.connect(config) as target:
            await target.apply(await target.prepare(first))
        async with (
            await sqlite.Database.initialize(config) as db,
            db.transaction() as tx,
        ):
            await tx.execute(sqlite.raw("INSERT INTO entries(id) VALUES(1)"))
        async with m.connect(config) as target:
            await target.apply(await target.prepare(second))
            assert_eq(
                await target.apply(await target.prepare(second)), "already_applied"
            )
        async with (
            await sqlite.Database.initialize(config) as db,
            db.transaction() as tx,
        ):
            await tx.execute(sqlite.raw("INSERT INTO entries(id) VALUES(2)"))
            await tx.execute(sqlite.raw("INSERT INTO entries VALUES(3,NULL)"))
            assert_eq(
                await tx.fetch_all(sqlite.raw("SELECT value FROM entries ORDER BY id")),
                [{"value": None}, {"value": 7}, {"value": None}],
            )


class NativeInitial[S = mariadb.Pending](mariadb.Model[S]):
    """Native populated table without the new field."""

    __tablename__ = "entries"
    __row_type__: ClassVar[mariadb.ReadType[NativeInitial[mariadb.Row]]]
    id: mariadb.Col[int] = mariadb.Integer(primary_key=True)


class NativeAdded[S = mariadb.Pending](mariadb.Model[S]):
    """Native nullable addition with a future-write default."""

    __tablename__ = "entries"
    __row_type__: ClassVar[mariadb.ReadType[NativeAdded[mariadb.Row]]]
    id: mariadb.Col[int] = mariadb.Integer(primary_key=True)
    value: mariadb.GenCol[int | None] = mariadb.Integer(
        nullable=True, default=mariadb.LiteralDefault(7)
    )


@test(mark="slow")
async def native_defaulted_addition_leaves_old_rows_null_only_by_explicit_policy() -> (
    None
):
    """Native ADD must not silently materialize its server default in old rows."""
    server = await load_fixture(provide_package_server())
    first = m.compile(m.generate("001", [NativeInitial], backend="mariadb"))
    with assert_raises(m.PackageError):
        m.compile(m.generate("002", [NativeAdded], backend="mariadb", previous=first))
    second = m.Package.load(
        m.compile(
            m.generate(
                "002",
                [NativeAdded],
                backend="mariadb",
                previous=first,
                defaulted_additions="leave_null",
            )
        ).dump()
    )
    async with m.connect(server.config()) as target:
        await target.apply(await target.prepare(first, schema_writers_excluded=True))
    await server.run_sql("INSERT INTO entries(id) VALUES(1)")
    async with m.connect(server.config()) as target:
        await target.apply(await target.prepare(second, schema_writers_excluded=True))
        assert_eq(
            await target.apply(
                await target.prepare(second, schema_writers_excluded=True)
            ),
            "already_applied",
        )
    async with (
        await mariadb.Database.initialize(server.config()) as db,
        db.transaction() as tx,
    ):
        await tx.execute(mariadb.raw("INSERT INTO entries(id) VALUES(2)"))
        await tx.execute(mariadb.raw("INSERT INTO entries VALUES(3,NULL)"))
        assert_eq(
            await tx.fetch_all(mariadb.raw("SELECT value FROM entries ORDER BY id")),
            [{"value": None}, {"value": 7}, {"value": None}],
        )


class Required[S = sqlite.Pending](sqlite.Model[S]):
    """A required default is not permission to fill existing rows."""

    __tablename__ = "entries"
    __row_type__: ClassVar[sqlite.ReadType[Required[sqlite.Row]]]
    id: sqlite.Col[int] = sqlite.Integer(primary_key=True)
    value: sqlite.GenCol[int] = sqlite.Integer(default=sqlite.LiteralDefault(7))


class NativeRequired[S = mariadb.Pending](mariadb.Model[S]):
    """Native required addition also needs a separate data policy."""

    __tablename__ = "entries"
    __row_type__: ClassVar[mariadb.ReadType[NativeRequired[mariadb.Row]]]
    id: mariadb.Col[int] = mariadb.Integer(primary_key=True)
    value: mariadb.GenCol[int] = mariadb.Integer(default=mariadb.LiteralDefault(7))


@test(
    [
        Param[Literal["sqlite", "mariadb"]](value="sqlite", name="sqlite"),
        Param[Literal["sqlite", "mariadb"]](value="mariadb", name="native"),
    ],
    mark="fast",
)
def leave_null_does_not_authorize_required_additions(
    backend: Literal["sqlite", "mariadb"],
) -> None:
    """Generation leaves unsupported required additions unresolved, never partial."""
    initial = Initial if backend == "sqlite" else NativeInitial
    required = Required if backend == "sqlite" else NativeRequired
    first = m.compile(m.generate("001", [initial], backend=backend))
    draft = m.generate(
        "002",
        [required],
        backend=backend,
        previous=first,
        defaulted_additions="leave_null",
    )
    assert draft.unresolved
    assert_eq(draft.operations, ())
    with assert_raises(m.PackageError):
        m.compile(draft)


@test(mark="slow")
async def native_addition_receipt_survives_a_lost_default_receipt() -> None:
    """Recovery must not replay an acknowledged ADD or infer a missing default receipt."""
    server = await load_fixture(provide_package_server())
    first = m.compile(m.generate("001", [NativeInitial], backend="mariadb"))
    second = m.Package.load(
        m.compile(
            m.generate(
                "002",
                [NativeAdded],
                backend="mariadb",
                previous=first,
                defaulted_additions="leave_null",
            )
        ).dump()
    )
    async with m.connect(server.config()) as target:
        await target.apply(await target.prepare(first, schema_writers_excluded=True))
    await server.run_sql("INSERT INTO entries(id) VALUES(1)")
    await server.run_sql(
        "DELIMITER //\nCREATE TRIGGER fail_default_receipt BEFORE UPDATE ON snekql_experimental_migrations FOR EACH ROW BEGIN IF NEW.acknowledged=2 THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='default receipt unavailable'; END IF; END//\nDELIMITER ;"
    )
    async with m.connect(server.config()) as target:
        plan = await target.prepare(second, schema_writers_excluded=True)
        with assert_raises(OperationalError):
            await target.apply(plan)
    await server.run_sql("DROP TRIGGER fail_default_receipt")
    async with m.connect(server.config()) as target:
        recovery = await target.inspect_recovery(plan, schema_writers_excluded=True)
        assert_eq(recovery.acknowledged_steps, 1)
        assert_eq(recovery.disposition, "ambiguous")
        with assert_raises(m.PackageError):
            await target.resume(recovery, schema_writers_excluded=True)
    # Deliberate operator restoration to the acknowledged schema, not auto-repair.
    await server.run_sql("ALTER TABLE entries ALTER COLUMN value DROP DEFAULT")
    async with m.connect(server.config()) as target:
        recovery = await target.inspect_recovery(plan, schema_writers_excluded=True)
        assert_eq(recovery.disposition, "retry_remaining")
        assert_eq(recovery.acknowledged_steps, 1)
        await target.resume(recovery, schema_writers_excluded=True)
        assert_eq(
            await target.apply(
                await target.prepare(second, schema_writers_excluded=True)
            ),
            "already_applied",
        )
    async with (
        await mariadb.Database.initialize(server.config()) as db,
        db.transaction() as tx,
    ):
        await tx.execute(mariadb.raw("INSERT INTO entries(id) VALUES(2)"))
        assert_eq(
            await tx.fetch_all(mariadb.raw("SELECT value FROM entries ORDER BY id")),
            [{"value": None}, {"value": 7}],
        )


@test(mark="medium")
async def sqlite_defaulted_addition_rolls_back_and_preserves_unmanaged_objects() -> (
    None
):
    """ADD plus rebuild is atomic with later data work and retains unmanaged behavior."""
    first = m.compile(m.generate("001", [Initial], backend="sqlite"))
    draft = m.generate(
        "002",
        [Added],
        backend="sqlite",
        previous=first,
        defaulted_additions="leave_null",
    ).then(m.Checkpoint(name="added"))
    second = m.Package.load(
        m.compile(
            draft.then(
                m.DataChange.from_query(
                    sqlite.update(Added).set(Added.id.to(42)).all(),
                    checkpoint="added",
                    contract_digest=m.contract_digest(draft, point="added"),
                )
            )
        ).dump()
    )
    with TemporaryDirectory() as directory:
        config = sqlite.Config(database=Path(directory) / "preserved.db")
        async with m.connect(config) as target:
            await target.apply(await target.prepare(first))
        async with aiosqlite.connect(config.database) as setup:
            await setup.executescript("""
            ALTER TABLE entries ADD COLUMN legacy BLOB DEFAULT X'00ff';
            CREATE INDEX legacy_idx ON entries(legacy);
            CREATE VIEW legacy_view AS SELECT id,legacy FROM entries;
            CREATE TABLE events(id INTEGER);
            CREATE TRIGGER inserted AFTER INSERT ON entries BEGIN INSERT INTO events VALUES(NEW.id); END;
            INSERT INTO entries(id) VALUES(1),(2);
            """)
        async with m.connect(config) as target:
            plan = await target.prepare(second, preserve_unmanaged=True)
            with assert_raises(IntegrityError):
                await target.apply(plan)
            assert_eq(len(await target.status()), 1)
        async with (
            await sqlite.Database.initialize(config) as db,
            db.transaction() as tx,
        ):
            assert_eq(
                [
                    row["name"]
                    for row in await tx.fetch_all(
                        sqlite.raw("PRAGMA table_info(entries)")
                    )
                ],
                ["id", "legacy"],
            )
            assert_eq(
                await tx.fetch_all(sqlite.raw("SELECT id FROM events ORDER BY id")),
                [{"id": 1}, {"id": 2}],
            )
            await tx.execute(sqlite.raw("DELETE FROM entries WHERE id=2"))
        async with m.connect(config) as target:
            await target.apply(plan)
        async with (
            await sqlite.Database.initialize(config) as db,
            db.transaction() as tx,
        ):
            await tx.execute(sqlite.raw("INSERT INTO entries(id) VALUES(3)"))
            assert_eq(
                await tx.fetch_all(
                    sqlite.raw("SELECT id,value,legacy FROM entries ORDER BY id")
                ),
                [
                    {"id": 3, "value": 7, "legacy": b"\x00\xff"},
                    {"id": 42, "value": None, "legacy": b"\x00\xff"},
                ],
            )
            assert_eq(
                await tx.fetch_all(sqlite.raw("SELECT id FROM events ORDER BY id")),
                [{"id": 1}, {"id": 2}, {"id": 3}],
            )
            assert_eq(
                await tx.fetch_all(
                    sqlite.raw("SELECT id FROM legacy_view ORDER BY id")
                ),
                [{"id": 3}, {"id": 42}],
            )
            assert any(
                row["name"] == "legacy_idx"
                for row in await tx.fetch_all(sqlite.raw("PRAGMA index_list(entries)"))
            )


class Mixed[S = sqlite.Pending](sqlite.Model[S]):
    """Encoded, explicit NULL and clock defaults on several new nullable columns."""

    __tablename__ = "entries"
    __row_type__: ClassVar[sqlite.ReadType[Mixed[sqlite.Row]]]
    id: sqlite.Col[int] = sqlite.Integer(primary_key=True)
    text: sqlite.GenCol[str | None] = sqlite.Text(
        nullable=True, default=sqlite.LiteralDefault("DEFAULT '\\ \0é")
    )
    empty: sqlite.GenCol[int | None] = sqlite.Integer(
        nullable=True, default=sqlite.LiteralDefault(None)
    )
    clock: sqlite.GenCol[sqlite.UtcDatetime | None] = sqlite.Text(
        nullable=True, default=sqlite.CurrentTimestamp
    )


class NativeMixed[S = mariadb.Pending](mariadb.Model[S]):
    """The same data policy includes a native DATETIME clock."""

    __tablename__ = "entries"
    __row_type__: ClassVar[mariadb.ReadType[NativeMixed[mariadb.Row]]]
    id: mariadb.Col[int] = mariadb.Integer(primary_key=True)
    text: mariadb.GenCol[str | None] = mariadb.Text(
        nullable=True, default=mariadb.LiteralDefault("DEFAULT '\\ \0é")
    )
    empty: mariadb.GenCol[int | None] = mariadb.Integer(
        nullable=True, default=mariadb.LiteralDefault(None)
    )
    clock: mariadb.GenCol[mariadb.UtcDatetime | None] = mariadb.DateTime(
        nullable=True, default=mariadb.CurrentTimestamp
    )


@test(mark="medium")
async def sqlite_multiple_defaulted_additions_do_not_materialize_defaults_in_old_rows() -> (
    None
):
    """Clock and encoded defaults follow the same old-row policy as scalars."""
    first = m.compile(m.generate("001", [Initial], backend="sqlite"))
    second = m.Package.load(
        m.compile(
            m.generate(
                "002",
                [Mixed],
                backend="sqlite",
                previous=first,
                defaulted_additions="leave_null",
            )
        ).dump()
    )
    with TemporaryDirectory() as directory:
        config = sqlite.Config(database=Path(directory) / "mixed.db")
        async with m.connect(config) as target:
            await target.apply(await target.prepare(first))
        async with (
            await sqlite.Database.initialize(config) as db,
            db.transaction() as tx,
        ):
            await tx.execute(sqlite.raw("INSERT INTO entries VALUES(1)"))
        async with m.connect(config) as target:
            await target.apply(await target.prepare(second))
        async with (
            await sqlite.Database.initialize(config) as db,
            db.transaction() as tx,
        ):
            await tx.execute(sqlite.raw("INSERT INTO entries(id) VALUES(2)"))
            rows = await tx.fetch_all(
                sqlite.raw("SELECT text,empty,clock FROM entries ORDER BY id")
            )
            assert_eq(rows[0], {"text": None, "empty": None, "clock": None})
            assert_eq(rows[1]["text"], "DEFAULT '\\ \0é")
            assert_eq(rows[1]["empty"], None)
            assert rows[1]["clock"] is not None


@test(mark="slow")
async def native_multiple_defaulted_additions_do_not_materialize_defaults_in_old_rows() -> (
    None
):
    """Native text, NULL and clock additions preserve old NULLs, not creation-time defaults."""
    server = await load_fixture(provide_package_server())
    first = m.compile(m.generate("001", [NativeInitial], backend="mariadb"))
    second = m.Package.load(
        m.compile(
            m.generate(
                "002",
                [NativeMixed],
                backend="mariadb",
                previous=first,
                defaulted_additions="leave_null",
            )
        ).dump()
    )
    async with m.connect(server.config()) as target:
        await target.apply(await target.prepare(first, schema_writers_excluded=True))
    await server.run_sql("INSERT INTO entries VALUES(1)")
    async with m.connect(server.config()) as target:
        await target.apply(await target.prepare(second, schema_writers_excluded=True))
    async with (
        await mariadb.Database.initialize(server.config()) as db,
        db.transaction() as tx,
    ):
        await tx.execute(mariadb.raw("INSERT INTO entries(id) VALUES(2)"))
        rows = await tx.fetch_all(
            mariadb.raw("SELECT text,empty,clock FROM entries ORDER BY id")
        )
        assert_eq(rows[0], {"text": None, "empty": None, "clock": None})
        assert_eq(rows[1]["text"], "DEFAULT '\\ \0é")
        assert_eq(rows[1]["empty"], None)
        assert rows[1]["clock"] is not None

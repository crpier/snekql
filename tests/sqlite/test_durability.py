"""SQLite durability policy through Config and managed Transactions."""

from collections.abc import AsyncGenerator, Iterable
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from aiosqlite import Connection, Cursor
from snektest import (
    Param,
    assert_eq,
    assert_in,
    assert_raises,
    fixture,
    load_fixture,
    test,
)

from snekql import sqlite


@fixture
async def provide_database_path() -> AsyncGenerator[Path]:
    """Keep a file-backed database alive through connection replacement."""
    with TemporaryDirectory() as directory:
        yield Path(directory) / "durability.db"


@test(mark="medium")
async def full_policy_applies_to_initial_connection() -> None:
    """FULL requests SQLite's extra WAL synchronization at commit."""
    path = await load_fixture(provide_database_path())
    database = await sqlite.Database.initialize(
        sqlite.Config(database=path, durability="full")
    )
    try:
        async with database.transaction() as transaction:
            rows = await transaction.fetch_all(sqlite.raw("PRAGMA synchronous"))
        assert_eq(rows, [{"synchronous": 2}])
    finally:
        await database.close()


@test(mark="medium")
async def additional_connections_keep_full_policy() -> None:
    """A concurrent lease must not fall back to NORMAL during lazy pool growth."""
    path = await load_fixture(provide_database_path())
    database = await sqlite.Database.initialize(
        sqlite.Config(database=path, durability="full", pool_size=2)
    )
    try:
        async with database.transaction(), database.transaction() as second:
            rows = await second.fetch_all(sqlite.raw("PRAGMA synchronous"))
        assert_eq(rows, [{"synchronous": 2}])
    finally:
        await database.close()


@test(
    [
        Param("off", name="off"),
        Param("extra", name="extra"),
        Param("FULL", name="uppercase"),
        Param(None, name="none"),
        Param(2, name="numeric"),
        Param(True, name="boolean"),
    ],
    mark="fast",
)
def unsupported_durability_is_rejected(durability: object) -> None:
    """Dynamic callers cannot bypass the two supported policy values."""
    with assert_raises(sqlite.DatabaseRuntimeError):
        sqlite.Config(database=Path("app.db"), durability=durability)  # ty: ignore[invalid-argument-type]


@test(mark="fast")
def full_policy_rejects_in_memory_database() -> None:
    """FULL must not pretend that volatile memory has crash durability."""
    with assert_raises(sqlite.DatabaseRuntimeError):
        sqlite.Config(database=":memory:", durability="full")


@test(mark="medium")
async def replacement_connection_keeps_full_policy() -> None:
    """Discarding an unsafe lease must not weaken the replacement connection."""
    path = await load_fixture(provide_database_path())
    database = await sqlite.Database.initialize(
        sqlite.Config(database=path, durability="full", pool_size=1)
    )
    try:
        with assert_raises(sqlite.ExecutionError):
            async with database.transaction() as failed:
                await failed.execute(sqlite.raw("SELECT * FROM missing_table"))
        async with database.transaction(timeout=1) as replacement:
            rows = await replacement.fetch_all(sqlite.raw("PRAGMA synchronous"))
        assert_eq(rows, [{"synchronous": 2}])
    finally:
        await database.close()


@test(mark="medium")
async def full_policy_keeps_wal() -> None:
    """Stronger synchronization does not change the supported journal mode."""
    path = await load_fixture(provide_database_path())
    database = await sqlite.Database.initialize(
        sqlite.Config(database=path, durability="full")
    )
    try:
        async with database.transaction() as transaction:
            rows = await transaction.fetch_all(sqlite.raw("PRAGMA journal_mode"))
        assert_eq(rows, [{"journal_mode": "wal"}])
    finally:
        await database.close()


@test(mark="fast")
def path_spelling_of_memory_rejects_full_policy() -> None:
    """Path(':memory:') reaches SQLite's special volatile target too."""
    with assert_raises(sqlite.DatabaseRuntimeError):
        sqlite.Config(database=Path(":memory:"), durability="full")


@test(mark="medium")
async def failed_verification_closes_initial_connection() -> None:
    """A driver accepting FULL without applying it must fail initialization closed."""
    path = await load_fixture(provide_database_path())
    native_execute = Connection.execute
    rejected: list[Connection] = []
    database: sqlite.Database | None = None

    async def weaken_setting(
        self: Connection, sql: str, parameters: Iterable[object] | None = None
    ) -> Cursor:
        if sql == "PRAGMA synchronous = FULL":
            rejected.append(self)
            sql = "PRAGMA synchronous = NORMAL"
        return await native_execute(self, sql, parameters)

    try:
        with (
            patch.object(Connection, "execute", weaken_setting),
            assert_raises(sqlite.DatabaseRuntimeError) as caught,
        ):
            database = await sqlite.Database.initialize(
                sqlite.Config(database=path, durability="full")
            )
        assert_in("synchronous", str(caught.exception))
        assert_eq(len(rejected), 1)
        with assert_raises(ValueError):
            await rejected[0].execute("SELECT 1")
    finally:
        if database is not None:
            await database.close()


@test(mark="medium")
async def failed_lazy_verification_recovers_pool_capacity() -> None:
    """A failed additional connection is rejected, then a healthy lease can replace it."""
    path = await load_fixture(provide_database_path())
    native_execute = Connection.execute
    database = await sqlite.Database.initialize(
        sqlite.Config(database=path, durability="full", pool_size=2)
    )

    async def weaken_setting(
        self: Connection, sql: str, parameters: Iterable[object] | None = None
    ) -> Cursor:
        if sql == "PRAGMA synchronous = FULL":
            sql = "PRAGMA synchronous = NORMAL"
        return await native_execute(self, sql, parameters)

    try:
        async with database.transaction():
            with (
                patch.object(Connection, "execute", weaken_setting),
                assert_raises(sqlite.DatabaseRuntimeError),
            ):
                async with database.transaction(timeout=1):
                    pass
            async with database.transaction(timeout=1) as healthy:
                rows = await healthy.fetch_all(sqlite.raw("PRAGMA synchronous"))
        assert_eq(rows, [{"synchronous": 2}])
    finally:
        await database.close()


@test(
    [
        Param("default", name="default"),
        Param("normal", name="explicit-normal"),
        Param("legacy", name="legacy-initializer"),
    ],
    mark="medium",
)
async def normal_file_policy_preserves_existing_default(mode: str) -> None:
    """The opt-in FULL policy must not change existing file-backed callers."""
    path = await load_fixture(provide_database_path())
    if mode == "legacy":
        database = await sqlite.Database.initialize(database=path)
    else:
        config = (
            sqlite.Config(database=path, durability="normal")
            if mode == "normal"
            else sqlite.Config(database=path)
        )
        database = await sqlite.Database.initialize(config)
    try:
        async with database.transaction() as transaction:
            rows = await transaction.fetch_all(sqlite.raw("PRAGMA synchronous"))
        assert_eq(rows, [{"synchronous": 1}])
    finally:
        await database.close()


@test(mark="medium")
async def normal_memory_policy_remains_volatile() -> None:
    """The default in-memory initializer still works without requiring WAL."""
    database = await sqlite.Database.initialize(sqlite.Config(database=":memory:"))
    try:
        async with database.transaction() as transaction:
            rows = await transaction.fetch_all(sqlite.raw("PRAGMA journal_mode"))
        assert_eq(rows, [{"journal_mode": "memory"}])
    finally:
        await database.close()


@test(mark="medium")
async def reopened_database_reapplies_selected_policy() -> None:
    """Reopening a file with FULL replaces its previous NORMAL connection policy."""
    path = await load_fixture(provide_database_path())
    previous = await sqlite.Database.initialize(sqlite.Config(database=path))
    await previous.close()

    reopened = await sqlite.Database.initialize(
        sqlite.Config(database=path, durability="full")
    )
    try:
        async with reopened.transaction() as transaction:
            rows = await transaction.fetch_all(sqlite.raw("PRAGMA synchronous"))
        assert_eq(rows, [{"synchronous": 2}])
    finally:
        await reopened.close()

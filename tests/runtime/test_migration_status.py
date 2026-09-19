"""Read-only deployment status through each backend's public Database."""

import asyncio
from collections.abc import AsyncGenerator
from dataclasses import FrozenInstanceError

from anyio import wait_all_tasks_blocked
from snektest import Param, assert_eq, assert_raises, fixture, load_fixture, test

from snekql import sqlite
from snekql.errors import MigrationDeclarationError, MigrationHistoryError
from snekql.model import BackendFamily
from tests.runtime.test_raw_execution import RawCase, provide_raw_case

_MIGRATIONS = {
    "001_entries": "CREATE TABLE status_entries (id INTEGER PRIMARY KEY)",
    "002_note": "ALTER TABLE status_entries ADD COLUMN note TEXT",
}


@test(
    [
        Param[BackendFamily](value="sqlite", name="sqlite"),
        Param[BackendFamily](value="mariadb", name="mariadb"),
    ],
    mark="slow",
)
async def absent_history_reports_every_migration_pending(
    backend: BackendFamily,
) -> None:
    """An untracked database has no applied declarations, without assuming it is empty."""
    case = await load_fixture(provide_raw_case(backend))

    status = await case.database.migration_status(_MIGRATIONS)

    assert_eq(status.history_present, False)
    assert_eq(status.applied, ())
    assert_eq(status.pending, ("001_entries", "002_note"))


@fixture
async def provide_tracked_case(
    backend: BackendFamily, count: int
) -> AsyncGenerator[RawCase]:
    case = await load_fixture(provide_raw_case(backend))
    await case.database.migrate(dict(list(_MIGRATIONS.items())[:count]))
    yield case


@test(
    [
        Param[BackendFamily](value="sqlite", name="sqlite"),
        Param[BackendFamily](value="mariadb", name="mariadb"),
    ],
    [
        Param(value=0, name="empty"),
        Param(value=1, name="prefix"),
        Param(value=2, name="head"),
    ],
    mark="slow",
)
async def tracked_history_splits_the_declared_chain(
    backend: BackendFamily, count: int
) -> None:
    """A valid prefix produces ordered applied/pending names, including empty v2 history."""
    case = await load_fixture(provide_tracked_case(backend, count))
    expected = {
        0: ((), ("001_entries", "002_note")),
        1: (("001_entries",), ("002_note",)),
        2: (("001_entries", "002_note"), ()),
    }

    status = await case.database.migration_status(_MIGRATIONS)

    assert_eq(status.history_present, True)
    assert_eq((status.applied, status.pending), expected[count])


@test(
    [
        Param[BackendFamily](value="sqlite", name="sqlite"),
        Param[BackendFamily](value="mariadb", name="mariadb"),
    ],
    mark="slow",
)
async def status_does_not_create_history(backend: BackendFamily) -> None:
    """Repeated inspection of an untracked database stays untracked."""
    case = await load_fixture(provide_raw_case(backend))

    await case.database.migration_status(_MIGRATIONS)
    repeated = await case.database.migration_status({})

    assert_eq(
        repeated, sqlite.MigrationStatus(applied=(), history_present=False, pending=())
    )


@test(
    [
        Param[BackendFamily](value="sqlite", name="sqlite"),
        Param[BackendFamily](value="mariadb", name="mariadb"),
    ],
    mark="slow",
)
async def status_does_not_execute_pending_bodies(backend: BackendFamily) -> None:
    """Non-idempotent pending DDL still executes for the first time after inspection."""
    case = await load_fixture(provide_raw_case(backend))

    await case.database.migration_status(_MIGRATIONS)
    applied = await case.database.migrate(_MIGRATIONS)

    assert_eq(applied.applied, ("001_entries", "002_note"))


@test(
    [
        Param[BackendFamily](value="sqlite", name="sqlite"),
        Param[BackendFamily](value="mariadb", name="mariadb"),
    ],
    [
        Param(value={}, name="shortened"),
        Param(value={"001_entries": "SELECT 1"}, name="edited"),
        Param(value={"renamed": _MIGRATIONS["001_entries"]}, name="renamed"),
        Param(value=dict(reversed(list(_MIGRATIONS.items()))), name="reordered"),
    ],
    mark="slow",
)
async def divergent_history_is_not_a_pending_plan(
    backend: BackendFamily, declaration: dict[str, str]
) -> None:
    """Status cannot authorize a deployment with inconsistent names, positions, or checksums."""
    case = await load_fixture(provide_tracked_case(backend, 1))

    with assert_raises(MigrationHistoryError):
        await case.database.migration_status(declaration)


@test(
    [
        Param[BackendFamily](value="sqlite", name="sqlite"),
        Param[BackendFamily](value="mariadb", name="mariadb"),
    ],
    [
        Param(value="", name="empty-body"),
        Param(value="BEGIN", name="transaction-control"),
    ],
    mark="slow",
)
async def invalid_declaration_is_rejected_before_acquisition(
    backend: BackendFamily, body: str
) -> None:
    """Declaration validation wins even when the database is already closed."""
    case = await load_fixture(provide_raw_case(backend))
    await case.database.close()

    with assert_raises(MigrationDeclarationError):
        await case.database.migration_status({"unit": body})


@test(mark="medium")
async def status_result_is_immutable() -> None:
    """A result cannot be changed into a different deployment decision."""
    case = await load_fixture(provide_raw_case("sqlite"))
    status = await case.database.migration_status(_MIGRATIONS)

    with assert_raises(FrozenInstanceError):
        status.pending = ()  # ty: ignore[invalid-assignment]


@test(mark="medium")
async def declaration_is_snapshotted_before_waiting() -> None:
    """Mutating a caller's declaration while waiting for a lease cannot alter the plan."""
    async with await sqlite.Database.initialize(
        sqlite.Config(database=":memory:", pool_size=1)
    ) as database:
        declaration = dict(_MIGRATIONS)
        async with database.transaction():
            inspecting = asyncio.create_task(database.migration_status(declaration))
            await wait_all_tasks_blocked()
            declaration.clear()
        status = await inspecting

    assert_eq(status.pending, ("001_entries", "002_note"))


@test(
    [
        Param[BackendFamily](value="sqlite", name="sqlite"),
        Param[BackendFamily](value="mariadb", name="mariadb"),
    ],
    mark="slow",
)
async def untracked_schema_is_not_treated_as_applied(backend: BackendFamily) -> None:
    """Status reads history, not whether a declared table happens to exist."""
    case = await load_fixture(provide_raw_case(backend))
    async with case.database.transaction() as transaction:
        await transaction.execute(case.namespace.raw(_MIGRATIONS["001_entries"]))

    status = await case.database.migration_status(_MIGRATIONS)

    assert_eq(status.applied, ())
    assert_eq(status.pending, ("001_entries", "002_note"))


@test(
    [
        Param[BackendFamily](value="sqlite", name="sqlite"),
        Param[BackendFamily](value="mariadb", name="mariadb"),
    ],
    [
        Param(value="legacy", name="legacy"),
        Param(value="malformed", name="malformed"),
    ],
    mark="slow",
)
async def unsupported_history_is_rejected(backend: BackendFamily, shape: str) -> None:
    """Status never upgrades, adopts, or repairs an unsupported history table."""
    case = await load_fixture(provide_raw_case(backend))
    if shape == "malformed":
        history_sql = "CREATE TABLE snekql_migrations (unexpected INTEGER)"
    elif backend == "sqlite":
        history_sql = (
            'CREATE TABLE "snekql_migrations" '
            '("name" TEXT PRIMARY KEY NOT NULL, "applied_at" TEXT NOT NULL) STRICT'
        )
    else:
        history_sql = (
            "CREATE TABLE snekql_migrations "
            "(name VARCHAR(255) CHARACTER SET utf8mb4 COLLATE utf8mb4_bin "
            "NOT NULL PRIMARY KEY, applied_at DATETIME(3) NOT NULL) ENGINE=InnoDB"
        )
    async with case.database.transaction() as transaction:
        await transaction.execute(case.namespace.raw(history_sql))

    with assert_raises(MigrationHistoryError):
        await case.database.migration_status(_MIGRATIONS)

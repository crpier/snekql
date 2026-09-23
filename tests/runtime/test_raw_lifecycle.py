"""Raw operation deadlines and cancellation on real contended connections."""

import asyncio
from collections.abc import AsyncGenerator, Iterable
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any
from unittest.mock import patch

from aiosqlite import Connection, Cursor
from anyio import fail_after, to_thread
from snektest import Param, assert_eq, assert_raises, fixture, load_fixture, test

from snekql import mariadb, sqlite
from snekql.model import BackendFamily
from tests.helpers import provide_mariadb_server
from tests.runtime.test_raw_execution import RawCase


@fixture
async def provide_contended_case(backend: BackendFamily) -> AsyncGenerator[RawCase]:
    """Two independent connections share one seeded transactional table."""

    directory = await to_thread.run_sync(TemporaryDirectory[str])
    try:
        if backend == "mariadb":
            server = await load_fixture(provide_mariadb_server())
            case = RawCase(
                await mariadb.Database.initialize(server.config(pool_size=2)), mariadb
            )
        else:
            case = RawCase(
                await sqlite.Database.initialize(
                    database=Path(directory.name) / "raw.db", pool_size=2
                ),
                sqlite,
            )
        async with case.database:
            await case.database.migrate(
                {"001_table": "CREATE TABLE raw_entries (value INTEGER PRIMARY KEY)"}
            )
            async with case.database.transaction() as transaction:
                await transaction.execute(
                    case.namespace.raw("INSERT INTO raw_entries VALUES (1)")
                )
            # Sequential leases can reuse one connection. Hold both before any
            # lock contention or deliberately short acquisition budget begins.
            async with case.database.transaction(), case.database.transaction():
                pass
            yield case
    finally:
        await to_thread.run_sync(directory.cleanup)


@test(mark="medium")
async def contended_waiter_does_not_need_connection_setup() -> None:
    """Slow physical setup cannot consume the prepared waiter's short deadline."""
    case = await load_fixture(provide_contended_case("sqlite"))
    original_execute = Connection.execute

    async def slow_validation(
        connection: Connection, sql: str, parameters: Iterable[Any] | None = None
    ) -> Cursor:
        if sql == "SELECT 1":
            await asyncio.sleep(0.06)
        return await original_execute(connection, sql, parameters)

    with patch.object(Connection, "execute", slow_validation), fail_after(5):
        async with (
            case.database.transaction(),
            case.database.transaction(timeout=0.03) as waiter,
        ):
            observed = await waiter.fetch_one(sqlite.raw("SELECT 42 AS value"))

    assert_eq(observed, {"value": 42})


@test(
    [
        Param[BackendFamily](value="sqlite", name="sqlite"),
        Param[BackendFamily](value="mariadb", name="mariadb"),
    ],
    mark="slow",
)
async def raw_deadline_discards_blocked_connection(backend: BackendFamily) -> None:
    """A timed-out writer cannot be reused, and its pool capacity is recovered."""

    case = await load_fixture(provide_contended_case(backend))

    with fail_after(5):
        async with case.database.transaction() as owner:
            await owner.execute(
                case.namespace.raw("UPDATE raw_entries SET value=2 WHERE value=1")
            )
            async with case.database.transaction(timeout=0.03) as waiter:
                with assert_raises(case.namespace.DatabaseOperationTimeoutError):
                    await waiter.execute(
                        case.namespace.raw(
                            "UPDATE raw_entries SET value=3 WHERE value=1"
                        )
                    )
                with assert_raises(case.namespace.DatabaseRuntimeError):
                    await waiter.fetch_one(case.namespace.raw("SELECT 1"))
        async with case.database.transaction() as transaction:
            observed = await transaction.fetch_one(
                case.namespace.raw("SELECT value FROM raw_entries")
            )

    assert_eq(observed, {"value": 2})


@test(
    [
        Param[BackendFamily](value="sqlite", name="sqlite"),
        Param[BackendFamily](value="mariadb", name="mariadb"),
    ],
    mark="slow",
)
async def raw_native_cancellation_releases_pool_capacity(
    backend: BackendFamily,
) -> None:
    """Native asyncio cancellation during a driver wait retains cancellation meaning."""

    case = await load_fixture(provide_contended_case(backend))
    started = asyncio.Event()

    async def blocked_write() -> None:
        async with case.database.transaction() as waiter:
            started.set()
            await waiter.execute(
                case.namespace.raw("UPDATE raw_entries SET value=3 WHERE value=1")
            )

    with fail_after(5):
        async with case.database.transaction() as owner:
            await owner.execute(
                case.namespace.raw("UPDATE raw_entries SET value=2 WHERE value=1")
            )
            pending = asyncio.create_task(blocked_write())
            try:
                await started.wait()
                await asyncio.sleep(0.03)
                pending.cancel()
                with assert_raises(asyncio.CancelledError):
                    await pending
            finally:
                pending.cancel()
                await asyncio.gather(pending, return_exceptions=True)
        async with case.database.transaction() as transaction:
            observed = await transaction.fetch_one(
                case.namespace.raw("SELECT value FROM raw_entries")
            )

    assert_eq(observed, {"value": 2})

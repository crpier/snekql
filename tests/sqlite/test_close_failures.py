"""SQLite shutdown retains failed idle cleanup without abandoning other leases."""

import asyncio
from collections.abc import AsyncGenerator, Iterable
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from aiosqlite import Connection, Cursor, OperationalError
from anyio import Event, fail_after, wait_all_tasks_blocked
from snektest import Param, assert_eq, assert_raises, fixture, load_fixture, test

from snekql import sqlite


@fixture
async def provide_idle_database(
    acquire_timeout: float = 30,
    pool_size: int = 2,
) -> AsyncGenerator[sqlite.Database]:
    """Populate two physical connections and retain driver cleanup for failed tests."""
    native_execute = Connection.execute
    native_close = Connection.close
    connections: list[Connection] = []

    async def capture_execute(
        self: Connection, sql: str, parameters: Iterable[object] | None = None
    ) -> Cursor:
        if self not in connections:
            connections.append(self)
        return await native_execute(self, sql, parameters)

    with TemporaryDirectory() as directory:
        with patch.object(Connection, "execute", capture_execute):
            database = await sqlite.Database.initialize(
                sqlite.Config(
                    database=Path(directory) / "shutdown.db",
                    pool_size=pool_size,
                    acquire_timeout=acquire_timeout,
                )
            )
            async with database.transaction(), database.transaction():
                pass
        try:
            yield database
        finally:
            for connection in connections:
                await native_close(connection)


@test(mark="medium")
async def failed_idle_close_does_not_abandon_other_connections() -> None:
    """Every idle connection gets a close attempt even if the first close fails."""
    database = await load_fixture(provide_idle_database())
    native_close = Connection.close
    rejected: list[Connection] = []
    closed: list[Connection] = []

    async def fail_first(self: Connection) -> None:
        if not rejected:
            rejected.append(self)
            message = "injected close failure"
            raise OperationalError(message)
        await native_close(self)
        closed.append(self)

    with (
        patch.object(Connection, "close", fail_first),
        assert_raises(sqlite.DatabaseRuntimeError),
    ):
        await database.close()

    assert_eq(len(closed), 1)


@test(
    [Param("before", name="before-close"), Param("after", name="after-close")],
    mark="medium",
)
async def failed_idle_close_can_be_retried(
    failure_stage: str,
) -> None:
    """A later close owns the failed connection until physical cleanup succeeds."""
    database = await load_fixture(provide_idle_database())
    native_close = Connection.close
    rejected: list[Connection] = []

    async def fail_first(self: Connection) -> None:
        if not rejected:
            rejected.append(self)
            if failure_stage == "after":
                await native_close(self)
            message = "injected close failure"
            raise OperationalError(message)
        await native_close(self)

    with (
        patch.object(Connection, "close", fail_first),
        assert_raises(sqlite.DatabaseRuntimeError),
    ):
        await database.close()
    with assert_raises(sqlite.DatabaseClosingError):
        database.transaction()

    await database.close()

    with assert_raises(ValueError):
        await rejected[0].execute("SELECT 1")
    with assert_raises(sqlite.DatabaseClosedError):
        database.transaction()


@test(mark="medium")
async def repeated_idle_close_failure_keeps_work_rejected() -> None:
    """Repeated cleanup attempts never make an uncertain handle reusable."""
    database = await load_fixture(provide_idle_database())

    async def fail_close(_self: Connection) -> None:
        message = "injected persistent close failure"
        raise OperationalError(message)

    with patch.object(Connection, "close", fail_close):
        for _ in range(3):
            with assert_raises(sqlite.DatabaseRuntimeError):
                await database.close()
            with assert_raises(sqlite.DatabaseClosingError):
                database.transaction()

    await database.close()
    with assert_raises(sqlite.DatabaseClosedError):
        database.transaction()


@test(mark="medium")
async def shutdown_waits_for_returned_connection_cleanup() -> None:
    """A returned lease still occupies shutdown capacity until its close completes."""
    database = await load_fixture(provide_idle_database())
    native_close = Connection.close
    started = Event()
    allow_close = Event()

    async def paused_close(self: Connection) -> None:
        started.set()
        await allow_close.wait()
        await native_close(self)

    transaction = database.transaction()
    await transaction.__aenter__()
    closing = asyncio.create_task(database.close())
    await wait_all_tasks_blocked()
    try:
        with patch.object(Connection, "close", paused_close):
            returning = asyncio.create_task(transaction.__aexit__(None, None, None))
            with fail_after(1):
                await started.wait()
            await wait_all_tasks_blocked()
            assert_eq(closing.done(), False)
            allow_close.set()
            with fail_after(1):
                await asyncio.gather(returning, closing)
    finally:
        allow_close.set()
        await asyncio.gather(returning, closing, return_exceptions=True)


@test(mark="medium")
async def failed_discard_cleanup_remains_owned() -> None:
    """Failed physical discard rejects new work and is retried by Database.close."""
    database = await load_fixture(provide_idle_database())
    rejected: list[Connection] = []

    async def fail_close(self: Connection) -> None:
        rejected.append(self)
        message = "injected discard close failure"
        raise OperationalError(message)

    with patch.object(Connection, "close", fail_close):
        with assert_raises(sqlite.ExecutionError):
            async with database.transaction() as transaction:
                await transaction.execute(sqlite.raw("SELECT * FROM missing_table"))
        await wait_all_tasks_blocked()
        with assert_raises(sqlite.DatabaseClosingError):
            database.transaction()
        with assert_raises(sqlite.DatabaseRuntimeError):
            await database.close()

    await database.close()
    for connection in rejected:
        with assert_raises(ValueError):
            await connection.execute("SELECT 1")


@test(mark="medium")
async def failed_return_cleanup_prevents_successful_shutdown() -> None:
    """A connection returned during shutdown cannot disappear after a close error."""
    database = await load_fixture(provide_idle_database())
    rejected: list[Connection] = []

    async def fail_close(self: Connection) -> None:
        rejected.append(self)
        message = "injected return close failure"
        raise OperationalError(message)

    transaction = database.transaction()
    await transaction.__aenter__()
    closing = asyncio.create_task(database.close())
    await wait_all_tasks_blocked()
    with patch.object(Connection, "close", fail_close):
        await transaction.__aexit__(None, None, None)
        with fail_after(1), assert_raises(sqlite.DatabaseRuntimeError):
            await closing

    await database.close()
    for connection in rejected:
        with assert_raises(ValueError):
            await connection.execute("SELECT 1")


@test(mark="medium")
async def cancelled_shutdown_waiter_preserves_return_cleanup() -> None:
    """Native caller cancellation cannot drop an in-flight returned connection."""
    database = await load_fixture(provide_idle_database())
    native_close = Connection.close
    started = Event()
    allow_close = Event()
    completed = Event()

    async def paused_close(self: Connection) -> None:
        started.set()
        await allow_close.wait()
        await native_close(self)
        completed.set()

    transaction = database.transaction()
    await transaction.__aenter__()
    closing = asyncio.create_task(database.close())
    await wait_all_tasks_blocked()
    try:
        with patch.object(Connection, "close", paused_close):
            returning = asyncio.create_task(transaction.__aexit__(None, None, None))
            with fail_after(1):
                await started.wait()
            closing.cancel()
            with assert_raises(asyncio.CancelledError):
                await closing
            with assert_raises(sqlite.DatabaseClosingError):
                database.transaction()
            allow_close.set()
            with fail_after(1):
                await returning
                await database.close()
            assert_eq(completed.is_set(), True)
    finally:
        allow_close.set()
        await asyncio.gather(returning, closing, return_exceptions=True)


@test(mark="medium")
async def close_timeout_does_not_reopen_failed_cleanup() -> None:
    """Waiting for another lease cannot clear quarantine after a physical failure."""
    database = await load_fixture(provide_idle_database(acquire_timeout=0.2))

    async def fail_close(_self: Connection) -> None:
        message = "injected close failure while another lease remains active"
        raise OperationalError(message)

    async with database.transaction():
        returning = database.transaction()
        await returning.__aenter__()
        closing = asyncio.create_task(database.close())
        await wait_all_tasks_blocked()
        with patch.object(Connection, "close", fail_close):
            await returning.__aexit__(None, None, None)
            with fail_after(1), assert_raises(sqlite.DatabaseCloseTimeoutError):
                await closing
        with assert_raises(sqlite.DatabaseClosingError):
            database.transaction()

    await database.close()


@test(mark="medium")
async def failed_cancelled_open_cleanup_remains_owned() -> None:
    """Cancellation after opening cannot lose a handle whose physical close fails."""
    database = await load_fixture(provide_idle_database(pool_size=3))
    native_cursor_close = Cursor.close
    native_close = Connection.close
    rejected: list[Connection] = []
    entering: asyncio.Task[None]

    async def cancel_after_settings(self: Cursor) -> None:
        final_probe = (
            self.description is not None and self.description[0][0] == "encoding"
        )
        await native_cursor_close(self)
        if final_probe:
            asyncio.get_running_loop().call_soon(entering.cancel)

    async def fail_close(self: Connection) -> None:
        rejected.append(self)
        message = "injected completed-open cleanup failure"
        raise OperationalError(message)

    async def enter_transaction() -> None:
        async with database.transaction():
            pass

    try:
        async with database.transaction(), database.transaction():
            with (
                patch.object(Cursor, "close", cancel_after_settings),
                patch.object(Connection, "close", fail_close),
            ):
                entering = asyncio.create_task(enter_transaction())
                with fail_after(1), assert_raises(asyncio.CancelledError):
                    await entering
                await wait_all_tasks_blocked()
            assert_eq(len(rejected), 1)
            with assert_raises(sqlite.DatabaseClosingError):
                database.transaction()
        await database.close()
        with assert_raises(ValueError):
            await rejected[0].execute("SELECT 1")
    finally:
        for connection in rejected:
            await native_close(connection)

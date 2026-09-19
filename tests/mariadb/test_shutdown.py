"""MariaDB shutdown ownership through real Database and Transaction lifecycles."""

import asyncio
from dataclasses import replace
from unittest.mock import patch

from aiomysql import Connection, OperationalError, Pool
from anyio import Event, fail_after, wait_all_tasks_blocked
from snektest import assert_eq, assert_raises, load_fixture, test

from snekql import mariadb
from tests.helpers import provide_mariadb_server


@test(mark="slow")
async def cancelled_waiter_does_not_abandon_shutdown() -> None:
    """Native caller cancellation leaves physical shutdown owned and running."""
    server = await load_fixture(provide_mariadb_server())
    database = await mariadb.Database.initialize(server.config(pool_size=1))
    native_wait = Pool.wait_closed
    started = Event()
    allow_close = Event()
    completed = Event()

    async def paused_wait(self: Pool) -> None:
        started.set()
        await allow_close.wait()
        await native_wait(self)
        completed.set()

    try:
        with patch.object(Pool, "wait_closed", paused_wait):
            closing = asyncio.create_task(database.close())
            with fail_after(1):
                await started.wait()
            closing.cancel()
            with assert_raises(asyncio.CancelledError):
                await closing
            allow_close.set()
            with fail_after(1):
                await completed.wait()
            await database.close()
        with assert_raises(mariadb.DatabaseClosedError):
            database.transaction()
    finally:
        allow_close.set()
        await database.close()


@test(mark="slow")
async def shutdown_finishes_after_active_connection_is_discarded() -> None:
    """A failed active Transaction must wake shutdown even on a closed socket."""
    server = await load_fixture(provide_mariadb_server())
    database = await mariadb.Database.initialize(
        server.config(pool_size=1, acquire_timeout=0.2)
    )
    closing: asyncio.Task[None] | None = None
    try:
        with assert_raises(mariadb.ExecutionError):
            async with database.transaction() as transaction:
                closing = asyncio.create_task(database.close())
                await wait_all_tasks_blocked()
                await transaction.execute(mariadb.raw("SELECT * FROM missing_table"))
        assert closing is not None
        with fail_after(1):
            await closing
        with assert_raises(mariadb.DatabaseClosedError):
            database.transaction()
    finally:
        await database.close()


@test(mark="slow")
async def shutdown_rejects_checkout_already_probing() -> None:
    """An admitted checkout cannot begin a Transaction after shutdown starts."""
    server = await load_fixture(provide_mariadb_server())
    database = await mariadb.Database.initialize(
        replace(server.config(pool_size=1), health_check="checkout")
    )
    native_ping = Connection.ping
    started = Event()
    allow_probe = Event()

    async def paused_ping(self: Connection, *, reconnect: bool) -> None:
        started.set()
        await allow_probe.wait()
        await native_ping(self, reconnect=reconnect)

    async def enter_transaction() -> None:
        async with database.transaction():
            pass

    try:
        with patch.object(Connection, "ping", paused_ping):
            entering = asyncio.create_task(enter_transaction())
            with fail_after(1):
                await started.wait()
            closing = asyncio.create_task(database.close())
            await wait_all_tasks_blocked()
            allow_probe.set()
            with assert_raises(mariadb.DatabaseClosingError):
                await entering
            with fail_after(1):
                await closing
    finally:
        allow_probe.set()
        await database.close()


@test(mark="slow")
async def failed_shutdown_can_finish_on_later_close() -> None:
    """Driver cleanup failure remains terminal for new work but cleanup is retryable."""
    server = await load_fixture(provide_mariadb_server())
    database = await mariadb.Database.initialize(server.config(pool_size=1))

    async def failed_wait(_self: Pool) -> None:
        message = "injected shutdown failure"
        raise OperationalError(2013, message)

    try:
        with (
            patch.object(Pool, "wait_closed", failed_wait),
            assert_raises(mariadb.DatabaseRuntimeError),
        ):
            await database.close()
        with assert_raises(mariadb.DatabaseClosingError):
            database.transaction()
        await database.close()
        with assert_raises(mariadb.DatabaseClosedError):
            database.transaction()
    finally:
        await database.close()


@test(mark="slow")
async def physical_close_failure_retains_socket_for_retry() -> None:
    """A driver close error cannot lose the socket removed from its idle queue."""
    server = await load_fixture(provide_mariadb_server())
    database = await mariadb.Database.initialize(server.config(pool_size=2))
    native_close = Connection.close
    rejected: list[Connection] = []

    def fail_first(self: Connection) -> None:
        if not rejected:
            rejected.append(self)
            message = "injected physical socket close failure"
            raise OperationalError(2013, message)
        native_close(self)

    try:
        async with database.transaction(), database.transaction():
            pass
        with (
            patch.object(Connection, "close", fail_first),
            assert_raises(mariadb.DatabaseRuntimeError),
        ):
            await database.close()
        await database.close()
        assert_eq(rejected[0].closed, True)
    finally:
        for connection in rejected:
            native_close(connection)
        await database.close()

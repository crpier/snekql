"""Partial MariaDB initialization owns and closes sockets on interruption."""

import asyncio
from unittest.mock import patch

from aiomysql import Connection, OperationalError, Pool
from anyio import Event, fail_after, sleep_forever
from snektest import assert_eq, assert_is, assert_raises, load_fixture, test

from snekql import mariadb
from tests.helpers import provide_mariadb_server


@test(mark="slow")
async def authentication_timeout_closes_partial_socket() -> None:
    """The acquisition deadline includes authentication, not just TCP connect."""
    server = await load_fixture(provide_mariadb_server())
    opened: list[Connection] = []

    async def stalled_authentication(self: Connection) -> None:
        opened.append(self)
        await sleep_forever()

    try:
        with (
            patch.object(Connection, "_request_authentication", stalled_authentication),
            fail_after(1),
            assert_raises(mariadb.PoolTimeoutError),
        ):
            await mariadb.Database.initialize(server.config(acquire_timeout=0.05))
        assert_eq(len(opened), 1)
        assert_eq(opened[0].closed, True)
    finally:
        for connection in opened:
            connection.close()


@test(mark="slow")
async def native_cancellation_closes_partial_socket() -> None:
    """Cancelling authentication cannot leave a socket outside pool ownership."""
    server = await load_fixture(provide_mariadb_server())
    opened: list[Connection] = []
    started = Event()

    async def stalled_authentication(self: Connection) -> None:
        opened.append(self)
        started.set()
        await sleep_forever()

    try:
        with patch.object(
            Connection, "_request_authentication", stalled_authentication
        ):
            initializing = asyncio.create_task(
                mariadb.Database.initialize(server.config())
            )
            with fail_after(1):
                await started.wait()
            initializing.cancel()
            with assert_raises(asyncio.CancelledError):
                await initializing
        assert_eq(opened[0].closed, True)
    finally:
        for connection in opened:
            connection.close()


@test(mark="slow")
async def cleanup_failure_preserves_initialization_error() -> None:
    """A failed cleanup wait must not replace the failure that prevented startup."""
    server = await load_fixture(provide_mariadb_server())
    primary = mariadb.DatabaseRuntimeError("injected authentication failure")

    async def failed_authentication(_self: Connection) -> None:
        raise primary

    async def failed_cleanup(_self: Pool) -> None:
        message = "injected cleanup failure"
        raise OperationalError(2013, message)

    with (
        patch.object(Connection, "_request_authentication", failed_authentication),
        patch.object(Pool, "wait_closed", failed_cleanup),
        assert_raises(mariadb.DatabaseRuntimeError) as caught,
    ):
        await mariadb.Database.initialize(server.config())
    assert_is(caught.exception, primary)

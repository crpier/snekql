"""MariaDB recycling and health policies through Config and Transactions."""

import asyncio
from collections.abc import AsyncGenerator
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from aiomysql import Connection, OperationalError
from anyio import Event, TemporaryDirectory, fail_after, sleep, sleep_forever
from snektest import (
    Param,
    assert_eq,
    assert_ne,
    assert_raises,
    fixture,
    load_fixture,
    test,
)

from snekql import mariadb
from snekql.testing.mariadb import temporary_mariadb_server
from tests.helpers import provide_mariadb_server
from tests.mariadb.test_required_tls import tls_peer


@test(mark="slow")
async def lifetime_replaces_connection_at_checkout() -> None:
    """An expired physical connection is replaced before the next Transaction."""
    server = await load_fixture(provide_mariadb_server())
    config = replace(server.config(pool_size=1), max_connection_lifetime=0.2)
    async with await mariadb.Database.initialize(config) as database:
        async with database.transaction() as transaction:
            before = await transaction.fetch_all(mariadb.raw("SELECT CONNECTION_ID()"))
            await sleep(0.25)
        async with database.transaction() as transaction:
            after = await transaction.fetch_all(mariadb.raw("SELECT CONNECTION_ID()"))
    assert_ne(after, before)


@test(mark="slow")
async def idle_timeout_replaces_returned_connection() -> None:
    """Idle time starts when a lease returns, not when its last cursor was opened."""
    server = await load_fixture(provide_mariadb_server())
    config = replace(server.config(pool_size=1), max_connection_idle=0.2)
    async with await mariadb.Database.initialize(config) as database:
        async with database.transaction() as transaction:
            before = await transaction.fetch_all(mariadb.raw("SELECT CONNECTION_ID()"))
        await sleep(0.25)
        async with database.transaction() as transaction:
            after = await transaction.fetch_all(mariadb.raw("SELECT CONNECTION_ID()"))
    assert_ne(after, before)


@test(mark="slow")
async def checkout_health_failure_discards_without_reconnect() -> None:
    """A failed probe fails acquisition; a later Transaction gets a new session."""
    server = await load_fixture(provide_mariadb_server())
    config = replace(server.config(pool_size=1), health_check="checkout")

    async def failed_ping(_self: Connection, *, reconnect: bool) -> None:
        assert_eq(reconnect, False)
        message = "injected silent socket loss"
        raise OperationalError(2013, message)

    async with await mariadb.Database.initialize(config) as database:
        async with database.transaction() as transaction:
            before = await transaction.fetch_all(mariadb.raw("SELECT CONNECTION_ID()"))
        with (
            patch.object(Connection, "ping", failed_ping),
            assert_raises(mariadb.DatabaseRuntimeError),
        ):
            async with database.transaction():
                pass
        async with database.transaction() as transaction:
            after = await transaction.fetch_all(mariadb.raw("SELECT CONNECTION_ID()"))
    assert_ne(after, before)


@test(
    [
        Param("max_connection_idle", name="idle"),
        Param("max_connection_lifetime", name="lifetime"),
    ],
    [
        Param(0, name="zero"),
        Param(-1, name="negative"),
        Param(float("inf"), name="infinity"),
        Param(float("nan"), name="nan"),
        Param(True, name="boolean"),
        Param("1", name="string"),
    ],
    mark="fast",
)
def recycling_rejects_invalid_duration(field: str, duration: object) -> None:
    """Recycling durations must be finite and positive, or disabled with None."""
    with assert_raises(mariadb.DatabaseRuntimeError):
        replace(mariadb.Config(database="app", user="app"), **{field: duration})


@test(
    [
        Param("always", name="unknown"),
        Param(None, name="none"),
        Param(True, name="boolean"),
    ],
    mark="fast",
)
def health_policy_rejects_unsupported_values(policy: object) -> None:
    """Only passive detection and active checkout probes are supported."""
    with assert_raises(mariadb.DatabaseRuntimeError):
        mariadb.Config(database="app", user="app", health_check=policy)  # ty: ignore[invalid-argument-type]


@test(mark="slow")
async def long_transaction_does_not_count_as_idle() -> None:
    """A newly returned lease has no idle age even after a long Transaction."""
    server = await load_fixture(provide_mariadb_server())
    config = replace(server.config(pool_size=1), max_connection_idle=0.2)
    async with await mariadb.Database.initialize(config) as database:
        async with database.transaction() as transaction:
            before = await transaction.fetch_all(mariadb.raw("SELECT CONNECTION_ID()"))
            await sleep(0.25)
        async with database.transaction() as transaction:
            after = await transaction.fetch_all(mariadb.raw("SELECT CONNECTION_ID()"))
    assert_eq(after, before)


@test(mark="slow")
async def lifetime_does_not_interrupt_active_transaction() -> None:
    """An active lease keeps its physical session beyond the recycling age."""
    server = await load_fixture(provide_mariadb_server())
    config = replace(server.config(pool_size=1), max_connection_lifetime=0.2)
    async with (
        await mariadb.Database.initialize(config) as database,
        database.transaction() as transaction,
    ):
        before = await transaction.fetch_all(mariadb.raw("SELECT CONNECTION_ID()"))
        await sleep(0.25)
        after = await transaction.fetch_all(mariadb.raw("SELECT CONNECTION_ID()"))
    assert_eq(after, before)


@test(mark="slow")
async def health_probe_obeys_acquisition_deadline() -> None:
    """A stalled probe releases capacity without extending the acquisition budget."""
    server = await load_fixture(provide_mariadb_server())
    config = replace(server.config(pool_size=1), health_check="checkout")

    async def stalled_ping(_self: Connection, *, reconnect: bool) -> None:
        assert_eq(reconnect, False)
        await sleep_forever()

    async with await mariadb.Database.initialize(config) as database:
        with (
            patch.object(Connection, "ping", stalled_ping),
            fail_after(1),
            assert_raises(mariadb.PoolTimeoutError),
        ):
            async with database.transaction(timeout=0.05):
                pass
        with fail_after(1):
            async with database.transaction() as transaction:
                rows = await transaction.fetch_all(mariadb.raw("SELECT 1 AS alive"))
        assert_eq(rows, [{"alive": 1}])


@test(mark="slow")
async def passive_health_does_not_send_probes() -> None:
    """The default preserves driver EOF checks without adding a ping round trip."""
    server = await load_fixture(provide_mariadb_server())

    async def unexpected_ping(_self: Connection, *, reconnect: bool) -> None:
        _ = reconnect
        message = "passive checkout must not ping"
        raise OperationalError(2013, message)

    with patch.object(Connection, "ping", unexpected_ping):
        async with await mariadb.Database.initialize(
            server.config(pool_size=1)
        ) as database:
            async with database.transaction() as transaction:
                rows = await transaction.fetch_all(mariadb.raw("SELECT 1 AS alive"))
    assert_eq(rows, [{"alive": 1}])


@test(mark="slow")
async def native_cancellation_during_probe_recovers_capacity() -> None:
    """Cancelling checkout cannot strand its socket or its sole admission slot."""
    server = await load_fixture(provide_mariadb_server())
    config = replace(server.config(pool_size=1), health_check="checkout")
    started = Event()

    async def stalled_ping(_self: Connection, *, reconnect: bool) -> None:
        assert_eq(reconnect, False)
        started.set()
        await sleep_forever()

    async with await mariadb.Database.initialize(config) as database:
        with patch.object(Connection, "ping", stalled_ping):
            entering = asyncio.create_task(database.transaction().__aenter__())
            with fail_after(1):
                await started.wait()
            entering.cancel()
            with assert_raises(asyncio.CancelledError):
                await entering
        with fail_after(1):
            async with database.transaction() as transaction:
                rows = await transaction.fetch_all(mariadb.raw("SELECT 1 AS alive"))
    assert_eq(rows, [{"alive": 1}])


@test(mark="slow")
async def required_tls_recycling_preserves_verified_transport() -> None:
    """Replacement sessions retain TLS and required session configuration."""
    peer = await load_fixture(tls_peer())
    config = replace(
        peer.config, pool_size=1, max_connection_idle=0.2, health_check="checkout"
    )
    async with await mariadb.Database.initialize(config) as database:
        await sleep(0.25)
        async with database.transaction() as transaction:
            rows = await transaction.fetch_all(
                mariadb.raw("SHOW SESSION STATUS LIKE 'Ssl_cipher'")
            )
        assert_ne(rows[0]["Value"], "")


@fixture
async def provide_restarted_database() -> AsyncGenerator[mariadb.Database]:
    """Keep a pool alive while its real server stops and restarts on the same port."""
    async with TemporaryDirectory() as directory:
        database: mariadb.Database | None = None
        try:
            async with temporary_mariadb_server(
                data_directory=Path(directory), transports={"tcp"}
            ) as server:
                config = replace(server.config(pool_size=1), health_check="checkout")
                database = await mariadb.Database.initialize(config)
            async with temporary_mariadb_server(
                data_directory=Path(directory), transports={"tcp"}, port=config.port
            ):
                yield database
        finally:
            if database is not None:
                await database.close()


@test(mark="slow")
async def restarted_server_gets_configured_replacement() -> None:
    """An idle socket from the previous server is replaced with a configured session."""
    database = await load_fixture(provide_restarted_database())
    async with database.transaction() as transaction:
        rows = await transaction.fetch_all(
            mariadb.raw("SELECT @@session.time_zone AS zone")
        )
    assert_eq(rows, [{"zone": "+00:00"}])


@test(mark="slow")
async def recycling_rejects_tls_downgrade() -> None:
    """An expired connection cannot be replaced by plaintext authentication."""
    peer = await load_fixture(tls_peer())
    config = replace(peer.config, pool_size=1, max_connection_idle=0.2)
    async with await mariadb.Database.initialize(config) as database:
        await sleep(0.25)
        peer.deny_tls = True
        with assert_raises(mariadb.DatabaseRuntimeError):
            async with database.transaction():
                pass
    await peer.disconnect()
    assert_eq(peer.denied_bytes, [0])


@test(mark="slow")
async def checkout_health_does_not_replay_active_transaction() -> None:
    """A connection killed after checkout still fails its active Transaction."""
    server = await load_fixture(provide_mariadb_server())
    config = replace(server.config(pool_size=1), health_check="checkout")
    async with await mariadb.Database.initialize(config) as database:
        with assert_raises(mariadb.ExecutionError):
            async with database.transaction() as transaction:
                rows = await transaction.fetch_all(
                    mariadb.raw("SELECT CONNECTION_ID() AS connection_id")
                )
                connection_id = rows[0]["connection_id"]
                assert isinstance(connection_id, int)
                await server.run_sql(f"KILL {connection_id}")
                await transaction.fetch_all(mariadb.raw("SELECT 1 AS alive"))
        async with database.transaction() as transaction:
            rows = await transaction.fetch_all(mariadb.raw("SELECT 1 AS alive"))
    assert_eq(rows, [{"alive": 1}])

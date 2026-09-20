"""Late native streaming faults must discard the lease rather than replay it."""

from typing import Any
from unittest.mock import patch

from aiomysql import OperationalError, SSCursor
from snektest import Param, assert_eq, assert_raises, load_fixture, test

from snekql import mariadb
from tests.helpers import provide_mariadb_server


@test(
    [Param(value="fetch", name="fetch"), Param(value="close", name="close")],
    mark="slow",
)
async def late_stream_fault_discards_lease(phase: str) -> None:
    """A failure after a delivered batch invalidates the transaction and frees capacity."""
    server = await load_fixture(provide_mariadb_server())
    fetchmany = SSCursor.fetchmany
    close = SSCursor.close
    batches = 0

    async def fail_fetch(self: SSCursor, size: int = 1) -> Any:
        nonlocal batches
        batches += 1
        if batches == 2:
            message = "simulated lost stream reply"
            raise OperationalError(2013, message)
        return await fetchmany(self, size)

    async def fail_close(self: SSCursor) -> None:
        await close(self)
        message = "simulated lost close reply"
        raise OperationalError(2013, message)

    async with await mariadb.Database.initialize(
        server.config(pool_size=1)
    ) as database:
        before = database.pool_stats()
        async with database.transaction() as transaction:
            with (
                patch.object(
                    SSCursor,
                    "fetchmany" if phase == "fetch" else "close",
                    fail_fetch if phase == "fetch" else fail_close,
                ),
                assert_raises(mariadb.ExecutionError) as caught,
            ):
                async with transaction.fetch_chunks(
                    mariadb.raw("SELECT 1 AS value UNION ALL SELECT 2 AS value"), size=1
                ) as stream:
                    assert_eq(await anext(stream), [{"value": 1}])
                    if phase == "fetch":
                        await anext(stream)
            with assert_raises(mariadb.DatabaseRuntimeError):
                await transaction.fetch_one(mariadb.raw("SELECT 3"))
        assert caught.exception.failure is not None
        assert_eq(caught.exception.failure.category, "connection_loss")
        assert_eq(
            database.pool_stats().discarded_connections,
            before.discarded_connections + 1,
        )
        async with database.transaction() as recovered:
            assert_eq(
                await recovered.fetch_one(mariadb.raw("SELECT 4 AS value")),
                {"value": 4},
            )
        assert_eq(database.pool_stats().occupied, 0)

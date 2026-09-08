"""MariaDB first-use configuration shares the transaction acquisition deadline."""

from __future__ import annotations

from unittest.mock import patch

from aiomysql import Cursor
from anyio import fail_after, sleep_forever
from snektest import assert_raises, load_fixture, test

from snekql import mariadb
from tests.helpers import provide_mariadb_server


@test(mark="slow")
async def first_use_configuration_obeys_acquisition_deadline() -> None:
    """A stalled session probe times out and leaves capacity for a healthy connection."""

    server = await load_fixture(provide_mariadb_server())
    original_execute = Cursor.execute

    async def stalled_probe(cursor: Cursor, sql: str, args: object = None) -> int:
        if sql == "SELECT VERSION()":
            await sleep_forever()
        affected = await original_execute(cursor, sql, args)
        assert isinstance(affected, int)
        return affected

    async with (
        await mariadb.Database.initialize(server.config(pool_size=2)) as database,
        database.transaction(),
    ):
        with (
            patch.object(Cursor, "execute", stalled_probe),
            fail_after(1),
            assert_raises(mariadb.PoolTimeoutError),
        ):
            async with database.transaction(timeout=0.05):
                pass
        with fail_after(1):
            async with database.transaction():
                pass

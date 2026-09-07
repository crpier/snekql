"""MariaDB transactions reject concurrent entry before pool acquisition."""

from __future__ import annotations

import asyncio

from anyio import fail_after, wait_all_tasks_blocked
from snektest import assert_eq, load_fixture, test

from snekql import mariadb
from tests.helpers import provide_mariadb_server


@test(mark="slow")
async def concurrent_entry_uses_only_one_connection() -> None:
    """A shared transaction cannot acquire two physical connections from a waiting pool."""

    server = await load_fixture(provide_mariadb_server())
    async with await mariadb.Database.initialize(
        server.config(pool_size=2, acquire_timeout=1)
    ) as database:
        transaction = database.transaction()
        outcomes: list[str] = []

        async def enter() -> None:
            try:
                async with transaction:
                    outcomes.append("entered")
            except mariadb.TransactionReuseError:
                outcomes.append("rejected")

        with fail_after(2):
            async with database.transaction(), database.transaction():
                first = asyncio.create_task(enter())
                second = asyncio.create_task(enter())
                await wait_all_tasks_blocked()
                while_waiting = list(outcomes)
            await asyncio.gather(first, second)
            async with database.transaction(), database.transaction():
                pass

    assert_eq(while_waiting, ["rejected"])
    assert_eq(sorted(outcomes), ["entered", "rejected"])

"""Cancellation cannot leave a dead FIFO ticket ahead of live transactions."""

import asyncio
from collections.abc import AsyncGenerator
from dataclasses import replace
from typing import Literal

from anyio import CancelScope, fail_after, sleep_forever
from snektest import Param, assert_eq, assert_raises, fixture, load_fixture, test

from snekql import mariadb, sqlite
from tests.helpers import provide_mariadb_server


@fixture
async def single_slot(
    backend: Literal["sqlite", "mariadb"],
) -> AsyncGenerator[sqlite.Database | mariadb.Database]:
    """Keep admission contended without using driver or pool internals."""
    if backend == "sqlite":
        async with await sqlite.Database.initialize(database=":memory:") as database:
            yield database
    else:
        server = await load_fixture(provide_mariadb_server())
        async with await mariadb.Database.initialize(
            replace(server.config(), pool_size=1)
        ) as database:
            yield database


@test(
    [
        Param[Literal["sqlite", "mariadb"]]("sqlite", name="sqlite"),
        Param[Literal["sqlite", "mariadb"]]("mariadb", name="mariadb"),
    ],
    [Param(delay, name=f"checkpoint-{delay}") for delay in range(8)],
    mark="slow",
)
async def cancelled_handoff_does_not_block_the_next_transaction(
    backend: Literal["sqlite", "mariadb"], delay: int
) -> None:
    """Cancel before, during, or after a queued waiter receives the free slot."""
    database = await load_fixture(single_slot(backend))
    scope = CancelScope()

    async def contender() -> None:
        with scope:
            async with database.transaction():
                await sleep_forever()

    async with database.transaction():
        queued = asyncio.create_task(contender())
        with fail_after(5):
            while database.pool_stats().waiters != 1:  # noqa: ASYNC110 - observe the public queue state at each checkpoint
                await asyncio.sleep(0)
    for _ in range(delay):
        await asyncio.sleep(0)
    scope.cancel()
    await queued

    async with database.transaction(timeout=1):
        pass


@test(
    [
        Param[Literal["sqlite", "mariadb"]]("sqlite", name="sqlite"),
        Param[Literal["sqlite", "mariadb"]]("mariadb", name="mariadb"),
    ],
    [Param(delay, name=f"checkpoint-{delay}") for delay in range(8)],
    mark="slow",
)
async def task_cancellation_remains_cancellation_during_handoff(
    backend: Literal["sqlite", "mariadb"], delay: int
) -> None:
    """Native asyncio cancellation must not become an unrelated lock error."""
    database = await load_fixture(single_slot(backend))

    async def contender() -> None:
        async with database.transaction():
            await sleep_forever()

    async with database.transaction():
        queued = asyncio.create_task(contender())
        with fail_after(5):
            while database.pool_stats().waiters != 1:  # noqa: ASYNC110 - observe the public queue state at each checkpoint
                await asyncio.sleep(0)
    for _ in range(delay):
        await asyncio.sleep(0)
    queued.cancel()

    with assert_raises(asyncio.CancelledError):
        await queued
    async with database.transaction(timeout=1):
        pass


@test(
    [
        Param[Literal["sqlite", "mariadb"]]("sqlite", name="sqlite"),
        Param[Literal["sqlite", "mariadb"]]("mariadb", name="mariadb"),
    ],
    mark="slow",
)
async def queued_transactions_keep_fifo_order(
    backend: Literal["sqlite", "mariadb"],
) -> None:
    """A fresh acquirer cannot overtake transactions already waiting."""
    database = await load_fixture(single_slot(backend))
    order: list[int] = []

    async def waiter(position: int) -> None:
        async with database.transaction():
            order.append(position)

    queued: list[asyncio.Task[None]] = []
    async with database.transaction():
        for position in range(3):
            queued.append(asyncio.create_task(waiter(position)))
            with fail_after(5):
                while database.pool_stats().waiters != position + 1:  # noqa: ASYNC110 - public admission state is the synchronization boundary
                    await asyncio.sleep(0)
    async with database.transaction():
        order.append(3)
    await asyncio.gather(*queued)

    assert_eq(order, [0, 1, 2, 3])

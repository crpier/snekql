"""SQLite connection pool fairness (FIFO, no barging) tests.

Under contention a task that releases a connection and immediately re-acquires
must not jump ahead of a task that was already waiting, and parked waiters must
be served in the order they arrived.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator

import anyio
from snektest import assert_eq, load_fixture, test

from snekql.sqlite.pool import (
    SQLiteConnectionPool,
    open_sqlite_connection,
)

_TIMEOUT = 30.0


async def single_connection_pool() -> AsyncGenerator[SQLiteConnectionPool]:
    """Provide a `pool_size=1` in-memory pool and close it on teardown."""

    initial = await open_sqlite_connection(":memory:")
    pool = SQLiteConnectionPool(
        database_path=":memory:",
        initial_connection=initial,
        pool_size=1,
    )
    try:
        yield pool
    finally:
        await pool.close(_TIMEOUT)


@test(mark="medium")
async def releasing_task_does_not_barge_past_a_waiter() -> None:
    """Re-acquiring after release must queue behind an already-parked waiter."""

    pool = await load_fixture(single_connection_pool())
    events: list[str] = []

    held = await pool.acquire(_TIMEOUT)

    async def waiter() -> None:
        connection = await pool.acquire(_TIMEOUT)
        events.append("waiter-acquired")
        await pool.release(connection)
        events.append("waiter-released")

    async with anyio.create_task_group() as task_group:
        task_group.start_soon(waiter)
        await anyio.wait_all_tasks_blocked()

        await pool.release(held)
        events.append("reacquire-start")
        reacquired = await pool.acquire(_TIMEOUT)
        events.append("reacquire-done")
        await pool.release(reacquired)

    assert_eq(
        events,
        [
            "reacquire-start",
            "waiter-acquired",
            "waiter-released",
            "reacquire-done",
        ],
    )


@test(mark="medium")
async def parked_waiters_are_served_in_arrival_order() -> None:
    """Multiple parked waiters acquire the connection FIFO, not LIFO."""

    pool = await load_fixture(single_connection_pool())
    order: list[str] = []

    held = await pool.acquire(_TIMEOUT)

    async def waiter(name: str) -> None:
        connection = await pool.acquire(_TIMEOUT)
        order.append(name)
        await pool.release(connection)

    async with anyio.create_task_group() as task_group:
        for name in ("first", "second", "third"):
            task_group.start_soon(waiter, name)
            await anyio.wait_all_tasks_blocked()
        await pool.release(held)

    assert_eq(order, ["first", "second", "third"])

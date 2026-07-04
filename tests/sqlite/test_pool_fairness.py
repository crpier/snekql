"""SQLite connection pool fairness (FIFO, no barging) tests.

Under contention a task that releases a connection and immediately re-acquires
must not jump ahead of a task that was already waiting, and parked waiters must
be served in the order they arrived.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator

import anyio
from snektest import assert_eq, fixture, load_fixture, test

from snekql.sqlite.pool import (
    SQLiteConnectionPool,
    open_sqlite_connection,
)

_TIMEOUT = 30.0


@fixture
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


@test(mark="medium")
async def cancelling_a_parked_waiter_frees_its_fifo_slot() -> None:
    """A waiter cancelled while parked must not block later FIFO waiters.

    If the cancelled acquirer left its ticket at the front of the queue, every
    later waiter would be stuck behind a dead ticket and never get served.
    """

    pool = await load_fixture(single_connection_pool())
    served: list[str] = []

    held = await pool.acquire(_TIMEOUT)

    async def cancellable_waiter(scope_holder: list[anyio.CancelScope]) -> None:
        with anyio.CancelScope() as scope:
            scope_holder.append(scope)
            connection = await pool.acquire(_TIMEOUT)
            served.append("cancelled-waiter")
            await pool.release(connection)

    async def waiter() -> None:
        connection = await pool.acquire(_TIMEOUT)
        served.append("waiter")
        await pool.release(connection)

    scope_holder: list[anyio.CancelScope] = []
    async with anyio.create_task_group() as task_group:
        # First in line; it will be cancelled while parked.
        task_group.start_soon(cancellable_waiter, scope_holder)
        await anyio.wait_all_tasks_blocked()
        # Second in line, queued strictly behind the soon-to-be-cancelled one.
        task_group.start_soon(waiter)
        await anyio.wait_all_tasks_blocked()

        scope_holder[0].cancel()
        await anyio.wait_all_tasks_blocked()
        await pool.release(held)

    assert_eq(served, ["waiter"])

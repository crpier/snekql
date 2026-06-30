"""MariaDB connection pool fairness (FIFO, no barging) tests.

The underlying ``aiomysql`` pool wakes blocked acquirers without a fairness
guarantee, so ``MariaDBConnectionPool`` puts a FIFO admission gate in front of
``pool.acquire()``. Under contention a task that releases and immediately
re-acquires must not jump ahead of an already-parked waiter, and parked waiters
must be served in arrival order regardless of how the driver wakes them.
"""

from __future__ import annotations

from collections import deque
from collections.abc import AsyncGenerator

import anyio
from snektest import assert_eq, fixture, load_fixture, test

from snekql.mariadb.runtime import MariaDBConnectionPool

_TIMEOUT = 30.0


class _FakeConnection:
    """Stand-in connection that reports itself already configured."""

    def __init__(self) -> None:
        # Pre-mark as configured so the pool skips the real session settings,
        # which would otherwise issue SQL against a live server.
        self._snekql_configured: bool = True


class _UnfairAiomysqlPool:
    """Bounded pool that wakes blocked acquirers LIFO, like aiomysql.

    Mirrors the lack of fairness in the real driver: when no connection is free
    an acquirer parks, and ``release`` hands the freed connection to the most
    recently parked waiter. Without the FIFO gate this reverses service order.
    """

    def __init__(self, maxsize: int) -> None:
        self._free: deque[_FakeConnection] = deque(
            _FakeConnection() for _ in range(maxsize)
        )
        self._waiters: list[anyio.Event] = []

    async def acquire(self) -> _FakeConnection:
        if not self._free:
            event = anyio.Event()
            self._waiters.append(event)
            await event.wait()
        return self._free.popleft()

    def release(self, connection: object) -> None:
        self._free.append(connection)  # type: ignore[arg-type]
        if self._waiters:
            self._waiters.pop().set()

    def close(self) -> None:
        pass

    async def wait_closed(self) -> None:
        pass


@fixture
async def single_connection_pool() -> AsyncGenerator[MariaDBConnectionPool]:
    """Provide a ``pool_size=1`` pool over an unfair fake aiomysql pool."""

    pool = MariaDBConnectionPool(_UnfairAiomysqlPool(maxsize=1), pool_size=1)
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

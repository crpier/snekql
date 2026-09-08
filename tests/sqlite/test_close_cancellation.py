"""Caller cancellation cannot abandon an owned SQLite close operation."""

from __future__ import annotations

import asyncio
from unittest.mock import patch

from aiosqlite import Connection
from anyio import Event, fail_after, sleep, wait_all_tasks_blocked
from anyio.lowlevel import checkpoint
from snektest import Param, assert_eq, assert_raises, test

from snekql import sqlite


@test(
    [Param(value=1, name="once"), Param(value=3, name="repeated")],
    mark="medium",
)
async def cancelled_close_can_be_awaited_again(attempts: int) -> None:
    """A cancelled closer cannot permanently strand the pool's closing state."""

    database = await sqlite.Database.initialize(
        database=":memory:", acquire_timeout=0.2
    )
    async with database.transaction():
        for _ in range(attempts):
            closing = asyncio.create_task(database.close())
            await wait_all_tasks_blocked()
            closing.cancel()
            with assert_raises(asyncio.CancelledError):
                await closing

    with fail_after(1):
        await database.close()
    with assert_raises(sqlite.DatabaseClosedError):
        database.transaction()


@test(mark="medium")
async def cancelled_idle_close_keeps_physical_cleanup_owned() -> None:
    """A cancelled waiter cannot abandon a connection detached from the idle list."""

    database = await sqlite.Database.initialize(database=":memory:")
    original_close = Connection.close
    started = Event()
    allow_close = Event()
    completed: list[Connection] = []
    captured: list[Connection] = []

    async def paused_close(connection: Connection) -> None:
        captured.append(connection)
        started.set()
        await allow_close.wait()
        await original_close(connection)
        completed.append(connection)

    try:
        with patch.object(Connection, "close", paused_close):
            closing = asyncio.create_task(database.close())
            with fail_after(1):
                await started.wait()
            closing.cancel()
            with assert_raises(asyncio.CancelledError):
                await closing
            with assert_raises(sqlite.DatabaseClosingError):
                database.transaction()
            allow_close.set()
            with fail_after(1):
                await database.close()
        assert_eq(len(completed), 1)
        assert_eq(len(captured), 1)
    finally:
        allow_close.set()
        # Driver-level fallback keeps a failing regression from leaving a worker
        # alive. Assertions above must pass without this test-only cleanup.
        for connection in captured:
            await original_close(connection)


@test(mark="medium")
async def concurrent_closers_await_one_shutdown() -> None:
    """Close callers share completion rather than competing for shutdown ownership."""

    database = await sqlite.Database.initialize(database=":memory:")
    async with database.transaction():
        first = asyncio.create_task(database.close())
        second = asyncio.create_task(database.close())
        await wait_all_tasks_blocked()
    with fail_after(1):
        await asyncio.gather(first, second)

    with assert_raises(sqlite.DatabaseClosedError):
        database.transaction()


@test(mark="medium")
async def abandoned_close_timeout_remains_retryable() -> None:
    """An owned close still obeys its wait deadline when its caller stops waiting."""

    async with await sqlite.Database.initialize(
        database=":memory:", acquire_timeout=0.2
    ) as database:
        async with database.transaction():
            closing = asyncio.create_task(database.close())
            with fail_after(1):
                while True:
                    try:
                        database.transaction()
                    except sqlite.DatabaseClosingError:
                        break
                    await checkpoint()
            closing.cancel()
            with assert_raises(asyncio.CancelledError):
                await closing
            with fail_after(1):
                while True:
                    try:
                        database.transaction()
                    except sqlite.DatabaseClosingError:
                        await sleep(0.01)
                    else:
                        break
        async with database.transaction():
            pass

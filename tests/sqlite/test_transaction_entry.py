"""Single-use transaction entry includes the time spent acquiring a connection."""

from __future__ import annotations

import asyncio
from collections.abc import Iterable
from unittest.mock import patch

from aiosqlite import Connection, Cursor
from anyio import CancelScope, Event, fail_after, wait_all_tasks_blocked
from snektest import Param, assert_eq, assert_raises, test

from snekql import sqlite


@test(mark="medium")
async def concurrent_transaction_entry_is_rejected() -> None:
    """Two callers cannot queue separate physical entries on the same transaction."""

    async with await sqlite.Database.initialize(
        database=":memory:", pool_size=1
    ) as database:
        transaction = database.transaction()
        outcomes: list[str] = []

        async def enter() -> None:
            try:
                async with transaction:
                    outcomes.append("entered")
            except sqlite.TransactionReuseError:
                outcomes.append("rejected")

        with fail_after(2):
            async with database.transaction():
                first = asyncio.create_task(enter())
                second = asyncio.create_task(enter())
                await wait_all_tasks_blocked()
                while_waiting = list(outcomes)
            await asyncio.gather(first, second)

    assert_eq(while_waiting, ["rejected"])
    assert_eq(sorted(outcomes), ["entered", "rejected"])


@test(mark="medium")
async def failed_acquisition_can_be_retried() -> None:
    """An acquisition timeout before BEGIN does not consume the transaction object."""

    async with await sqlite.Database.initialize(database=":memory:") as database:
        transaction = database.transaction(timeout=0.05)
        async with database.transaction():
            with assert_raises(sqlite.PoolTimeoutError):
                async with transaction:
                    pass
        async with transaction:
            pass
        with assert_raises(sqlite.TransactionReuseError):
            async with transaction:
                pass


@test(
    [Param(value="native", name="native"), Param(value="scope", name="anyio")],
    mark="medium",
)
async def cancelled_acquisition_can_be_retried(cancellation: str) -> None:
    """Native and AnyIO cancellation release a pre-BEGIN entry reservation."""

    async with await sqlite.Database.initialize(database=":memory:") as database:
        transaction = database.transaction()
        cancel_scope = CancelScope()

        async def enter() -> None:
            with cancel_scope:
                async with transaction:
                    pass

        with fail_after(2):
            async with database.transaction():
                pending = asyncio.create_task(enter())
                await wait_all_tasks_blocked()
                if cancellation == "native":
                    pending.cancel()
                    with assert_raises(asyncio.CancelledError):
                        await pending
                else:
                    cancel_scope.cancel()
                    await pending
            async with transaction:
                pass


@test(mark="medium")
async def entry_remains_reserved_until_begin_finishes() -> None:
    """A second caller cannot enter during the driver's BEGIN operation."""

    original_execute = Connection.execute
    begin_started = Event()
    allow_begin = Event()

    async def paused_begin(
        connection: Connection,
        sql: str,
        parameters: Iterable[object] | None = None,
    ) -> Cursor:
        if sql == "BEGIN":
            begin_started.set()
            await allow_begin.wait()
        return await original_execute(connection, sql, parameters)

    async with await sqlite.Database.initialize(database=":memory:") as database:
        transaction = database.transaction()

        async def enter() -> None:
            async with transaction:
                pass

        with patch.object(Connection, "execute", paused_begin):
            pending = asyncio.create_task(enter())
            try:
                with fail_after(2):
                    await begin_started.wait()
                    with assert_raises(sqlite.TransactionReuseError):
                        async with transaction:
                            pass
            finally:
                allow_begin.set()
                await pending

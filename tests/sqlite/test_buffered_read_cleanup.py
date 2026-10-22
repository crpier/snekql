"""Buffered reads cannot hide native cursor cleanup failures (#496)."""

import asyncio
import sqlite3
import threading
from functools import partial
from pathlib import Path
from typing import Any, ClassVar
from unittest.mock import patch

from anyio import Event, TemporaryDirectory, fail_after
from snektest import Param, assert_eq, assert_raises, test

from snekql import sqlite
from snekql.errors import DatabaseRuntimeError, ExecutionError
from tests.helpers import initialized_database


class CleanupReading[S = sqlite.Pending](sqlite.Model[S]):
    __row_type__: ClassVar[sqlite.ReadType[CleanupReading[sqlite.Row]]]
    value: CleanupReading.Col[int] = sqlite.Integer()


@test(mark="medium")
async def buffered_read_cleanup_failure_invalidates_transaction_and_recovers() -> None:
    """A native cleanup failure is an execution failure, not a successful read."""
    query = sqlite.select(CleanupReading.value)
    target_sql = query.compile().sql
    inject_failure = True

    class FaultCursor(sqlite3.Cursor):
        fail_close = False

        def close(self) -> None:
            super().close()
            if self.fail_close:
                msg = "injected native cursor cleanup failure"
                raise sqlite3.OperationalError(msg)

    class FaultConnection(sqlite3.Connection):
        def execute(self, sql: str, parameters: Any = (), /) -> sqlite3.Cursor:
            cursor = self.cursor(factory=FaultCursor)
            cursor.execute(sql, parameters)
            cursor.fail_close = inject_failure and sql == target_sql
            return cursor

    # Fault injection uses sqlite3's public connection/cursor factory extension,
    # not snekql internals or a particular asynchronous driver's call sequence.
    connect = partial(sqlite3.connect, factory=FaultConnection)
    with patch.object(sqlite3, "connect", connect):
        async with (
            TemporaryDirectory() as directory,
            await initialized_database(
                database=Path(directory) / "cleanup.db",
                models=[CleanupReading],
                pool_size=1,
            ) as database,
        ):
            async with database.transaction() as transaction:
                await transaction.execute(sqlite.insert(CleanupReading(value=7)))
            async with database.transaction() as transaction:
                with assert_raises(ExecutionError):
                    await transaction.fetch_all(query)
                inject_failure = False
                with assert_raises(DatabaseRuntimeError):
                    await transaction.fetch_all(query)
            with fail_after(2):
                async with database.transaction() as transaction:
                    assert_eq(await transaction.fetch_all(query), [7])


@test(
    [Param(value="timeout", name="timeout"), Param(value="cancel", name="cancel")],
    mark="medium",
)
async def interrupted_read_cleanup_retains_capacity_until_physical_close(
    interruption: str,
) -> None:
    """An interrupted cleanup cannot admit a replacement while native work runs."""
    query = sqlite.select(CleanupReading.value)
    target_sql = query.compile().sql
    started = Event()
    release = threading.Event()
    loop = asyncio.get_running_loop()
    inject_pause = True

    class PausedCursor(sqlite3.Cursor):
        pause_close = False

        def close(self) -> None:
            try:
                if self.pause_close:
                    loop.call_soon_threadsafe(started.set)
                    if not release.wait(10):
                        msg = "test did not release native cleanup"
                        raise TimeoutError(msg)
            finally:
                super().close()

    class PausedConnection(sqlite3.Connection):
        def execute(self, sql: str, parameters: Any = (), /) -> sqlite3.Cursor:
            cursor = self.cursor(factory=PausedCursor)
            cursor.execute(sql, parameters)
            cursor.pause_close = inject_pause and sql == target_sql
            return cursor

    connect = partial(sqlite3.connect, factory=PausedConnection)
    with patch.object(sqlite3, "connect", connect):
        async with (
            TemporaryDirectory() as directory,
            await initialized_database(
                database=Path(directory) / "interrupted.db",
                models=[CleanupReading],
                pool_size=1,
            ) as database,
        ):
            async with database.transaction() as transaction:
                await transaction.execute(sqlite.insert(CleanupReading(value=7)))

            async def read() -> None:
                async with database.transaction(timeout=0.25) as transaction:
                    await transaction.fetch_all(query)

            pending = asyncio.create_task(read())
            try:
                with fail_after(2):
                    await started.wait()
                    if interruption == "cancel":
                        pending.cancel()
                        with assert_raises(asyncio.CancelledError):
                            await pending
                    else:
                        with assert_raises(sqlite.DatabaseOperationTimeoutError):
                            await pending
                assert_eq(database.pool_stats().occupied, 1)
                with assert_raises(sqlite.PoolTimeoutError):
                    async with database.transaction(timeout=0.05):
                        pass
            finally:
                inject_pause = False
                release.set()
                await asyncio.gather(pending, return_exceptions=True)
            with fail_after(2):
                async with database.transaction() as transaction:
                    assert_eq(await transaction.fetch_all(query), [7])

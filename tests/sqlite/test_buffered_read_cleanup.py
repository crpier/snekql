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


@test(mark="medium")
async def buffered_fetch_failure_keeps_cleanup_failure_precedence() -> None:
    """A failing fetch still closes; a cleanup failure remains the primary cause."""
    query = sqlite.select(CleanupReading.value)
    target_sql = query.compile().sql

    class FaultCursor(sqlite3.Cursor):
        inject_failure = False

        def fetchall(self) -> list[Any]:
            if self.inject_failure:
                msg = "injected native fetch failure"
                raise sqlite3.OperationalError(msg)
            return super().fetchall()

        def close(self) -> None:
            super().close()
            if self.inject_failure:
                msg = "injected native cleanup failure"
                raise sqlite3.OperationalError(msg)

    class FaultConnection(sqlite3.Connection):
        def execute(self, sql: str, parameters: Any = (), /) -> sqlite3.Cursor:
            cursor = self.cursor(factory=FaultCursor)
            cursor.execute(sql, parameters)
            cursor.inject_failure = sql == target_sql
            return cursor

    connect = partial(sqlite3.connect, factory=FaultConnection)
    with patch.object(sqlite3, "connect", connect):
        async with (
            await initialized_database(
                sqlite.Config(database=":memory:", parameter_visibility="values"),
                models=[CleanupReading],
            ) as database,
            database.transaction() as transaction,
        ):
            with assert_raises(ExecutionError) as caught:
                await transaction.fetch_all(query)
            assert_eq(
                str(caught.exception.__cause__), "injected native cleanup failure"
            )


@test(
    [Param(value="fetch", name="fetch"), Param(value="close", name="close")],
    mark="medium",
)
async def late_buffered_constraint_does_not_become_savepoint_recoverable(
    stage: str,
) -> None:
    """Only execution-time constraints can recover through a savepoint."""
    query = sqlite.select(CleanupReading.value)
    target_sql = query.compile().sql
    inject_failure = True

    def fail() -> None:
        error = sqlite3.IntegrityError("injected late constraint")
        error.sqlite_errorcode = sqlite3.SQLITE_CONSTRAINT_UNIQUE
        raise error

    class FaultCursor(sqlite3.Cursor):
        targeted = False

        def fetchall(self) -> list[Any]:
            if self.targeted and stage == "fetch":
                fail()
            return super().fetchall()

        def close(self) -> None:
            super().close()
            if self.targeted and stage == "close":
                fail()

    class FaultConnection(sqlite3.Connection):
        def execute(self, sql: str, parameters: Any = (), /) -> sqlite3.Cursor:
            cursor = self.cursor(factory=FaultCursor)
            cursor.execute(sql, parameters)
            cursor.targeted = inject_failure and sql == target_sql
            return cursor

    connect = partial(sqlite3.connect, factory=FaultConnection)
    with patch.object(sqlite3, "connect", connect):
        async with (
            await initialized_database(
                database=":memory:", models=[CleanupReading]
            ) as database,
            database.transaction() as transaction,
        ):
            with assert_raises(ExecutionError):
                async with transaction.begin_nested():
                    await transaction.fetch_all(query)
            inject_failure = False
            with assert_raises(DatabaseRuntimeError):
                await transaction.fetch_all(query)


@test(mark="medium")
async def buffered_execution_failure_preserves_explicit_driver_cause() -> None:
    """Values diagnostics retain a native exception's explicit causal chain."""
    query = sqlite.select(CleanupReading.value)
    target_sql = query.compile().sql

    class FaultConnection(sqlite3.Connection):
        def execute(self, sql: str, parameters: Any = (), /) -> sqlite3.Cursor:
            if sql == target_sql:
                cause = ValueError("native execution cause")
                msg = "native execution failure"
                raise sqlite3.IntegrityError(msg) from cause
            return super().execute(sql, parameters)

    connect = partial(sqlite3.connect, factory=FaultConnection)
    with patch.object(sqlite3, "connect", connect):
        async with (
            await initialized_database(
                sqlite.Config(database=":memory:", parameter_visibility="values"),
                models=[CleanupReading],
            ) as database,
            database.transaction() as transaction,
        ):
            with assert_raises(ExecutionError) as caught:
                await transaction.fetch_all(query)
            native = caught.exception.__cause__
            assert native is not None
            assert_eq(str(native.__cause__), "native execution cause")

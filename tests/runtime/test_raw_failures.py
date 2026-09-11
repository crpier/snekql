"""Controlled adapter results that real databases cannot produce reliably."""

import asyncio
import logging
from collections.abc import Generator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from io import StringIO
from traceback import format_exception
from typing import Any, Literal
from unittest.mock import patch

from snektest import Param, assert_eq, assert_raises, test

from snekql import sqlite
from snekql._raw import NativeParameters
from snekql.sqlite.runtime import SQLiteConnectionAdapter


@dataclass
class ControlledCursor:
    """A driver boundary with independently controlled rows and completion."""

    column_names: tuple[str, ...] | None = ("value",)
    rows: tuple[tuple[object, ...], ...] = ((1, 2),)
    cancel_fetch: bool = False
    failure: Literal["fetch", "cleanup", "metadata"] | None = None
    max_fetch_size: int | None = None
    closed: bool = False
    rowcount: int = -1

    @property
    def columns(self) -> tuple[str, ...] | None:
        if self.failure == "metadata":
            msg = "metadata_secret"
            raise sqlite.DatabaseRuntimeError(msg)
        return self.column_names

    async def fetchone(self) -> Sequence[object] | None:
        rows = await self.fetchmany(1)
        return rows[0] if rows else None

    async def fetchmany(self, size: int = 1) -> Sequence[Sequence[object]]:
        if self.max_fetch_size is not None and size > self.max_fetch_size:
            msg = "capped consumption requested too many rows"
            raise sqlite.DatabaseRuntimeError(msg)
        if self.cancel_fetch:
            raise asyncio.CancelledError
        if self.failure == "fetch":
            msg = "driver_secret"
            raise sqlite.DatabaseRuntimeError(msg)
        rows, self.rows = self.rows[:size], self.rows[size:]
        return rows

    async def fetchall(self) -> Sequence[Sequence[object]]:
        return await self.fetchmany(len(self.rows))

    async def complete(self) -> bool:
        self.closed = True
        self.rowcount = 123
        if self.failure == "cleanup":
            msg = "cleanup_secret"
            raise sqlite.DatabaseRuntimeError(msg)
        return False

    async def close(self) -> None:
        self.closed = True


@contextmanager
def substitute_cursor(cursor: ControlledCursor) -> Generator[None]:
    """Inject a fake only at the approved native adapter boundary."""

    async def execute_raw(
        self: SQLiteConnectionAdapter,
        sql: str,
        params: NativeParameters,
        *,
        stream: bool = False,
    ) -> ControlledCursor:
        del self, sql, params, stream
        return cursor

    with patch.object(SQLiteConnectionAdapter, "execute_raw", execute_raw):
        yield


@test(
    [
        Param[Literal["mapping", "tuple"]](value="mapping", name="mapping"),
        Param[Literal["mapping", "tuple"]](value="tuple", name="tuple"),
    ],
    mark="medium",
)
async def row_width_must_match_metadata(mode: Literal["mapping", "tuple"]) -> None:
    """Neither dictionary zip truncation nor tuple packaging hides malformed rows."""

    cursor = ControlledCursor()
    async with (
        await sqlite.Database.initialize(database=":memory:") as database,
        database.transaction() as transaction,
    ):
        with substitute_cursor(cursor), assert_raises(sqlite.RawResultShapeError):
            await transaction.fetch_all(sqlite.raw("SELECT secret", row_mode=mode))

    assert_eq(cursor.closed, True)


@test(mark="medium")
async def failed_stream_is_closed_before_error_propagates() -> None:
    """Catching a bad row cannot resume after it or yield part of its chunk."""

    cursor = ControlledCursor(rows=((1,), (2, 3), (4,)))
    async with (
        await sqlite.Database.initialize(database=":memory:") as database,
        database.transaction() as transaction,
    ):
        with substitute_cursor(cursor):
            async with transaction.fetch_chunks(
                sqlite.raw("SELECT secret"), size=2
            ) as stream:
                with assert_raises(sqlite.RawResultShapeError):
                    await anext(stream)
                assert_eq(cursor.closed, True)
                with assert_raises(StopAsyncIteration):
                    await anext(stream)


@test(
    [
        Param[Literal["fetch", "cleanup", "metadata"]](value="fetch", name="fetch"),
        Param[Literal["fetch", "cleanup", "metadata"]](value="cleanup", name="cleanup"),
        Param[Literal["fetch", "cleanup", "metadata"]](
            value="metadata", name="metadata"
        ),
    ],
    [Param(value="buffered", name="buffered"), Param(value="stream", name="stream")],
    mark="medium",
)
async def driver_failures_omit_secret_diagnostics(
    stage: Literal["fetch", "cleanup", "metadata"],
    consumption: str,
) -> None:
    """Normal exception-chain rendering and package logs never copy driver text."""

    cursor = ControlledCursor(failure=stage)
    statement = sqlite.raw(
        "SELECT 'sql_secret' AS column_secret",
        params={"parameter_secret": "value_secret"},
    )
    captured = StringIO()
    handler = logging.StreamHandler(captured)
    logger = logging.getLogger("snekql")
    logger.addHandler(handler)
    try:
        async with await sqlite.Database.initialize(database=":memory:") as database:
            with assert_raises(sqlite.ExecutionError) as raised:
                async with database.transaction() as transaction:
                    with substitute_cursor(cursor):
                        if consumption == "stream":
                            async with transaction.fetch_chunks(
                                statement, size=1
                            ) as stream:
                                await anext(stream)
                        else:
                            await transaction.fetch_all(statement)
        rendered = captured.getvalue() + "".join(format_exception(raised.exception))
    finally:
        logger.removeHandler(handler)
    for marker in (
        "driver_secret",
        "metadata_secret",
        "cleanup_secret",
        "sql_secret",
        "column_secret",
        "parameter_secret",
        "value_secret",
    ):
        assert_eq(marker in rendered, False)


@test(mark="medium")
async def cleanup_failure_does_not_replace_cancellation() -> None:
    """Cancellation retains control flow when the adapter also fails completion."""

    cursor = ControlledCursor(cancel_fetch=True, failure="cleanup")
    async with await sqlite.Database.initialize(database=":memory:") as database:
        with assert_raises(asyncio.CancelledError):
            async with database.transaction() as transaction:
                with substitute_cursor(cursor):
                    await transaction.fetch_all(sqlite.raw("SELECT 1"))


@test(mark="medium")
async def rollback_logging_does_not_reveal_raw_driver_text() -> None:
    """Transaction cleanup retains raw's diagnostic policy after a result error."""

    async def failed_rollback(self: SQLiteConnectionAdapter) -> None:
        del self
        msg = "rollback_secret"
        raise sqlite.DatabaseRuntimeError(msg)

    captured = StringIO()
    handler = logging.StreamHandler(captured)
    logger = logging.getLogger("snekql")
    logger.addHandler(handler)
    try:
        async with await sqlite.Database.initialize(database=":memory:") as database:
            with patch.object(SQLiteConnectionAdapter, "rollback", failed_rollback):
                with assert_raises(sqlite.RawResultShapeError):
                    async with database.transaction() as transaction:
                        await transaction.execute(sqlite.raw("SELECT 1"))
    finally:
        logger.removeHandler(handler)

    assert_eq("rollback_secret" in captured.getvalue(), False)


@test(mark="medium")
async def metadata_failure_completes_opened_cursor() -> None:
    """A failing metadata accessor cannot orphan a successfully opened cursor."""

    cursor = ControlledCursor(failure="metadata")
    async with await sqlite.Database.initialize(database=":memory:") as database:
        with assert_raises(sqlite.ExecutionError):
            async with database.transaction() as transaction:
                with substitute_cursor(cursor):
                    await transaction.fetch_all(sqlite.raw("SELECT 1"))

    assert_eq(cursor.closed, True)


@test(mark="medium")
async def raw_stream_rejects_consumption_by_another_task() -> None:
    """A foreign task cannot use the stream owner's transaction connection."""

    async with (
        await sqlite.Database.initialize(database=":memory:") as database,
        database.transaction() as transaction,
        transaction.fetch_chunks(sqlite.raw("SELECT 1 AS value"), size=1) as stream,
    ):
        with assert_raises(sqlite.DatabaseRuntimeError):
            await asyncio.create_task(anext(stream))
        observed = await anext(stream)

    assert_eq(observed, [{"value": 1}])


@test(mark="medium")
async def non_string_metadata_is_a_safe_shape_error() -> None:
    """Malformed adapter metadata cannot turn mapping keys into arbitrary objects."""

    invalid_columns: Any = (42,)
    cursor = ControlledCursor(column_names=invalid_columns, rows=((1,),))
    async with (
        await sqlite.Database.initialize(database=":memory:") as database,
        database.transaction() as transaction,
    ):
        with substitute_cursor(cursor), assert_raises(sqlite.RawResultShapeError):
            await transaction.fetch_one(sqlite.raw("SELECT 1"))


@test(mark="medium")
async def execute_captures_rowcount_without_fetching() -> None:
    """Completion changing driver state cannot overwrite the first response's count."""

    cursor = ControlledCursor(column_names=None, rowcount=-7, failure="fetch")
    async with (
        await sqlite.Database.initialize(database=":memory:") as database,
        database.transaction() as transaction,
    ):
        with substitute_cursor(cursor):
            observed = await transaction.execute(sqlite.raw("command"))

    assert_eq(observed, -7)


@test(mark="medium")
async def invalid_raw_stream_size_is_sanitized() -> None:
    """Boundary validation must not render rejected method option values."""

    size: Any = "size_secret"
    async with (
        await sqlite.Database.initialize(database=":memory:") as database,
        database.transaction() as transaction,
    ):
        with assert_raises(sqlite.QueryConstructionError) as raised:
            transaction.fetch_chunks(sqlite.raw("SELECT 1"), size=size)

    assert_eq("size_secret" in "".join(format_exception(raised.exception)), False)


@test(
    [
        Param(value="fetch_one", name="one"),
        Param(value="fetch_one_or_none", name="optional"),
    ],
    mark="medium",
)
async def cardinality_is_capped_before_row_width_checks(method: str) -> None:
    """Capped reads request at most two rows and reject excess before packaging."""

    cursor = ControlledCursor(rows=((1, 2), (3, 4), (5, 6)), max_fetch_size=2)
    async with (
        await sqlite.Database.initialize(database=":memory:") as database,
        database.transaction() as transaction,
    ):
        with substitute_cursor(cursor), assert_raises(sqlite.MultipleResultsError):
            await getattr(transaction, method)(sqlite.raw("SELECT 1"))

    assert_eq(cursor.closed, True)

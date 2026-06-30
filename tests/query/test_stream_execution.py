"""Streaming/chunked select execution and cursor-cleanup tests for fetch_chunks."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Any, cast

from snektest import assert_eq, assert_raises, test
from snektest.assertions import assert_true

from snekql.model import BackendFamily, Table
from snekql.query import AnySelectQuery
from snekql.runtime import RuntimeConnection, Transaction, TransactionMode
from snekql.sqlite import (
    PENDING_GENERATION,
    ExecutionError,
    Fetched,
    Integer,
    Model,
    Pending,
    QueryCompilationError,
    QueryConstructionError,
    SchemaPolicy,
    Text,
    insert,
    select,
)
from snekql.validation import NonNegativeFloat
from tests.helpers import initialized_database


class _StreamUser[S = Pending](Model[S, "_StreamUser[Fetched]"]):
    """Table model selected through the streaming runtime."""

    id: _StreamUser.GenCol[int] = Integer(
        primary_key=True,
        auto_increment=True,
        default=PENDING_GENERATION,
    )
    email: _StreamUser.Col[str] = Text(nullable=False)


@test(mark="medium")
async def fetch_chunks_yields_model_batches_of_requested_size() -> None:
    """Streaming a model select yields fetched-state batches sized by ``size``."""

    database = await initialized_database(database=":memory:", models=[_StreamUser])
    try:
        async with database.transaction() as tx:
            for index in range(5):
                await tx.execute(insert(_StreamUser(email=f"user{index}@example.com")))
            async with tx.fetch_chunks(select(_StreamUser).all(), size=2) as stream:
                batches: list[list[_StreamUser[Fetched]]] = [
                    batch async for batch in stream
                ]
    finally:
        await database.close()

    assert_eq([len(batch) for batch in batches], [2, 2, 1])
    emails = [user.email for batch in batches for user in batch]
    assert_eq(
        emails,
        [f"user{index}@example.com" for index in range(5)],
    )


@test(mark="medium")
async def fetch_chunks_streams_scalar_values_for_single_column_selects() -> None:
    """Single-column streaming yields decoded scalar batches, not row tuples."""

    database = await initialized_database(database=":memory:", models=[_StreamUser])
    try:
        async with database.transaction() as tx:
            for index in range(3):
                await tx.execute(insert(_StreamUser(email=f"user{index}@example.com")))
            async with tx.fetch_chunks(
                select(_StreamUser.email).all(), size=2
            ) as stream:
                batches: list[list[str]] = [batch async for batch in stream]
    finally:
        await database.close()

    assert_eq([len(batch) for batch in batches], [2, 1])
    assert_eq(
        [email for batch in batches for email in batch],
        [f"user{index}@example.com" for index in range(3)],
    )


@test(mark="medium")
async def fetch_chunks_over_empty_result_yields_no_batches() -> None:
    """An empty result set yields no batches and closes cleanly."""

    database = await initialized_database(database=":memory:", models=[_StreamUser])
    try:
        async with (
            database.transaction() as tx,
            tx.fetch_chunks(select(_StreamUser).all(), size=10) as stream,
        ):
            batches = [batch async for batch in stream]
    finally:
        await database.close()

    assert_eq(batches, [])


@test(mark="medium")
async def fetch_chunks_rejects_non_positive_size() -> None:
    """``size`` must be a positive integer; zero fails fast at the call site."""

    database = await initialized_database(database=":memory:", models=[_StreamUser])
    try:
        async with database.transaction() as tx:
            with assert_raises(QueryConstructionError):
                _ = tx.fetch_chunks(select(_StreamUser).all(), size=0)
    finally:
        await database.close()


@test(mark="medium")
async def fetch_chunks_rejects_non_select_query() -> None:
    """Streaming a non-select query is rejected like the other fetch verbs."""

    database = await initialized_database(database=":memory:", models=[_StreamUser])
    try:
        async with database.transaction() as tx:
            fetch_chunks = cast("Callable[..., object]", tx.fetch_chunks)
            with assert_raises(QueryCompilationError):
                _ = fetch_chunks(insert(_StreamUser(email="x@example.com")), size=2)
    finally:
        await database.close()


class _CleanupCursor:
    """Runtime cursor that serves preset rows in batches and counts closes."""

    def __init__(
        self,
        rows: Sequence[Sequence[object]],
        *,
        fail_after: int | None = None,
    ) -> None:
        self.close_count: int = 0
        self._rows: list[Sequence[object]] = list(rows)
        self._served: int = 0
        self._calls: int = 0
        self._fail_after: int | None = fail_after

    @property
    def rowcount(self) -> int:
        return len(self._rows)

    async def fetchone(self) -> Sequence[object] | None:
        return None

    async def fetchmany(self, size: int = 1) -> Sequence[Sequence[object]]:
        self._calls += 1
        if self._fail_after is not None and self._calls > self._fail_after:
            msg = "driver exploded mid-stream"
            raise RuntimeError(msg)
        batch = self._rows[self._served : self._served + size]
        self._served += len(batch)
        return batch

    async def fetchall(self) -> Sequence[Sequence[object]]:
        return self._rows

    async def close(self) -> None:
        self.close_count += 1


class _CleanupConnection:
    """Connection fake handing back one preset streaming cursor."""

    def __init__(self, cursor: _CleanupCursor) -> None:
        self.cursor: _CleanupCursor = cursor

    async def begin(self, mode: TransactionMode = "deferred") -> None:
        _ = mode

    async def commit(self) -> None:
        return None

    async def rollback(self) -> None:
        return None

    async def execute(self, sql: str, params: tuple[object, ...]) -> _CleanupCursor:
        _ = sql
        _ = params
        return self.cursor

    async def execute_stream(
        self, sql: str, params: tuple[object, ...]
    ) -> _CleanupCursor:
        _ = sql
        _ = params
        return self.cursor


class _CleanupRuntime:
    """Runtime fake that streams preset rows and materializes the first column."""

    backend_family: BackendFamily = "sqlite"

    def __init__(self, connection: RuntimeConnection) -> None:
        self.acquire_timeout: NonNegativeFloat = 1.0
        self.connection: RuntimeConnection = connection

    async def acquire(self, acquisition_timeout: NonNegativeFloat) -> RuntimeConnection:
        _ = acquisition_timeout
        return self.connection

    async def release(self, connection: object) -> None:
        _ = connection

    async def close(self, close_timeout: NonNegativeFloat) -> None:
        _ = close_timeout

    def check_accepting_work(self) -> None:
        return None

    async def apply_migrations(self, migrations: dict[str, str]) -> None:
        _ = migrations

    async def verify_schema(
        self,
        models: Sequence[type[Table[Any]]],
        schema_policy: SchemaPolicy,
    ) -> None:
        _ = models
        _ = schema_policy

    def compile_select_sql(
        self, query: AnySelectQuery
    ) -> tuple[str, tuple[object, ...]]:
        _ = query
        return "SELECT 1", ()

    def compile_write_sql(self, query: object) -> tuple[str, tuple[object, ...]]:
        _ = query
        return "SELECT 1", ()

    def materialize_select_row(
        self,
        query: AnySelectQuery,
        row: Sequence[object],
        *,
        validate: bool = True,
    ) -> object:
        _ = query
        _ = validate
        return row[0]

    def materialize_write_rows(
        self,
        query: object,
        rows: Sequence[Sequence[object]],
        *,
        validate: bool = True,
    ) -> list[object]:
        _ = query
        _ = validate
        return list(rows)


def _cleanup_rows(count: int) -> list[tuple[int]]:
    return [(value,) for value in range(count)]


@test(mark="fast")
async def fetch_chunks_closes_cursor_on_full_consumption() -> None:
    """Fully draining the stream closes the cursor exactly once."""

    cursor = _CleanupCursor(_cleanup_rows(5))
    runtime = _CleanupRuntime(_CleanupConnection(cursor))
    transaction = Transaction(runtime=runtime, timeout=1.0)

    async with (
        transaction as tx,
        tx.fetch_chunks(select(_StreamUser.id).all(), size=2) as stream,
    ):
        collected = [value async for batch in stream for value in batch]

    assert_eq(collected, list(range(5)))
    assert_eq(cursor.close_count, 1)


@test(mark="fast")
async def fetch_chunks_closes_cursor_on_early_break() -> None:
    """Breaking out of the stream early still closes the cursor."""

    cursor = _CleanupCursor(_cleanup_rows(10))
    runtime = _CleanupRuntime(_CleanupConnection(cursor))
    transaction = Transaction(runtime=runtime, timeout=1.0)

    async with (
        transaction as tx,
        tx.fetch_chunks(select(_StreamUser.id).all(), size=2) as stream,
    ):
        async for _ in stream:
            break

    assert_eq(cursor.close_count, 1)


@test(mark="fast")
async def fetch_chunks_closes_cursor_on_iteration_error() -> None:
    """A driver failure mid-stream surfaces ExecutionError and closes the cursor."""

    cursor = _CleanupCursor(_cleanup_rows(10), fail_after=1)
    runtime = _CleanupRuntime(_CleanupConnection(cursor))
    transaction = Transaction(runtime=runtime, timeout=1.0)

    with assert_raises(ExecutionError):
        async with (
            transaction as tx,
            tx.fetch_chunks(select(_StreamUser.id).all(), size=2) as stream,
        ):
            async for _ in stream:
                pass

    assert_true(cursor.close_count >= 1)


class _ConsumerError(Exception):
    """Raised by the consumer body to exercise cleanup on caller-side failure."""


@test(mark="fast")
async def fetch_chunks_closes_cursor_on_consumer_exception() -> None:
    """An exception raised in the ``async for`` body still closes the cursor."""

    cursor = _CleanupCursor(_cleanup_rows(10))
    runtime = _CleanupRuntime(_CleanupConnection(cursor))
    transaction = Transaction(runtime=runtime, timeout=1.0)

    with assert_raises(_ConsumerError):
        async with (
            transaction as tx,
            tx.fetch_chunks(select(_StreamUser.id).all(), size=2) as stream,
        ):
            async for _ in stream:
                raise _ConsumerError

    assert_eq(cursor.close_count, 1)

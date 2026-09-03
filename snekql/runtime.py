"""Backend-neutral database lifecycle and transaction runtime."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator, Sequence
from pathlib import Path
from types import TracebackType
from typing import (
    Any,
    Literal,
    Never,
    Protocol,
    Self,
    TypeVar,
    TypeVarTuple,
    cast,
    overload,
)

import anyio
import anyio.lowlevel

from snekql._migrations import (
    MigrationPlan,
    MigrationResult,
    prepare_migrations,
)
from snekql._query_plan import SelectCardinality, SelectPlan, WritePlan
from snekql._runtime_selection import (
    RuntimeConfig,
    resolve_runtime_config,
    validate_model_backends,
)
from snekql.errors import (
    DatabaseRuntimeError,
    ExecutionError,
    MigrationDeclarationError,
    MultipleResultsError,
    QueryCompilationError,
    QueryConstructionError,
    TransactionClosedError,
    TransactionNotStartedError,
    TransactionReuseError,
)
from snekql.model import (
    BackendFamily,
    Table,
    require_model_backend,
    require_model_table_name,
)
from snekql.query import (
    AnySelectQuery,
    DeleteQuery,
    InsertManyQuery,
    InsertQuery,
    JoinModelQuery,
    SelectModelQuery,
    SelectTupleQuery,
    SelectValueQuery,
    UpdateQuery,
    _OptionalQueryShape,
    _QueryShape,
    _SelectableModelClass,
    _WriteShape,
)
from snekql.storage import SchemaPolicy
from snekql.validation import NonNegativeFloat, PositiveInt, validate_boundary

logger = logging.getLogger(__name__)

# Transaction begin mode. ``deferred`` opens a plain transaction that acquires
# no lock until its first write (the SQL default); ``immediate`` declares write
# intent up front so a backend that can take the writer lock eagerly does so,
# trading deferred read concurrency for fair, fail-fast writer-lock acquisition.
# SQLite honors this as ``BEGIN`` vs ``BEGIN IMMEDIATE``; row-locking backends
# treat it as a no-op (see each adapter's ``begin``).
type TransactionMode = Literal["deferred", "immediate"]

# ``fetch_all`` materializes and validates every row synchronously on the event
# loop. For large result sets that is a CPU-bound stretch that starves every
# other task on the loop, so the materialization loop yields a cooperative
# checkpoint every this-many rows. The interval is large enough that the
# per-checkpoint overhead is negligible on bounded results yet small enough that
# no single uninterrupted run blocks the loop for long. Callers with genuinely
# large results should stream with ``fetch_chunks`` instead.
FETCH_ALL_YIELD_INTERVAL = 1000


@validate_boundary(error_type=QueryConstructionError)
def _validate_chunk_size(*, size: PositiveInt) -> None:
    """Reject non-positive ``fetch_chunks`` batch sizes at the call site."""

    _ = size


SelectOwnerT = TypeVar("SelectOwnerT", bound=Table[Any])
OwnerT = TypeVar("OwnerT", bound=Table[Any])
ReadModelT = TypeVar("ReadModelT", bound=Table[Any])
# A single fresh variable used for both the scope and referenced unions of a
# projection select. Because the projection query pins its scope union to
# invariant and leaves its referenced union covariant, unifying both through
# one variable forces every referenced table to be in scope (i.e. joined).
ScopeRefT = TypeVar("ScopeRefT", bound=Table[Any])
T = TypeVar("T")
Ts = TypeVarTuple("Ts")


class RuntimeCursor(Protocol):
    """Cursor behavior required by backend-neutral transaction execution."""

    @property
    def rowcount(self) -> int: ...

    async def fetchone(self) -> Sequence[object] | None: ...

    async def fetchmany(self, size: int = ...) -> Sequence[Sequence[object]]: ...

    async def fetchall(self) -> Sequence[Sequence[object]]: ...

    async def close(self) -> None: ...


class RuntimeConnection(Protocol):
    """Connection behavior required by backend-neutral transactions."""

    async def begin(self, mode: TransactionMode) -> None: ...

    async def commit(self) -> None: ...

    async def rollback(self) -> None: ...

    async def execute(
        self,
        sql: str,
        params: tuple[object, ...],
    ) -> RuntimeCursor: ...

    async def execute_stream(
        self,
        sql: str,
        params: tuple[object, ...],
    ) -> RuntimeCursor:
        """Execute a select for incremental fetching.

        The returned cursor must stream rows from the server rather than buffer
        the full result set client-side, so callers can ``fetchmany`` over an
        unbounded result without loading it all into memory. The cursor must be
        fully consumed or closed before another statement runs on the
        connection.
        """
        ...


class QueryCodec(Protocol):
    """Query compile/materialize seam a backend adapter exposes as one object."""

    def compile_select_sql(
        self,
        query: AnySelectQuery,
    ) -> tuple[str, tuple[object, ...]]: ...

    def compile_select_plan[ResultT](
        self,
        query: _QueryShape[Any, Any, Any, ResultT],
        *,
        cardinality: SelectCardinality,
        validate: bool = True,
    ) -> SelectPlan[object]: ...

    def compile_write_plan[ResultT](
        self,
        query: _WriteShape[Any, ResultT],
        *,
        validate: bool = True,
    ) -> WritePlan[object]: ...

    def materialize_select_row(
        self,
        query: AnySelectQuery,
        row: Sequence[object],
        *,
        validate: bool = True,
    ) -> object: ...


class RuntimeBackend(Protocol):
    """Backend adapter seam used by Database and Transaction."""

    acquire_timeout: NonNegativeFloat
    backend_family: BackendFamily
    query_codec: QueryCodec

    async def acquire(
        self,
        acquisition_timeout: NonNegativeFloat,
    ) -> RuntimeConnection: ...

    async def release(self, connection: object) -> None: ...

    async def close(self, close_timeout: NonNegativeFloat) -> None: ...

    def check_accepting_work(self) -> None: ...

    def validate_migrations(self, migrations: MigrationPlan) -> None: ...

    async def apply_migrations(
        self,
        migrations: MigrationPlan,
        *,
        adopt_legacy: bool = False,
    ) -> MigrationResult: ...

    async def verify_migrations(self, migrations: MigrationPlan) -> None: ...

    async def verify_schema(
        self,
        models: Sequence[type[Table[Any]]],
        schema_policy: SchemaPolicy,
    ) -> None: ...


class ChunkStream[RowT]:
    """Incremental batch reader over one select, bound to a transaction.

    Created by ``Transaction.fetch_chunks``. It is both an async context manager
    and an async iterator: entering acquires the transaction connection and opens
    a streaming cursor, iterating yields lists of up to ``size`` materialized
    rows, and exiting closes the cursor and releases the connection regardless of
    how iteration ended. Use it inside ``async with`` rather than iterating the
    bare object so cleanup is deterministic.
    """

    def __init__(
        self,
        *,
        transaction: Transaction[Any],
        select_query: AnySelectQuery,
        lock: anyio.Lock,
        size: PositiveInt,
        validate: bool,
    ) -> None:
        self._transaction: Transaction[Any] = transaction
        self._select_query: AnySelectQuery = select_query
        self._lock: anyio.Lock = lock
        self._size: PositiveInt = size
        self._validate: bool = validate
        self._cursor: RuntimeCursor | None = None
        self._entered: bool = False
        self._sql: str = ""
        self._params: tuple[object, ...] = ()

    async def __aenter__(self) -> Self:
        if self._entered:
            msg = "chunk stream is already open"
            raise DatabaseRuntimeError(msg)
        self._entered = True
        transaction = self._transaction
        await self._lock.acquire()
        try:
            connection = transaction.require_connection()
            self._sql, self._params = (
                transaction.runtime.query_codec.compile_select_sql(self._select_query)
            )
            try:
                self._cursor = await connection.execute_stream(self._sql, self._params)
            except Exception as error:
                logger.exception(
                    "%s fetch_chunks query failed: %s params=%r",
                    transaction.runtime.backend_family,
                    self._sql,
                    self._params,
                )
                msg = "select failed"
                raise ExecutionError(msg, sql=self._sql, params=self._params) from error
        except BaseException:
            self._lock.release()
            raise
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        _ = exc_type
        _ = exc_value
        _ = traceback
        try:
            cursor = self._cursor
            self._cursor = None
            if cursor is not None:
                await cursor.close()
        finally:
            self._lock.release()

    def __aiter__(self) -> AsyncIterator[list[RowT]]:
        return self

    async def __anext__(self) -> list[RowT]:
        cursor = self._cursor
        if cursor is None:
            msg = "chunk stream is not open; use 'async with tx.fetch_chunks(...)'"
            raise DatabaseRuntimeError(msg)
        transaction = self._transaction
        try:
            rows = await cursor.fetchmany(self._size)
        except Exception as error:
            logger.exception(
                "%s fetch_chunks fetch failed: %s params=%r",
                transaction.runtime.backend_family,
                self._sql,
                self._params,
            )
            msg = "select failed"
            raise ExecutionError(msg, sql=self._sql, params=self._params) from error
        if not rows:
            raise StopAsyncIteration
        logger.debug(
            "%s fetch_chunks batch: %s params=%r rows=%d",
            transaction.runtime.backend_family,
            self._sql,
            self._params,
            len(rows),
        )
        # Materialization runs outside the fetch try/except, mirroring
        # ``fetch_all``: a decode/validation failure surfaces as its own error
        # type rather than being wrapped as a fetch-level ``ExecutionError``.
        return [
            cast(
                "RowT",
                transaction.runtime.query_codec.materialize_select_row(
                    self._select_query, tuple(row), validate=self._validate
                ),
            )
            for row in rows
        ]


class Transaction[FamilyT: BackendFamily]:
    """Async transaction that executes built snekql queries on one connection.

    Single-use and not re-entrant: enter it exactly once with ``async with
    db.transaction()``, run queries while it is open, and let the block exit
    commit (clean exit) or roll back (the block raised). Using it off that path
    raises a ``TransactionStateError`` subclass -- ``TransactionNotStartedError``
    before entry, ``TransactionClosedError`` after close, ``TransactionReuseError``
    on a second entry. Queries on one transaction are serialized on its single
    connection, so sharing it across tasks is safe but offers no parallelism; open
    separate transactions for concurrent work. See ``docs/error-handling.md``.

    >>> async def create_user(transaction: Transaction[Any], user: User[Pending]) -> None:
    ...     await transaction.execute(insert(user))
    """

    def __init__(
        self,
        *,
        runtime: RuntimeBackend | None = None,
        timeout: NonNegativeFloat = 0.0,
        mode: TransactionMode = "deferred",
    ) -> None:
        if runtime is None:
            msg = "use db.transaction(...) to start a transaction"
            raise DatabaseRuntimeError(msg)
        self.closed: bool = False
        self.connection: RuntimeConnection | None = None
        self.runtime: RuntimeBackend = runtime
        self.timeout: NonNegativeFloat = timeout
        self.mode: TransactionMode = mode
        self._lock: anyio.Lock = anyio.Lock()

    async def __aenter__(self) -> Self:
        # A Transaction is single-use and not re-entrant: it is entered exactly
        # once and cannot be restarted. Re-entering one that is still open, or
        # one already used and closed, is reuse rather than a closed-use error.
        if self.connection is not None:
            msg = (
                "transaction is already in progress; a Transaction is "
                "single-use and not re-entrant"
            )
            raise TransactionReuseError(msg)
        if self.closed:
            msg = (
                "transaction has already been used; create a new one with "
                "db.transaction()"
            )
            raise TransactionReuseError(msg)
        logger.debug(
            "%s transaction acquiring connection (timeout=%s, mode=%s)",
            self.runtime.backend_family,
            self.timeout,
            self.mode,
        )
        connection = await self.runtime.acquire(self.timeout)
        try:
            await connection.begin(self.mode)
        except Exception as error:
            logger.exception("%s transaction begin failed", self.runtime.backend_family)
            with anyio.CancelScope(shield=True):
                await self.runtime.release(connection)
            msg = "could not begin transaction"
            raise DatabaseRuntimeError(msg) from error
        self.connection = connection
        logger.debug("%s transaction begin", self.runtime.backend_family)
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        _ = exc_value
        _ = traceback
        with anyio.CancelScope(shield=True):
            async with self._lock:
                connection = self.connection
                if connection is None:
                    msg = "transaction is closed"
                    raise TransactionClosedError(msg)
                self.connection = None
                self.closed = True
                try:
                    if exc_type is None:
                        await connection.commit()
                        logger.debug(
                            "%s transaction commit", self.runtime.backend_family
                        )
                    else:
                        await connection.rollback()
                        logger.debug(
                            "%s transaction rollback (%s)",
                            self.runtime.backend_family,
                            exc_type.__name__,
                        )
                except Exception as error:
                    logger.exception(
                        "%s transaction close failed", self.runtime.backend_family
                    )
                    if exc_type is None:
                        msg = "could not close transaction"
                        raise DatabaseRuntimeError(msg) from error
                finally:
                    await self.runtime.release(connection)
                    logger.debug("%s transaction released", self.runtime.backend_family)

    @overload
    async def fetch_all[ScopeT, RowT](
        self,
        query: _QueryShape[FamilyT, ScopeT, ScopeT, RowT],
        *,
        validate: Literal[True] = True,
    ) -> list[RowT]: ...
    @overload
    async def fetch_all[ScopeT, RowT](
        self,
        query: _QueryShape[FamilyT, ScopeT, ScopeT, RowT],
        *,
        validate: Literal[False],
    ) -> list[object]: ...
    @overload
    async def fetch_all[ScopeT, RowT](
        self,
        query: _QueryShape[FamilyT, ScopeT, ScopeT, RowT],
        *,
        validate: bool,
    ) -> list[object]: ...
    async def fetch_all(
        self,
        query: object,
        *,
        validate: bool = True,
    ) -> list[object]:
        """Fetch and materialize every row of a select query into a list.

        Intended for bounded result sets. The whole result is loaded into memory
        and each row is validated synchronously on the event loop; the loop
        yields a cooperative checkpoint periodically so a large materialization
        does not monopolize it, but the read still holds the connection for its
        full duration. For large or unbounded results stream with ``fetch_chunks``
        instead, which fetches incrementally from a server-side cursor and keeps
        per-batch materialization small.
        """

        async with self._lock:
            connection = self.require_connection()
            select_query = self._require_select_query(query)
            self._validate_query_backend(select_query)
            sql, params = self.runtime.query_codec.compile_select_sql(select_query)
            try:
                cursor = await connection.execute(sql, params)
                try:
                    rows = await cursor.fetchall()
                finally:
                    await cursor.close()
            except Exception as error:
                logger.exception(
                    "%s fetch_all query failed: %s params=%r",
                    self.runtime.backend_family,
                    sql,
                    params,
                )
                msg = "select failed"
                raise ExecutionError(msg, sql=sql, params=params) from error
            logger.debug(
                "%s fetch_all executed: %s params=%r rows=%d",
                self.runtime.backend_family,
                sql,
                params,
                len(rows),
            )
            materialized: list[object] = []
            for index, row in enumerate(rows):
                if index and index % FETCH_ALL_YIELD_INTERVAL == 0:
                    await anyio.lowlevel.checkpoint()
                materialized.append(
                    self.runtime.query_codec.materialize_select_row(
                        select_query, tuple(row), validate=validate
                    )
                )
            return materialized

    @overload
    def fetch_chunks[ScopeT, RowT](
        self,
        query: _QueryShape[FamilyT, ScopeT, ScopeT, RowT],
        *,
        size: PositiveInt,
        validate: Literal[True] = True,
    ) -> ChunkStream[RowT]: ...
    @overload
    def fetch_chunks[ScopeT, RowT](
        self,
        query: _QueryShape[FamilyT, ScopeT, ScopeT, RowT],
        *,
        size: PositiveInt,
        validate: Literal[False],
    ) -> ChunkStream[object]: ...
    @overload
    def fetch_chunks[ScopeT, RowT](
        self,
        query: _QueryShape[FamilyT, ScopeT, ScopeT, RowT],
        *,
        size: PositiveInt,
        validate: bool,
    ) -> ChunkStream[object]: ...
    def fetch_chunks(
        self,
        query: object,
        *,
        size: PositiveInt,
        validate: bool = True,
    ) -> ChunkStream[object]:
        """Stream a select's rows in batches of at most ``size`` rows.

        Unlike ``fetch_all``, rows are fetched incrementally from a server-side
        (unbounded) cursor, so an arbitrarily large result set never has to fit
        in memory at once. Each batch holds up to ``size`` materialized rows; the
        final batch may be smaller and an empty result yields nothing.

        Returns a ``ChunkStream`` -- an async context manager that is also an
        async iterator. Always consume it inside ``async with`` so the cursor is
        closed and the connection released deterministically on full
        consumption, early ``break``, or an error mid-iteration::

            async with tx.fetch_chunks(select(User).all(), size=500) as stream:
                async for batch in stream:
                    ...

        The single transaction connection is held for the lifetime of the
        stream: no other query may run on this transaction, and the stream must
        be closed before the transaction commits. Open and consume the stream
        within one task.
        """

        _validate_chunk_size(size=size)
        select_query = self._require_select_query(query)
        self._validate_query_backend(select_query)
        return ChunkStream[object](
            transaction=self,
            select_query=select_query,
            lock=self._lock,
            size=size,
            validate=validate,
        )

    async def _fetch_capped_rows(
        self, query: object, *, method: str
    ) -> tuple[AnySelectQuery, list[tuple[object, ...]]]:
        """Run a select and fetch at most two rows for a cardinality-capped read.

        Both ``fetch_one`` and ``fetch_one_or_none`` cap result cardinality at
        one. Fetching two rows is the cheapest way to tell ``0`` from ``1`` from
        ``many`` without materializing an unbounded result set; the caller maps
        the row count onto its own contract. Runs under the held connection
        lock acquired by the caller.
        """

        connection = self.require_connection()
        select_query = self._require_select_query(query)
        self._validate_query_backend(select_query)
        sql, params = self.runtime.query_codec.compile_select_sql(select_query)
        try:
            cursor = await connection.execute(sql, params)
            try:
                rows = await cursor.fetchmany(2)
            finally:
                await cursor.close()
        except Exception as error:
            logger.exception(
                "%s %s query failed: %s params=%r",
                self.runtime.backend_family,
                method,
                sql,
                params,
            )
            msg = "select failed"
            raise ExecutionError(msg, sql=sql, params=params) from error
        logger.debug(
            "%s %s executed: %s params=%r rows=%d",
            self.runtime.backend_family,
            method,
            sql,
            params,
            len(rows),
        )
        return select_query, [tuple(row) for row in rows]

    @overload
    async def fetch_one[ScopeT, RowT](
        self,
        query: _QueryShape[FamilyT, ScopeT, ScopeT, RowT],
        *,
        validate: Literal[True] = True,
    ) -> RowT: ...
    @overload
    async def fetch_one[ScopeT, RowT](
        self,
        query: _QueryShape[FamilyT, ScopeT, ScopeT, RowT],
        *,
        validate: Literal[False],
    ) -> object: ...
    @overload
    async def fetch_one[ScopeT, RowT](
        self,
        query: _QueryShape[FamilyT, ScopeT, ScopeT, RowT],
        *,
        validate: bool,
    ) -> object: ...
    async def fetch_one(
        self,
        query: object,
        *,
        validate: bool = True,
    ) -> object:
        """Fetch the single row a select must match (exactly-one contract).

        Raises ``NoResultError`` when no row matches and ``MultipleResultsError``
        when more than one does. Because absence raises, a returned ``None`` for
        a single-value select unambiguously means SQL ``NULL`` rather than a
        missing row. Use ``fetch_one_or_none`` when a missing row is expected,
        and ``.limit(1)`` to take the first of several rows on purpose.
        """

        async with self._lock:
            connection = self.require_connection()
            plan = self.runtime.query_codec.compile_select_plan(
                cast("_QueryShape[FamilyT, Any, Any, object]", query),
                cardinality="one",
                validate=validate,
            )
            self._validate_plan_backend(plan.backend)
            try:
                cursor = await connection.execute(plan.sql, plan.params)
                try:
                    raw_rows = await cursor.fetchmany(plan.fetch_limit)
                finally:
                    await cursor.close()
            except Exception as error:
                logger.exception(
                    "%s fetch_one query failed: %s params=%r",
                    self.runtime.backend_family,
                    plan.sql,
                    plan.params,
                )
                msg = "select failed"
                raise ExecutionError(
                    msg,
                    sql=plan.sql,
                    params=plan.params,
                ) from error
            rows = [tuple(row) for row in raw_rows]
            logger.debug(
                "%s fetch_one executed: %s params=%r rows=%d",
                self.runtime.backend_family,
                plan.sql,
                plan.params,
                len(rows),
            )
        return plan.materialize(rows)

    @overload
    async def fetch_one_or_none[ScopeT, RowT](
        self,
        query: _OptionalQueryShape[FamilyT, ScopeT, ScopeT, RowT],
        *,
        validate: Literal[True] = True,
    ) -> RowT | None: ...
    @overload
    async def fetch_one_or_none[ScopeT, RowT](
        self,
        query: _OptionalQueryShape[FamilyT, ScopeT, ScopeT, RowT],
        *,
        validate: Literal[False],
    ) -> object: ...
    @overload
    async def fetch_one_or_none[ScopeT, RowT](
        self,
        query: _OptionalQueryShape[FamilyT, ScopeT, ScopeT, RowT],
        *,
        validate: bool,
    ) -> object: ...
    async def fetch_one_or_none(
        self,
        query: object,
        *,
        validate: bool = True,
    ) -> object:
        """Fetch zero or one row, returning ``None`` when none matches.

        Raises ``MultipleResultsError`` when more than one row matches. Only
        model, tuple, and join selects are accepted: for these ``None`` can only
        mean a missing row. Single-value selects are rejected because their
        ``None`` would also mean SQL ``NULL`` -- reach for ``fetch_one``, or for
        the zero-or-one case ``fetch_all`` or a tuple select that includes a
        non-nullable column.
        """

        if isinstance(query, SelectValueQuery):
            msg = (
                "fetch_one_or_none cannot disambiguate a missing row from a SQL "
                "NULL value for a single-value select; use fetch_one, or "
                "fetch_all / a tuple select including a non-nullable column"
            )
            raise QueryConstructionError(msg)
        async with self._lock:
            select_query, rows = await self._fetch_capped_rows(
                query, method="fetch_one_or_none"
            )
        if not rows:
            return None
        if len(rows) > 1:
            msg = "fetch_one_or_none found more than one row"
            raise MultipleResultsError(msg)
        return self.runtime.query_codec.materialize_select_row(
            select_query,
            rows[0],
            validate=validate,
        )

    @overload
    async def execute(
        self,
        query: UpdateQuery[FamilyT, Any, Any] | DeleteQuery[FamilyT, Any, Any],
        *,
        validate: bool = True,
    ) -> int: ...
    @overload
    async def execute(
        self,
        query: InsertQuery[FamilyT, Any, Any] | InsertManyQuery[FamilyT, Any, Any],
        *,
        validate: bool = True,
    ) -> None: ...
    @overload
    async def execute[ResultT](
        self,
        query: _WriteShape[FamilyT, ResultT],
        *,
        validate: Literal[True] = True,
    ) -> ResultT: ...
    @overload
    async def execute[ResultT](
        self,
        query: _WriteShape[FamilyT, ResultT],
        *,
        validate: Literal[False],
    ) -> object: ...
    @overload
    async def execute[ResultT](
        self,
        query: _WriteShape[FamilyT, ResultT],
        *,
        validate: bool,
    ) -> object: ...
    async def execute(
        self,
        query: object,
        *,
        validate: bool = True,
    ) -> object:
        """Execute a write query inside this transaction.

        The result depends on the query shape; see ``insert`` / ``update`` /
        ``delete`` for return-value details.
        """

        async with self._lock:
            connection = self.require_connection()
            plan = self.runtime.query_codec.compile_write_plan(
                cast("_WriteShape[FamilyT, object]", query),
                validate=validate,
            )
            if plan.sql is None:
                return plan.materialize(rowcount=0, rows=())
            self._validate_plan_backend(plan.backend)
            sql = plan.sql
            returned_rows: list[tuple[object, ...]] = []
            affected_rows = 0
            try:
                cursor = await connection.execute(sql, plan.params)
                try:
                    if plan.returns_rows:
                        returned_rows = [tuple(row) for row in await cursor.fetchall()]
                    affected_rows = cursor.rowcount
                finally:
                    await cursor.close()
            except Exception as error:
                logger.exception(
                    "%s write query failed: %s params=%r",
                    self.runtime.backend_family,
                    sql,
                    plan.params,
                )
                msg = "write failed"
                raise ExecutionError(msg, sql=sql, params=plan.params) from error
            logger.debug(
                "%s write executed: %s params=%r",
                self.runtime.backend_family,
                sql,
                plan.params,
            )
            return plan.materialize(
                rowcount=affected_rows,
                rows=returned_rows,
            )

    def require_connection(self) -> RuntimeConnection:
        """Return the active connection or reject use before start / after close.

        A query run after the transaction closed raises ``TransactionClosedError``;
        one run before the transaction was ever entered raises
        ``TransactionNotStartedError``. Both are ``TransactionStateError``
        subclasses, so a caller can catch either uniformly.
        """

        connection = self.connection
        if self.closed:
            msg = "transaction is closed"
            raise TransactionClosedError(msg)
        if connection is None:
            msg = (
                "transaction has not been started; enter it with "
                "'async with db.transaction()'"
            )
            raise TransactionNotStartedError(msg)
        return connection

    def _validate_plan_backend(self, received_backend: BackendFamily) -> None:
        """Reject a compiled plan for a different Backend Runtime Adapter."""

        expected_backend = self.runtime.backend_family
        if received_backend == expected_backend:
            return
        msg = (
            f"backend mismatch: expected {expected_backend} query, "
            f"received {received_backend} query"
        )
        raise DatabaseRuntimeError(msg)

    def _validate_query_backend(self, query: object) -> None:
        query_model = self._query_model(query)
        received_backend = require_model_backend(query_model)
        expected_backend = self.runtime.backend_family
        if received_backend == expected_backend:
            return
        msg = (
            f"backend mismatch: expected {expected_backend} query, "
            f"received {received_backend} query for {query_model.__name__}"
        )
        raise DatabaseRuntimeError(msg)

    @staticmethod
    def _query_model(query: object) -> type[Table[Any]]:
        if isinstance(
            query,
            SelectModelQuery | SelectValueQuery | SelectTupleQuery | JoinModelQuery,
        ):
            return query.state.model
        msg = "query backend validation requires a select query"
        raise QueryCompilationError(msg)

    @staticmethod
    def _require_select_query(query: object) -> AnySelectQuery:
        if isinstance(
            query,
            SelectModelQuery | SelectValueQuery | SelectTupleQuery | JoinModelQuery,
        ):
            return cast("AnySelectQuery", query)
        msg = "fetch requires a select query"
        raise QueryCompilationError(msg)


class Database[FamilyT: BackendFamily]:
    """Connected snekql runtime service for database-backed execution.

    `Database.initialize(...)` is the only public construction path and is
    **connect-only**: it opens connectivity and a connection pool and hands out
    Transactions, and does no schema work at all (see ADR 0007). Schema comes
    into existence only by applying Migrations with `db.migrate(...)`; the
    recorded head is checked with `db.verify_migrations(...)`, and the resulting
    schema is checked against Table Models with `db.verify(...)`.

    It is an async context manager: `async with await Database.initialize(...) as
    db:` closes the runtime on block exit; `close()` can also be called directly.
    """

    def __init__(self, _initialized: Never, /) -> None:
        self.runtime = cast("RuntimeBackend", None)
        msg = "use Database.initialize(...) to create a Database"
        raise DatabaseRuntimeError(msg)

    @overload
    @classmethod
    async def initialize(
        cls,
        backend: RuntimeConfig[FamilyT],
    ) -> Self: ...

    @overload
    @classmethod
    async def initialize(
        cls: type[Database[Literal["sqlite"]]],
        *,
        database: Path | Literal[":memory:"],
        pool_size: PositiveInt = 5,
        acquire_timeout: NonNegativeFloat = 30.0,
    ) -> Database[Literal["sqlite"]]: ...

    @classmethod
    async def initialize(
        cls,
        backend: object | None = None,
        *,
        database: Path | Literal[":memory:"] | None = None,
        pool_size: PositiveInt = 5,
        acquire_timeout: NonNegativeFloat = 30.0,
    ) -> Self:
        """Open connectivity and a connection pool; do no schema work.

        Initialization only proves it can connect and returns a live Database.
        Apply Migrations with `db.migrate(...)`, check their recorded head with
        `db.verify_migrations(...)`, and verify the schema against Table Models
        with `db.verify(...)`; a wrong-backend deploy is caught at the first
        `verify` or query, not here.
        """

        try:
            runtime_config = resolve_runtime_config(
                backend=backend,
                database=database,
                pool_size=pool_size,
                acquire_timeout=acquire_timeout,
            )
            backend_family = runtime_config.backend_family
            logger.info("%s database initialization started", backend_family)
            logger.debug(
                "%s backend selected (pool_size=%s, acquire_timeout=%s)",
                backend_family,
                runtime_config.pool_size,
                runtime_config.acquire_timeout,
            )
            runtime = cast(
                "RuntimeBackend",
                await runtime_config.initialize_runtime(),
            )
            logger.info("%s database initialization completed", backend_family)
        except Exception:
            logger.exception("database initialization failed")
            raise
        database_instance = cls.__new__(cls)
        database_instance.runtime = runtime
        return database_instance

    async def migrate(
        self,
        migrations: dict[str, str],
        *,
        adopt_legacy: bool = False,
    ) -> MigrationResult:
        """Apply pending Migrations imperatively against this live Database.

        Snapshots one complete ordered declaration before I/O, checks that
        ordered checksummed history is its exact prefix, and applies the pending
        suffix one migration at a time. Migrations are the sole schema-creation
        authority. Pair with `verify_migrations(...)` and `verify(...)`.
        """

        migration_plan = prepare_migrations(migrations)
        if type(adopt_legacy) is not bool:
            msg = "adopt_legacy must be an exact bool"
            raise MigrationDeclarationError(msg)
        self.runtime.validate_migrations(migration_plan)
        backend_family = self.runtime.backend_family
        try:
            logger.info(
                "%s database migrate started: %d migration(s)",
                backend_family,
                len(migration_plan),
            )
            result = await self.runtime.apply_migrations(
                migration_plan, adopt_legacy=adopt_legacy
            )
            logger.info(
                "%s database migrate completed: %d migration(s)",
                backend_family,
                len(migration_plan),
            )
        except Exception:
            logger.exception("database migrate failed")
            raise
        return result

    async def verify_migrations(self, migrations: dict[str, str]) -> None:
        """Require read-only Migration History to match a complete declaration."""

        migration_plan = prepare_migrations(migrations)
        self.runtime.validate_migrations(migration_plan)
        backend_family = self.runtime.backend_family
        try:
            logger.info(
                "%s migration verification started: %d migration(s)",
                backend_family,
                len(migration_plan),
            )
            await self.runtime.verify_migrations(migration_plan)
            logger.info(
                "%s migration verification completed: %d migration(s)",
                backend_family,
                len(migration_plan),
            )
        except Exception:
            logger.exception("migration verification failed")
            raise

    async def verify(
        self,
        models: Sequence[_SelectableModelClass[FamilyT, Any, Any]],
        *,
        policy: SchemaPolicy = "strict",
    ) -> None:
        """Verify the live schema against Table Models, a partial structural check.

        Inspects each model's live table and reports Schema Drift under the
        Schema Policy (`strict` raises `SchemaVerificationError`, `warn` logs).
        It ties hand-written Migrations back to current model metadata and never
        creates anything. Verification is deliberately partial and structural --
        see ADR 0008 and `docs/schema-drift.md` for what it cannot see (default
        values, CHECK constraints, triggers, and more).
        """

        backend_family = self.runtime.backend_family
        table_models = cast("Sequence[type[Table[Any]]]", models)
        try:
            validate_model_backends(backend_family, table_models)
            table_names = tuple(
                require_model_table_name(model) for model in table_models
            )
            logger.info(
                "%s database verify started: %d model(s) %r, policy=%s",
                backend_family,
                len(models),
                table_names,
                policy,
            )
            await self.runtime.verify_schema(table_models, policy)
            logger.info(
                "%s database verify completed: %d model(s) %r",
                backend_family,
                len(models),
                table_names,
            )
        except Exception:
            logger.exception("database verify failed")
            raise

    def transaction(
        self,
        *,
        timeout: NonNegativeFloat | None = None,
        mode: TransactionMode = "deferred",
    ) -> Transaction[FamilyT]:
        """Create a transaction context manager using the runtime backend.

        ``mode="immediate"`` declares write intent so the backend acquires the
        writer lock when the transaction opens instead of on its first write.
        On SQLite this issues ``BEGIN IMMEDIATE``, which queues fairly on the
        single writer lock and lets a losing writer be retried at acquisition
        rather than failing mid-transaction; prefer it for write transactions
        under contention. It is a no-op on row-locking backends.
        """

        return cast(
            "Transaction[FamilyT]",
            self._validated_transaction(timeout=timeout, mode=mode),
        )

    @validate_boundary(error_type=DatabaseRuntimeError)
    def _validated_transaction(
        self,
        *,
        timeout: NonNegativeFloat | None = None,
        mode: TransactionMode = "deferred",
    ) -> Transaction[Any]:
        """Validate public transaction arguments outside the generic signature."""

        self.runtime.check_accepting_work()
        acquisition_timeout = (
            self.runtime.acquire_timeout if timeout is None else timeout
        )
        return Transaction[Any](
            runtime=self.runtime,
            timeout=acquisition_timeout,
            mode=mode,
        )

    async def close(self) -> None:
        """Close this database runtime idempotently when shutdown succeeds."""

        with anyio.CancelScope(shield=True):
            await self.runtime.close(self.runtime.acquire_timeout)

    async def __aenter__(self) -> Self:
        """Enter an `async with` block over an already-initialized Database.

        Use as `async with await Database.initialize(...) as db:`; the matching
        `__aexit__` calls `close()`, so the runtime is shut down even when the
        block raises.
        """

        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        _ = exc_type
        _ = exc_value
        _ = traceback
        await self.close()

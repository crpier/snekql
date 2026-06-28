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
from anyio.lowlevel import checkpoint

from snekql._runtime_selection import (
    RuntimeConfig,
    resolve_runtime_config,
    validate_model_backends,
)
from snekql.errors import (
    DatabaseRuntimeError,
    ExecutionError,
    MultipleResultsError,
    NoResultError,
    QueryCompilationError,
    QueryConstructionError,
    TransactionClosedError,
)
from snekql.model import (
    BackendFamily,
    Table,
    require_model_backend,
    require_model_table_name,
)
from snekql.query import (
    AnySelectQuery,
    AnyWriteQuery,
    DeleteQuery,
    DeleteReturningQuery,
    DeleteReturningTupleQuery,
    DeleteReturningValueQuery,
    InsertManyQuery,
    InsertManyReturningQuery,
    InsertManyReturningTupleQuery,
    InsertManyReturningValueQuery,
    InsertQuery,
    InsertReturningQuery,
    InsertReturningTupleQuery,
    InsertReturningValueQuery,
    JoinModelQuery,
    SelectModelQuery,
    SelectTupleQuery,
    SelectValueQuery,
    UpdateQuery,
    UpdateReturningQuery,
    UpdateReturningTupleQuery,
    UpdateReturningValueQuery,
)
from snekql.storage import SchemaPolicy
from snekql.validation import NonNegativeFloat, PositiveInt, validate_boundary

logger = logging.getLogger(__name__)

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

    async def begin(self) -> None: ...

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


class RuntimeBackend(Protocol):
    """Backend adapter seam used by Database and Transaction."""

    acquire_timeout: NonNegativeFloat
    backend_family: BackendFamily

    async def acquire(
        self,
        acquisition_timeout: NonNegativeFloat,
    ) -> RuntimeConnection: ...

    async def release(self, connection: object) -> None: ...

    async def close(self, close_timeout: NonNegativeFloat) -> None: ...

    def check_accepting_work(self) -> None: ...

    async def apply_migrations(self, migrations: dict[str, str]) -> None: ...

    async def verify_schema(
        self,
        models: Sequence[type[Table[Any]]],
        schema_policy: SchemaPolicy,
    ) -> None: ...

    def compile_select_sql(
        self,
        query: AnySelectQuery,
    ) -> tuple[str, tuple[object, ...]]: ...

    def compile_write_sql(self, query: object) -> tuple[str, tuple[object, ...]]: ...

    def materialize_select_row(
        self,
        query: AnySelectQuery,
        row: Sequence[object],
        *,
        validate: bool = True,
    ) -> object: ...

    def materialize_write_rows(
        self,
        query: object,
        rows: Sequence[Sequence[object]],
        *,
        validate: bool = True,
    ) -> list[object]: ...


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
        transaction: Transaction,
        select_query: AnySelectQuery,
        lock: anyio.Lock,
        size: PositiveInt,
        validate: bool,
    ) -> None:
        self._transaction: Transaction = transaction
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
            self._sql, self._params = transaction.runtime.compile_select_sql(
                self._select_query
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
                transaction.runtime.materialize_select_row(
                    self._select_query, tuple(row), validate=self._validate
                ),
            )
            for row in rows
        ]


class Transaction:
    """Async transaction that executes built snekql queries on one connection.

    >>> async def create_user(transaction: Transaction, user: User[Pending]) -> None:
    ...     await transaction.execute(insert(user))
    """

    def __init__(
        self,
        *,
        runtime: RuntimeBackend | None = None,
        timeout: NonNegativeFloat = 0.0,
    ) -> None:
        if runtime is None:
            msg = "use db.transaction(...) to start a transaction"
            raise DatabaseRuntimeError(msg)
        self.closed: bool = False
        self.connection: RuntimeConnection | None = None
        self.runtime: RuntimeBackend = runtime
        self.timeout: NonNegativeFloat = timeout
        self._lock: anyio.Lock = anyio.Lock()

    async def __aenter__(self) -> Self:
        if self.closed or self.connection is not None:
            msg = "transaction is closed"
            raise TransactionClosedError(msg)
        logger.debug(
            "%s transaction acquiring connection (timeout=%s)",
            self.runtime.backend_family,
            self.timeout,
        )
        connection = await self.runtime.acquire(self.timeout)
        try:
            await connection.begin()
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
    async def fetch_all(
        self,
        query: SelectModelQuery[SelectOwnerT, ReadModelT],
        *,
        validate: bool = True,
    ) -> list[ReadModelT]: ...
    @overload
    async def fetch_all(
        self,
        query: SelectValueQuery[ScopeRefT, ScopeRefT, T],
        *,
        validate: bool = True,
    ) -> list[T]: ...
    @overload
    async def fetch_all(
        self,
        query: SelectTupleQuery[ScopeRefT, ScopeRefT, *Ts],
        *,
        validate: bool = True,
    ) -> list[tuple[*Ts]]: ...
    @overload
    async def fetch_all(
        self,
        query: JoinModelQuery[OwnerT, *Ts],
        *,
        validate: bool = True,
    ) -> list[tuple[*Ts]]: ...
    async def fetch_all(self, query: object, *, validate: bool = True) -> object:
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
            sql, params = self.runtime.compile_select_sql(select_query)
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
                    await checkpoint()
                materialized.append(
                    self.runtime.materialize_select_row(
                        select_query, tuple(row), validate=validate
                    )
                )
            return materialized

    @overload
    def fetch_chunks(
        self,
        query: SelectModelQuery[SelectOwnerT, ReadModelT],
        *,
        size: PositiveInt,
        validate: bool = True,
    ) -> ChunkStream[ReadModelT]: ...
    @overload
    def fetch_chunks(
        self,
        query: SelectValueQuery[ScopeRefT, ScopeRefT, T],
        *,
        size: PositiveInt,
        validate: bool = True,
    ) -> ChunkStream[T]: ...
    @overload
    def fetch_chunks(
        self,
        query: SelectTupleQuery[ScopeRefT, ScopeRefT, *Ts],
        *,
        size: PositiveInt,
        validate: bool = True,
    ) -> ChunkStream[tuple[*Ts]]: ...
    @overload
    def fetch_chunks(
        self,
        query: JoinModelQuery[OwnerT, *Ts],
        *,
        size: PositiveInt,
        validate: bool = True,
    ) -> ChunkStream[tuple[*Ts]]: ...
    def fetch_chunks(
        self, query: object, *, size: PositiveInt, validate: bool = True
    ) -> ChunkStream[Any]:
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
        return ChunkStream(
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
        sql, params = self.runtime.compile_select_sql(select_query)
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
    async def fetch_one(
        self,
        query: SelectModelQuery[SelectOwnerT, ReadModelT],
        *,
        validate: bool = True,
    ) -> ReadModelT: ...
    @overload
    async def fetch_one(
        self,
        query: SelectValueQuery[ScopeRefT, ScopeRefT, T],
        *,
        validate: bool = True,
    ) -> T: ...
    @overload
    async def fetch_one(
        self,
        query: SelectTupleQuery[ScopeRefT, ScopeRefT, *Ts],
        *,
        validate: bool = True,
    ) -> tuple[*Ts]: ...
    @overload
    async def fetch_one(
        self,
        query: JoinModelQuery[OwnerT, *Ts],
        *,
        validate: bool = True,
    ) -> tuple[*Ts]: ...
    async def fetch_one(self, query: object, *, validate: bool = True) -> object:
        """Fetch the single row a select must match (exactly-one contract).

        Raises ``NoResultError`` when no row matches and ``MultipleResultsError``
        when more than one does. Because absence raises, a returned ``None`` for
        a single-value select unambiguously means SQL ``NULL`` rather than a
        missing row. Use ``fetch_one_or_none`` when a missing row is expected,
        and ``.limit(1)`` to take the first of several rows on purpose.
        """

        async with self._lock:
            select_query, rows = await self._fetch_capped_rows(
                query, method="fetch_one"
            )
        if not rows:
            msg = "fetch_one found no row"
            raise NoResultError(msg)
        if len(rows) > 1:
            msg = "fetch_one found more than one row"
            raise MultipleResultsError(msg)
        return self.runtime.materialize_select_row(
            select_query, rows[0], validate=validate
        )

    @overload
    async def fetch_one_or_none(
        self,
        query: SelectModelQuery[SelectOwnerT, ReadModelT],
        *,
        validate: bool = True,
    ) -> ReadModelT | None: ...
    @overload
    async def fetch_one_or_none(
        self,
        query: SelectTupleQuery[ScopeRefT, ScopeRefT, *Ts],
        *,
        validate: bool = True,
    ) -> tuple[*Ts] | None: ...
    @overload
    async def fetch_one_or_none(
        self,
        query: JoinModelQuery[OwnerT, *Ts],
        *,
        validate: bool = True,
    ) -> tuple[*Ts] | None: ...
    async def fetch_one_or_none(
        self, query: object, *, validate: bool = True
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
        return self.runtime.materialize_select_row(
            select_query, rows[0], validate=validate
        )

    @overload
    async def execute(
        self,
        query: InsertReturningQuery[OwnerT, ReadModelT],
        *,
        validate: bool = True,
    ) -> ReadModelT: ...
    @overload
    async def execute(
        self,
        query: InsertManyReturningQuery[OwnerT, ReadModelT],
        *,
        validate: bool = True,
    ) -> list[ReadModelT]: ...
    @overload
    async def execute(
        self,
        query: InsertReturningValueQuery[OwnerT, T],
        *,
        validate: bool = True,
    ) -> T: ...
    @overload
    async def execute(
        self,
        query: InsertReturningTupleQuery[OwnerT, *Ts],
        *,
        validate: bool = True,
    ) -> tuple[*Ts]: ...
    @overload
    async def execute(
        self,
        query: InsertManyReturningValueQuery[OwnerT, T],
        *,
        validate: bool = True,
    ) -> list[T]: ...
    @overload
    async def execute(
        self,
        query: InsertManyReturningTupleQuery[OwnerT, *Ts],
        *,
        validate: bool = True,
    ) -> list[tuple[*Ts]]: ...
    @overload
    async def execute(
        self,
        query: UpdateReturningQuery[OwnerT] | DeleteReturningQuery[OwnerT],
        *,
        validate: bool = True,
    ) -> list[OwnerT]: ...
    @overload
    async def execute(
        self,
        query: UpdateReturningValueQuery[OwnerT, T]
        | DeleteReturningValueQuery[OwnerT, T],
        *,
        validate: bool = True,
    ) -> list[T]: ...
    @overload
    async def execute(
        self,
        query: UpdateReturningTupleQuery[OwnerT, *Ts]
        | DeleteReturningTupleQuery[OwnerT, *Ts],
        *,
        validate: bool = True,
    ) -> list[tuple[*Ts]]: ...
    @overload
    async def execute(
        self,
        query: UpdateQuery[Any] | DeleteQuery[Any],
        *,
        validate: bool = True,
    ) -> int: ...
    @overload
    async def execute(
        self,
        query: InsertQuery[Any, Any] | InsertManyQuery[Any, Any],
        *,
        validate: bool = True,
    ) -> None: ...
    async def execute(self, query: object, *, validate: bool = True) -> object:
        """Execute a write query inside this transaction.

        The result depends on the query shape; see ``insert`` / ``update`` /
        ``delete`` for return-value details.
        """

        write_query: AnyWriteQuery = cast("AnyWriteQuery", query)
        returning = isinstance(
            write_query,
            (
                InsertReturningQuery,
                InsertManyReturningQuery,
                InsertReturningValueQuery,
                InsertReturningTupleQuery,
                InsertManyReturningValueQuery,
                InsertManyReturningTupleQuery,
                UpdateReturningQuery,
                UpdateReturningValueQuery,
                UpdateReturningTupleQuery,
                DeleteReturningQuery,
                DeleteReturningValueQuery,
                DeleteReturningTupleQuery,
            ),
        )
        is_many = isinstance(
            write_query,
            (
                InsertManyQuery,
                InsertManyReturningQuery,
                InsertManyReturningValueQuery,
                InsertManyReturningTupleQuery,
            ),
        )
        affects_rows = (
            isinstance(write_query, (UpdateQuery, DeleteQuery)) and not returning
        )
        async with self._lock:
            connection = self.require_connection()
            if is_many and not self._insert_rows(write_query):
                return [] if returning else None
            self._validate_query_backend(cast("object", write_query))
            sql, params = self.runtime.compile_write_sql(cast("object", write_query))
            returned_rows: list[tuple[object, ...]] = []
            affected_rows = 0
            try:
                cursor = await connection.execute(sql, params)
                try:
                    if returning:
                        returned_rows = [tuple(row) for row in await cursor.fetchall()]
                    affected_rows = cursor.rowcount
                finally:
                    await cursor.close()
            except Exception as error:
                logger.exception(
                    "%s write query failed: %s params=%r",
                    self.runtime.backend_family,
                    sql,
                    params,
                )
                msg = "write failed"
                raise ExecutionError(msg, sql=sql, params=params) from error
            logger.debug(
                "%s write executed: %s params=%r",
                self.runtime.backend_family,
                sql,
                params,
            )
            if affects_rows:
                return affected_rows
            if not returning:
                return None
            models = self.runtime.materialize_write_rows(
                cast("object", write_query),
                returned_rows,
                validate=validate,
            )
            if is_many or isinstance(write_query, (UpdateQuery, DeleteQuery)):
                return models
            return models[0]

    @staticmethod
    def _insert_rows(query: object) -> tuple[Table[Any], ...]:
        if isinstance(
            query,
            (
                InsertQuery,
                InsertManyQuery,
                InsertReturningQuery,
                InsertManyReturningQuery,
                InsertReturningValueQuery,
                InsertReturningTupleQuery,
                InsertManyReturningValueQuery,
                InsertManyReturningTupleQuery,
            ),
        ):
            return query.state.rows
        return ()

    def require_connection(self) -> RuntimeConnection:
        """Return the active transaction connection or reject use-after-close."""

        connection = self.connection
        if self.closed or connection is None:
            msg = "transaction is closed"
            raise TransactionClosedError(msg)
        return connection

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
            InsertQuery
            | InsertManyQuery
            | InsertReturningQuery
            | InsertManyReturningQuery
            | InsertReturningValueQuery
            | InsertReturningTupleQuery
            | InsertManyReturningValueQuery
            | InsertManyReturningTupleQuery,
        ):
            model = query.state.model()
            if model is None:
                msg = "an empty bulk insert has no model to validate"
                raise QueryCompilationError(msg)
            return model
        if isinstance(
            query,
            SelectModelQuery | SelectValueQuery | SelectTupleQuery | JoinModelQuery,
        ):
            return query.state.model
        if isinstance(query, UpdateQuery | DeleteQuery):
            return query.state.model
        msg = "query backend validation requires a snekql query"
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


class Database:
    """Connected snekql runtime service for database-backed execution.

    `Database.initialize(...)` is the only public construction path and is
    **connect-only**: it opens connectivity and a connection pool and hands out
    Transactions, and does no schema work at all (see ADR 0007). Schema comes
    into existence only by applying Migrations with `db.migrate(...)`; the
    resulting schema is checked against Table Models with `db.verify(...)`.

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
        backend: RuntimeConfig,
    ) -> Self: ...

    @overload
    @classmethod
    async def initialize(
        cls,
        *,
        database: Path | Literal[":memory:"],
        pool_size: PositiveInt = 5,
        acquire_timeout: NonNegativeFloat = 30.0,
    ) -> Self: ...

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
        Apply Migrations with `db.migrate(...)` and verify the schema against
        Table Models with `db.verify(...)`; a wrong-backend deploy is caught at
        the first `verify` or query, not here.
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

    async def migrate(self, migrations: dict[str, str]) -> None:
        """Apply pending Migrations imperatively against this live Database.

        Runs the backend-neutral apply runner: holds the advisory lock, ensures
        the Migration History, applies each pending body exactly once in declared
        order, and records each success (ADR 0001, ADR 0002). Migrations are the
        sole schema-creation authority; a fresh database is built by replaying
        the whole chain. Pair with `verify(...)`.
        """

        backend_family = self.runtime.backend_family
        try:
            logger.info(
                "%s database migrate started: %d migration(s)",
                backend_family,
                len(migrations),
            )
            await self.runtime.apply_migrations(migrations)
            logger.info(
                "%s database migrate completed: %d migration(s)",
                backend_family,
                len(migrations),
            )
        except Exception:
            logger.exception("database migrate failed")
            raise

    async def verify(
        self,
        models: Sequence[type[Table[Any]]],
        *,
        policy: SchemaPolicy = "strict",
    ) -> None:
        """Verify the live schema against Table Models, a partial structural check.

        Inspects each model's live table and reports Schema Drift under the
        Schema Policy (`strict` raises `SchemaVerificationError`, `warn` logs).
        It is the only feedback loop tying the hand-written Migration chain back
        to the models; it never creates anything. Verification is deliberately
        partial and structural -- see ADR 0008 and `docs/schema-drift.md` for what
        it cannot see (default values, CHECK constraints, triggers, and more).
        """

        backend_family = self.runtime.backend_family
        try:
            validate_model_backends(backend_family, models)
            table_names = tuple(require_model_table_name(model) for model in models)
            logger.info(
                "%s database verify started: %d model(s) %r, policy=%s",
                backend_family,
                len(models),
                table_names,
                policy,
            )
            await self.runtime.verify_schema(models, policy)
            logger.info(
                "%s database verify completed: %d model(s) %r",
                backend_family,
                len(models),
                table_names,
            )
        except Exception:
            logger.exception("database verify failed")
            raise

    @validate_boundary(error_type=DatabaseRuntimeError)
    def transaction(self, *, timeout: NonNegativeFloat | None = None) -> Transaction:
        """Create a transaction context manager using the runtime backend."""

        self.runtime.check_accepting_work()
        acquisition_timeout = (
            self.runtime.acquire_timeout if timeout is None else timeout
        )
        return Transaction(
            runtime=self.runtime,
            timeout=acquisition_timeout,
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

"""Backend-neutral database lifecycle and transaction runtime."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator, Awaitable, Callable, Sequence
from contextlib import AbstractAsyncContextManager
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

from snekql._explain import ExplainResult, compile_explain_plan
from snekql._migrations import (
    MigrationPlan,
    MigrationResult,
    prepare_migrations,
)
from snekql._query_plan import (
    SelectCardinality,
    SelectPlan,
    WritePlan,
    select_query_backend,
    validate_select_consumption,
)
from snekql._raw import NativeParameters, RawPlan, RawStatement, lower_raw
from snekql._runtime_selection import (
    RuntimeConfig,
    resolve_runtime_config,
    validate_model_backends,
)
from snekql._schema_verification import SchemaVerificationResult
from snekql._statement_failure import StatementConstraintError
from snekql._telemetry import ParameterVisibility, QueryDiagnostics, format_bound_params
from snekql.errors import (
    DatabaseOperationTimeoutError,
    DatabaseRuntimeError,
    ExecutionError,
    MigrationDeclarationError,
    QueryConstructionError,
    TransactionClosedError,
    TransactionNotStartedError,
    TransactionReuseError,
    TransactionStateError,
)
from snekql.model import (
    BackendFamily,
    Table,
    require_model_table_name,
)
from snekql.query import (
    AnySelectQuery,
    InsertManyQuery,
    InsertQuery,
    _ExecutableOptionalSelect,
    _ExecutableSelect,
    _ExecutableWrite,
    _SelectableModelClass,
)
from snekql.storage import SchemaPolicy
from snekql.validation import NonNegativeFloat, PositiveInt, validate_boundary

logger = logging.getLogger(__name__)


def _log_query_failure(
    backend_family: BackendFamily,
    operation: str,
    sql: str,
    rendered_params: str,
) -> None:
    """Log safe query context without copying a driver's exception message."""

    logger.error(
        "%s %s query failed: %s params=%s",
        backend_family,
        operation,
        sql,
        rendered_params,
    )


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


class RawRuntimeCursor(RuntimeCursor, Protocol):
    """Raw cursors expose only normalized first-result metadata."""

    @property
    def columns(self) -> tuple[str, ...] | None: ...

    async def complete(self) -> bool:
        """Close the first result, reporting extras without buffering them."""
        ...


class RawRuntimeConnection(Protocol):
    """Adapter-owned native binding path, separate from builder diagnostics."""

    async def execute_raw(
        self,
        sql: str,
        params: NativeParameters,
        *,
        stream: bool = False,
    ) -> RawRuntimeCursor: ...


class QueryCodec(Protocol):
    """Query compile/materialize seam a backend adapter exposes as one object."""

    def compile_select_sql(
        self,
        query: AnySelectQuery,
    ) -> tuple[str, tuple[object, ...]]: ...

    def compile_select_plan[ResultT](
        self,
        query: _ExecutableSelect[Any, Any, Any, ResultT],
        *,
        cardinality: SelectCardinality,
        validate: bool = True,
    ) -> SelectPlan[object]: ...

    def compile_write_plan[ResultT](
        self,
        query: _ExecutableWrite[Any, ResultT],
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
    operation_timeout: NonNegativeFloat
    parameter_visibility: ParameterVisibility
    query_codec: QueryCodec

    async def acquire(
        self,
        acquisition_timeout: NonNegativeFloat,
    ) -> RuntimeConnection: ...

    async def release(self, connection: object) -> None: ...

    async def discard(self, connection: object) -> None: ...

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
    ) -> SchemaVerificationResult: ...


class ChunkStream[RowT]:
    """Incremental batch reader over one result, bound to a transaction.

    Created by ``Transaction.fetch_chunks``. It is both an async context manager
    and an async iterator: entering locks the transaction connection and opens
    a streaming cursor, iterating yields lists of up to ``size`` materialized
    rows, and exiting closes the cursor and releases the transaction lock regardless of
    how iteration ended. Use it inside ``async with`` rather than iterating the
    bare object so cleanup is deterministic.
    """

    def __init__(
        self,
        *,
        transaction: Transaction[Any],
        plan_factory: Callable[[], SelectPlan[object] | RawPlan],
        lock: anyio.Lock,
        size: PositiveInt,
    ) -> None:
        self._transaction: Transaction[Any] = transaction
        self._plan_factory: Callable[[], SelectPlan[object] | RawPlan] = plan_factory
        self._plan: SelectPlan[object] | RawPlan | None = None
        self._lock: anyio.Lock = lock
        self._size: PositiveInt = size
        self._cursor: RuntimeCursor | None = None
        self._entered: bool = False
        self._owner_task: int | None = None

    async def __aenter__(self) -> Self:
        if self._entered:
            msg = "chunk stream is already open"
            raise DatabaseRuntimeError(msg)
        self._entered = True
        transaction = self._transaction
        transaction._check_nested_owner()  # noqa: SLF001
        await self._lock.acquire()
        self._owner_task = anyio.get_current_task().id
        try:
            transaction._check_nested_owner()  # noqa: SLF001
            connection = transaction.require_connection()
            plan = self._plan_factory()
            self._plan = plan
            transaction._validate_plan_backend(plan.backend)  # noqa: SLF001
            self._cursor = await transaction._run_query_operation(  # noqa: SLF001
                "fetch_chunks execution",
                lambda: transaction._open_cursor(connection, plan, stream=True),  # noqa: SLF001
                plan.diagnostics,
            )
            if isinstance(plan, RawPlan):
                plan.check_shape()
            transaction._stream_owner = self._owner_task  # noqa: SLF001
        except BaseException as error:
            try:
                if isinstance(self._plan, RawPlan):
                    await self._finish_raw(error)
            finally:
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
        _ = traceback
        self._check_raw_owner()
        try:
            if isinstance(self._plan, RawPlan):
                await self._finish_raw(exc_value)
            else:
                cursor = self._cursor
                self._cursor = None
                if cursor is not None:
                    await self._transaction._run_driver_operation(  # noqa: SLF001
                        "cursor close",
                        cursor.close,
                    )
        finally:
            self._transaction._stream_owner = None  # noqa: SLF001
            self._lock.release()

    def _check_raw_owner(self) -> None:
        """Reject cursor use outside its savepoint or raw stream's owning task."""

        self._transaction._check_nested_owner()  # noqa: SLF001
        if (
            isinstance(self._plan, RawPlan)
            and self._owner_task != anyio.get_current_task().id
        ):
            msg = "raw stream must be consumed by its owning task"
            raise DatabaseRuntimeError(msg)

    async def _finish_raw(self, pending: BaseException | None = None) -> None:
        """A completed raw stream cannot resume, including after caught failures."""

        cursor = self._cursor
        self._cursor = None
        plan = self._plan
        if cursor is None or not isinstance(plan, RawPlan):
            return
        control_flow = pending is not None and not isinstance(pending, Exception)
        try:
            with anyio.CancelScope(shield=True):
                await self._transaction._complete_raw_cursor(cursor, plan)  # noqa: SLF001
        except BaseException:
            if not control_flow:
                raise
            return
        if not control_flow:
            try:
                plan.check_shape()
            except Exception as error:
                raise error from None

    def __aiter__(self) -> AsyncIterator[list[RowT]]:
        return self

    async def __anext__(self) -> list[RowT]:
        self._check_raw_owner()
        cursor = self._cursor
        plan = self._plan
        if cursor is None and isinstance(plan, RawPlan):
            raise StopAsyncIteration
        if cursor is None or plan is None:
            msg = "chunk stream is not open; use 'async with tx.fetch_chunks(...)'"
            raise DatabaseRuntimeError(msg)
        transaction = self._transaction
        try:
            rows = await transaction._run_query_operation(  # noqa: SLF001
                "fetch_chunks fetch",
                lambda: cursor.fetchmany(self._size),
                plan.diagnostics,
            )
            if not rows:
                if isinstance(plan, RawPlan):
                    await self._finish_raw()
                raise StopAsyncIteration  # noqa: TRY301 - cleanup precedes iteration termination
            logger.debug(
                "%s fetch_chunks batch: %s params=%s rows=%d",
                transaction.runtime.backend_family,
                plan.diagnostics.sql,
                transaction._format_bound_params(plan.diagnostics.params),  # noqa: SLF001
                len(rows),
            )
            # Application decoding stays outside the driver-error boundary, so a
            # validation failure does not become an ExecutionError.
            return [
                cast(
                    "RowT",
                    plan.materialize_row(tuple(row)),
                )
                for row in rows
            ]
        except BaseException as error:
            if isinstance(plan, RawPlan):
                await self._finish_raw(error)
            raise


class _NestedTransaction(AbstractAsyncContextManager[None]):
    """An explicit savepoint on an existing Transaction's connection."""

    def __init__(self, transaction: Transaction[Any]) -> None:
        self._transaction: Transaction[Any] = transaction
        self._name: str = ""
        self._used: bool = False
        self.failed: bool = False

    async def __aenter__(self) -> None:
        if self._used:
            msg = "nested transaction contexts are single-use"
            raise TransactionReuseError(msg)
        self._used = True
        transaction = self._transaction
        self._check_access()
        async with transaction._lock:  # noqa: SLF001
            transaction._check_nested_owner()  # noqa: SLF001
            transaction.require_connection()
            transaction._savepoint_sequence += 1  # noqa: SLF001
            self._name = f"snekql_sp_{transaction._savepoint_sequence}"  # noqa: SLF001
            await self._control("SAVEPOINT")
            transaction._nested_stack.append(self)  # noqa: SLF001
            transaction._nested_owner = anyio.get_current_task().id  # noqa: SLF001

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        del exc_value, traceback
        transaction = self._transaction
        self._check_access()
        if transaction.connection is None or transaction.closed:
            transaction.require_connection()
        if not transaction._nested_stack or transaction._nested_stack[-1] is not self:  # noqa: SLF001
            msg = "nested transaction contexts must exit once in stack order"
            raise TransactionStateError(msg)
        with anyio.CancelScope(shield=True):
            async with transaction._lock:  # noqa: SLF001
                try:
                    if not transaction._connection_reusable:  # noqa: SLF001
                        if exc_type is not None:
                            return
                        msg = "nested transaction cannot release an unsafe connection"
                        raise DatabaseRuntimeError(msg)  # noqa: TRY301 - stack cleanup must run
                    if exc_type is not None or self.failed:
                        await self._control("ROLLBACK TO SAVEPOINT")
                    await self._control("RELEASE SAVEPOINT")
                except Exception:
                    if exc_type is None:
                        raise
                    logger.error(  # noqa: TRY400 - driver text may contain raw SQL values
                        "nested transaction cleanup failed",
                        extra={"backend": transaction.runtime.backend_family},
                    )
                finally:
                    transaction._nested_stack.pop()  # noqa: SLF001
                    if not transaction._nested_stack:  # noqa: SLF001
                        transaction._nested_owner = None  # noqa: SLF001
                if self.failed and exc_type is None:
                    msg = "nested transaction rolled back after a caught constraint failure"
                    raise TransactionStateError(msg)

    def _check_access(self) -> None:
        """Reject foreign tasks and held cursors before waiting on the connection lock."""
        transaction = self._transaction
        transaction._check_nested_owner()  # noqa: SLF001
        if transaction._stream_owner is not None:  # noqa: SLF001
            msg = "close the active stream before crossing a savepoint boundary"
            raise TransactionStateError(msg)

    async def _control(self, command: str) -> None:
        """Run control and cleanup under one deadline, even for a failed savepoint.

        Only control may bypass the rollback-required guard. Physical connection
        safety is still required; no control operation revives an unsafe connection.
        """
        transaction = self._transaction
        connection = transaction.connection
        if (
            connection is None
            or transaction.closed
            or not transaction._connection_reusable  # noqa: SLF001
        ):
            connection = transaction.require_connection()

        async def execute() -> None:
            cursor = await connection.execute(f"{command} {self._name}", ())
            await cursor.close()

        try:
            await transaction._run_driver_operation(command.lower(), execute)  # noqa: SLF001
        except DatabaseOperationTimeoutError:
            raise
        except Exception as e:
            msg = f"could not execute {command.lower()}"
            if transaction._raw_diagnostics:  # noqa: SLF001
                raise DatabaseRuntimeError(msg) from None
            raise DatabaseRuntimeError(msg) from e


class Transaction[FamilyT: BackendFamily]:
    """Async transaction that executes built snekql queries on one connection.

    Single-use and not re-entrant: enter it exactly once with ``async with
    db.transaction()``, run queries while it is open, and let the block exit
    commit (clean exit) or roll back (the block raised). Using it off that path
    raises a ``TransactionStateError`` subclass -- ``TransactionNotStartedError``
    before entry, ``TransactionClosedError`` after close, ``TransactionReuseError``
    on a second entry. Queries on one transaction are serialized on its single
    connection, so sharing it across tasks is safe but offers no parallelism; open
    separate transactions for concurrent work. Active nested contexts reserve
    transaction use for their entering task. See ``docs/error-handling.md``.

    >>> async def create_user(transaction: Transaction[Any], user: User[Pending]) -> None:
    ...     await transaction.execute(insert(user))
    """

    def __init__(
        self,
        *,
        runtime: RuntimeBackend | None = None,
        timeout: NonNegativeFloat = 0.0,
        acquisition_timeout: NonNegativeFloat | None = None,
        mode: TransactionMode = "deferred",
    ) -> None:
        if runtime is None:
            msg = "use db.transaction(...) to start a transaction"
            raise DatabaseRuntimeError(msg)
        self.closed: bool = False
        self.connection: RuntimeConnection | None = None
        self.runtime: RuntimeBackend = runtime
        self.timeout: NonNegativeFloat = timeout
        self.acquisition_timeout: NonNegativeFloat = (
            timeout if acquisition_timeout is None else acquisition_timeout
        )
        self.mode: TransactionMode = mode
        self._connection_reusable: bool = True
        self._raw_diagnostics: bool = False
        self._entering: bool = False
        self._savepoint_sequence: int = 0
        self._nested_stack: list[_NestedTransaction] = []
        self._nested_owner: int | None = None
        self._stream_owner: int | None = None
        self._lock: anyio.Lock = anyio.Lock()

    async def __aenter__(self) -> Self:
        # A Transaction is single-use and not re-entrant: it is entered exactly
        # once and cannot be restarted. Re-entering one that is still open, or
        # one already used and closed, is reuse rather than a closed-use error.
        if self._entering or self.connection is not None:
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
            self.acquisition_timeout,
            self.mode,
        )
        # Reserve entry before the first await. A rejected competing caller
        # must not acquire a connection or reset the owner's reservation.
        self._entering = True
        try:
            connection = await self.runtime.acquire(self.acquisition_timeout)
            try:
                await self._run_driver_operation(
                    "transaction begin",
                    lambda: connection.begin(self.mode),
                )
            except BaseException as error:
                logger.exception(
                    "%s transaction begin failed", self.runtime.backend_family
                )
                with anyio.CancelScope(shield=True):
                    await self.runtime.discard(connection)
                self._connection_reusable = False
                self.closed = True
                if isinstance(error, DatabaseOperationTimeoutError):
                    raise
                if isinstance(error, Exception):
                    msg = "could not begin transaction"
                    raise DatabaseRuntimeError(msg) from error
                raise
            self.connection = connection
            logger.debug("%s transaction begin", self.runtime.backend_family)
            return self
        finally:
            self._entering = False

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        _ = exc_value
        _ = traceback
        self._check_nested_owner()
        with anyio.CancelScope(shield=True):
            async with self._lock:
                self._check_nested_owner()
                connection = self.connection
                if connection is None:
                    msg = "transaction is closed"
                    raise TransactionClosedError(msg)
                self.connection = None
                self.closed = True
                if self._nested_stack:
                    self._connection_reusable = False
                    self._nested_stack.clear()
                    self._nested_owner = None
                    await self.runtime.discard(connection)
                    if exc_type is None:
                        msg = "transaction closed with unfinished nested contexts"
                        raise TransactionStateError(msg)
                    return
                if not self._connection_reusable:
                    await self.runtime.discard(connection)
                    logger.warning(
                        "%s transaction discarded after unsafe operation",
                        self.runtime.backend_family,
                    )
                    return
                try:
                    if exc_type is None:
                        await self._run_driver_operation(
                            "transaction commit",
                            connection.commit,
                        )
                        logger.debug(
                            "%s transaction commit", self.runtime.backend_family
                        )
                    else:
                        await self._run_driver_operation(
                            "transaction rollback",
                            connection.rollback,
                        )
                        logger.debug(
                            "%s transaction rollback (%s)",
                            self.runtime.backend_family,
                            exc_type.__name__,
                        )
                except Exception as error:
                    self._connection_reusable = False
                    self._report_close_failure(error, during_error=exc_type is not None)
                finally:
                    if self._connection_reusable:
                        await self.runtime.release(connection)
                        logger.debug(
                            "%s transaction released", self.runtime.backend_family
                        )
                    else:
                        await self.runtime.discard(connection)
                        logger.warning(
                            "%s transaction discarded", self.runtime.backend_family
                        )

    def begin_nested(self) -> AbstractAsyncContextManager[None]:
        """Create a savepoint context without acquiring another connection.

        >>> async def optional_write(transaction, statement):
        ...     async with transaction.begin_nested():
        ...         await transaction.execute(statement)

        Queries still run through this Transaction. Success releases the savepoint;
        only the outer transaction commits. An exception rolls back the nested work
        and propagates to the caller. Recognized constraint failures require
        rollback before further work; other driver failures remain terminal.
        Savepoints never make an unsafe connection reusable. Contexts are
        single-use and reserve Transaction use for their entering task until exit.
        """
        return _NestedTransaction(self)

    @overload
    async def fetch_all[ScopeT, RowT](
        self,
        query: _ExecutableSelect[FamilyT, ScopeT, ScopeT, RowT],
        *,
        validate: Literal[True] = True,
    ) -> list[RowT]: ...
    @overload
    async def fetch_all[ScopeT, RowT](
        self,
        query: _ExecutableSelect[FamilyT, ScopeT, ScopeT, RowT],
        *,
        validate: Literal[False],
    ) -> list[object]: ...
    @overload
    async def fetch_all[ScopeT, RowT](
        self,
        query: _ExecutableSelect[FamilyT, ScopeT, ScopeT, RowT],
        *,
        validate: bool,
    ) -> list[object]: ...
    @overload
    async def fetch_all[RowT](
        self,
        query: RawStatement[FamilyT, RowT],
        *,
        validate: Literal[True] = True,
    ) -> list[RowT]: ...

    async def fetch_all(
        self,
        query: object,
        *,
        validate: bool = True,
    ) -> list[object]:
        """Fetch all rows from a builder select or raw statement into a list.

        Intended for bounded result sets. The whole result is loaded into memory
        and each row is validated synchronously on the event loop; the loop
        yields a cooperative checkpoint periodically so a large materialization
        does not monopolize it, but the read still holds the connection for its
        full duration. For large or unbounded results stream with ``fetch_chunks``
        instead, which fetches incrementally from a server-side cursor and keeps
        per-batch materialization small.
        """

        self._check_nested_owner()
        async with self._lock:
            self._check_nested_owner()
            connection = self.require_connection()
            if isinstance(query, RawStatement):
                plan = lower_raw(
                    query,
                    backend=self.runtime.backend_family,
                    operation="fetch_all",
                    validate=validate,
                )
            else:
                self._validate_plan_backend(select_query_backend(query))
                plan = self.runtime.query_codec.compile_select_plan(
                    cast("_ExecutableSelect[FamilyT, Any, Any, object]", query),
                    cardinality="many",
                    validate=validate,
                )
                self._validate_plan_backend(plan.backend)
            _, rows = await self._execute_buffered(
                connection,
                plan=plan,
                operation="fetch_all",
            )
            materialized: list[object] = []
            for index, row in enumerate(rows):
                if index and index % FETCH_ALL_YIELD_INTERVAL == 0:
                    await anyio.lowlevel.checkpoint()
                materialized.append(plan.materialize_row(tuple(row)))
            return materialized

    @overload
    def fetch_chunks[ScopeT, RowT](
        self,
        query: _ExecutableSelect[FamilyT, ScopeT, ScopeT, RowT],
        *,
        size: PositiveInt,
        validate: Literal[True] = True,
    ) -> ChunkStream[RowT]: ...
    @overload
    def fetch_chunks[ScopeT, RowT](
        self,
        query: _ExecutableSelect[FamilyT, ScopeT, ScopeT, RowT],
        *,
        size: PositiveInt,
        validate: Literal[False],
    ) -> ChunkStream[object]: ...
    @overload
    def fetch_chunks[ScopeT, RowT](
        self,
        query: _ExecutableSelect[FamilyT, ScopeT, ScopeT, RowT],
        *,
        size: PositiveInt,
        validate: bool,
    ) -> ChunkStream[object]: ...
    @overload
    def fetch_chunks[RowT](
        self,
        query: RawStatement[FamilyT, RowT],
        *,
        size: PositiveInt,
        validate: Literal[True] = True,
    ) -> ChunkStream[RowT]: ...

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

        if isinstance(query, RawStatement):
            try:
                _validate_chunk_size(size=size)
            except Exception:
                msg = "raw stream size must be a positive integer"
                raise QueryConstructionError(msg) from None
            lower_raw(
                query,
                backend=self.runtime.backend_family,
                operation="fetch_chunks",
                validate=validate,
            )
        else:
            _validate_chunk_size(size=size)
            self._validate_plan_backend(select_query_backend(query))

        def plan_factory() -> SelectPlan[object] | RawPlan:
            if isinstance(query, RawStatement):
                return lower_raw(
                    query,
                    backend=self.runtime.backend_family,
                    operation="fetch_chunks",
                    validate=validate,
                )
            return self.runtime.query_codec.compile_select_plan(
                cast("_ExecutableSelect[FamilyT, Any, Any, object]", query),
                cardinality="many",
                validate=validate,
            )

        return ChunkStream[object](
            transaction=self,
            plan_factory=plan_factory,
            lock=self._lock,
            size=size,
        )

    @overload
    async def fetch_one[ScopeT, RowT](
        self,
        query: _ExecutableSelect[FamilyT, ScopeT, ScopeT, RowT],
        *,
        validate: Literal[True] = True,
    ) -> RowT: ...
    @overload
    async def fetch_one[ScopeT, RowT](
        self,
        query: _ExecutableSelect[FamilyT, ScopeT, ScopeT, RowT],
        *,
        validate: Literal[False],
    ) -> object: ...
    @overload
    async def fetch_one[ScopeT, RowT](
        self,
        query: _ExecutableSelect[FamilyT, ScopeT, ScopeT, RowT],
        *,
        validate: bool,
    ) -> object: ...
    @overload
    async def fetch_one[RowT](
        self,
        query: RawStatement[FamilyT, RowT],
        *,
        validate: Literal[True] = True,
    ) -> RowT: ...

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

        self._check_nested_owner()
        async with self._lock:
            self._check_nested_owner()
            connection = self.require_connection()
            if isinstance(query, RawStatement):
                plan = lower_raw(
                    query,
                    backend=self.runtime.backend_family,
                    operation="fetch_one",
                    validate=validate,
                )
            else:
                plan = self.runtime.query_codec.compile_select_plan(
                    cast("_ExecutableSelect[FamilyT, Any, Any, object]", query),
                    cardinality="one",
                    validate=validate,
                )
                self._validate_plan_backend(plan.backend)
            _, raw_rows = await self._execute_buffered(
                connection,
                plan=plan,
                operation="fetch_one",
            )
            rows = [tuple(row) for row in raw_rows]
        return plan.materialize(rows)

    @overload
    async def fetch_one_or_none[ScopeT, RowT](
        self,
        query: _ExecutableOptionalSelect[FamilyT, ScopeT, ScopeT, RowT],
        *,
        validate: Literal[True] = True,
    ) -> RowT | None: ...
    @overload
    async def fetch_one_or_none[ScopeT, RowT](
        self,
        query: _ExecutableOptionalSelect[FamilyT, ScopeT, ScopeT, RowT],
        *,
        validate: Literal[False],
    ) -> object: ...
    @overload
    async def fetch_one_or_none[ScopeT, RowT](
        self,
        query: _ExecutableOptionalSelect[FamilyT, ScopeT, ScopeT, RowT],
        *,
        validate: bool,
    ) -> object: ...
    @overload
    async def fetch_one_or_none[RowT](
        self,
        query: RawStatement[FamilyT, RowT],
        *,
        validate: Literal[True] = True,
    ) -> RowT | None: ...

    async def fetch_one_or_none(
        self,
        query: object,
        *,
        validate: bool = True,
    ) -> object:
        """Fetch zero or one row, returning ``None`` when none matches.

        Raises ``MultipleResultsError`` when more than one row matches. Builder
        selects accept model, tuple, and join rows: for these ``None`` can only
        mean a missing row. Single-value selects are rejected because their
        ``None`` would also mean SQL ``NULL`` -- reach for ``fetch_one``, or for
        the zero-or-one case ``fetch_all`` or a tuple select that includes a
        non-nullable column. Raw statements use their declared row mode and
        require result columns, without the builder's scalar restriction.
        """

        validate_select_consumption(query, cardinality="one_or_none")
        self._check_nested_owner()
        async with self._lock:
            self._check_nested_owner()
            connection = self.require_connection()
            if isinstance(query, RawStatement):
                plan = lower_raw(
                    query,
                    backend=self.runtime.backend_family,
                    operation="fetch_one_or_none",
                    validate=validate,
                )
            else:
                self._validate_plan_backend(select_query_backend(query))
                plan = self.runtime.query_codec.compile_select_plan(
                    cast("_ExecutableSelect[FamilyT, Any, Any, object]", query),
                    cardinality="one_or_none",
                    validate=validate,
                )
                self._validate_plan_backend(plan.backend)
            _, rows = await self._execute_buffered(
                connection,
                plan=plan,
                operation="fetch_one_or_none",
            )
        return plan.materialize(rows)

    @overload
    async def execute(
        self,
        query: _ExecutableWrite[FamilyT, int],
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
        query: _ExecutableWrite[FamilyT, ResultT],
        *,
        validate: Literal[True] = True,
    ) -> ResultT: ...
    @overload
    async def execute[ResultT](
        self,
        query: _ExecutableWrite[FamilyT, ResultT],
        *,
        validate: Literal[False],
    ) -> object: ...
    @overload
    async def execute[ResultT](
        self,
        query: _ExecutableWrite[FamilyT, ResultT],
        *,
        validate: bool,
    ) -> object: ...
    @overload
    async def execute[RowT](
        self,
        query: RawStatement[FamilyT, RowT],
        *,
        validate: Literal[True] = True,
    ) -> int: ...

    async def execute(
        self,
        query: object,
        *,
        validate: bool = True,
    ) -> object:
        """Execute a builder write or raw no-column command in this transaction.

        Raw statements return the connector's rowcount. Builder results depend
        on query shape; see ``insert`` / ``update`` /
        ``delete`` for return-value details.
        """

        self._check_nested_owner()
        async with self._lock:
            self._check_nested_owner()
            connection = self.require_connection()
            if isinstance(query, RawStatement):
                plan = lower_raw(
                    query,
                    backend=self.runtime.backend_family,
                    operation="execute",
                    validate=validate,
                )
            else:
                plan = self.runtime.query_codec.compile_write_plan(
                    cast("_ExecutableWrite[FamilyT, object]", query),
                    validate=validate,
                )
                self._validate_plan_backend(plan.backend)
            affected_rows, returned_rows = await self._execute_buffered(
                connection,
                plan=plan,
                operation="write",
            )
            if isinstance(plan, RawPlan):
                return affected_rows
            return plan.materialize(
                rowcount=affected_rows,
                rows=returned_rows,
            )

    async def explain[ScopeT, RowT, ResultT](
        self,
        query: _ExecutableSelect[FamilyT, ScopeT, ScopeT, RowT]
        | _ExecutableWrite[FamilyT, ResultT],
    ) -> ExplainResult:
        """Inspect a built query's backend-native plan without executing its writes.

        SQLite uses `EXPLAIN QUERY PLAN`; MariaDB uses `EXPLAIN`.
        Results contain native columns and rows, not the query's result type.
        """

        return await self._explain(query, analyze=False)

    async def explain_analyze[ScopeT, RowT, ResultT](
        self,
        query: _ExecutableSelect[FamilyT, ScopeT, ScopeT, RowT]
        | _ExecutableWrite[FamilyT, ResultT],
    ) -> ExplainResult:
        """Execute a query to collect MariaDB's actual optimizer statistics.

        Writes really run in this Transaction and commit on its normal exit.
        This method does not create a savepoint or automatically roll back.
        SQLite and unsupported statement shapes raise `QueryCompilationError`.
        """

        return await self._explain(query, analyze=True)

    async def _explain(self, query: object, *, analyze: bool) -> ExplainResult:
        """Share transaction locking, deadlines, cleanup, and safe raw diagnostics."""

        self._check_nested_owner()
        async with self._lock:
            self._check_nested_owner()
            connection = self.require_connection()
            plan = compile_explain_plan(
                query, backend=self.runtime.backend_family, analyze=analyze
            )
            _, rows = await self._execute_buffered(
                connection,
                plan=plan,
                operation="explain_analyze" if analyze else "explain",
            )
            return ExplainResult(
                backend=plan.backend,
                columns=plan.columns or (),
                rows=tuple(tuple(row) for row in rows),
            )

    def _check_nested_owner(self) -> None:
        """Savepoints reserve the connection's logical work for one task."""
        if (
            self._nested_owner is not None
            and self._nested_owner != anyio.get_current_task().id
        ):
            msg = "nested transaction must be used by its owning task"
            raise TransactionStateError(msg)

    def _report_close_failure(self, error: Exception, *, during_error: bool) -> None:
        """Rollback preserves pending errors; raw lifecycle diagnostics stay safe."""

        if self._raw_diagnostics:
            logger.error(
                "raw transaction close failed",
                extra={"backend": self.runtime.backend_family},
            )
        else:
            logger.error(
                "%s transaction close failed",
                self.runtime.backend_family,
                exc_info=error,
            )
        if during_error:
            return
        if isinstance(error, DatabaseOperationTimeoutError):
            if self._raw_diagnostics:
                raise error from None
            raise error
        msg = "could not close transaction"
        if self._raw_diagnostics:
            raise DatabaseRuntimeError(msg) from None
        raise DatabaseRuntimeError(msg) from error

    async def _open_cursor(
        self,
        connection: RuntimeConnection,
        plan: SelectPlan[object] | WritePlan[object] | RawPlan,
        *,
        stream: bool = False,
    ) -> RuntimeCursor:
        """Choose the adapter's native raw path without another connection."""

        if isinstance(plan, RawPlan):
            self._raw_diagnostics = True
            # Both supported adapters implement this additional native boundary.
            cursor = await cast("RawRuntimeConnection", connection).execute_raw(
                plan.sql,
                plan.params,
                stream=stream,
            )
            try:
                plan.columns = cursor.columns
            except BaseException as error:
                await self._complete_raw_cursor(cursor, plan, pending=error)
                raise
            return cursor
        if plan.sql is None:
            msg = "cannot open a cursor for an empty execution plan"
            raise DatabaseRuntimeError(msg)
        if stream:
            return await connection.execute_stream(plan.sql, plan.params)
        return await connection.execute(plan.sql, plan.params)

    async def _complete_raw_cursor(
        self,
        cursor: RuntimeCursor,
        plan: RawPlan,
        *,
        pending: BaseException | None = None,
    ) -> None:
        """Cleanup errors supersede result errors, but never cancellation."""

        try:
            plan.additional_results = await self._run_query_operation(
                "raw cursor completion",
                cast("RawRuntimeCursor", cursor).complete,
                plan.diagnostics,
            )
        except BaseException:
            if pending is not None and not isinstance(pending, Exception):
                raise pending from None
            raise
        if plan.additional_results:
            self._connection_reusable = False

    async def _execute_buffered(
        self,
        connection: RuntimeConnection,
        *,
        plan: SelectPlan[object] | WritePlan[object] | RawPlan,
        operation: str,
    ) -> tuple[int, Sequence[Sequence[object]]]:
        """Collect driver output and close before application materialization.

        A zero limit skips fetching for a command; None collects every row.
        Execution, fetch, and close share the buffered operation's deadline.
        Cardinality and decoding run outside the driver-error boundary.
        """

        sql = plan.sql
        if sql is None:
            return 0, ()
        diagnostics = plan.diagnostics
        fetch_limit = plan.fetch_limit

        async def collect() -> tuple[int, Sequence[Sequence[object]]]:
            cursor = await self._open_cursor(connection, plan)
            pending: BaseException | None = None
            try:
                if fetch_limit is None:
                    rows = await cursor.fetchall()
                elif fetch_limit:
                    rows = await cursor.fetchmany(fetch_limit)
                else:
                    rows = ()
                rowcount = cursor.rowcount
            except BaseException as error:
                pending = error
                raise
            else:
                return rowcount, rows
            finally:
                if isinstance(plan, RawPlan):
                    await self._complete_raw_cursor(cursor, plan, pending=pending)
                else:
                    await cursor.close()

        output = await self._run_query_operation(operation, collect, diagnostics)
        if isinstance(plan, RawPlan):
            plan.check_shape()
        logger.debug(
            "%s %s executed: %s params=%s rows=%d",
            self.runtime.backend_family,
            operation,
            diagnostics.sql,
            self._format_bound_params(diagnostics.params),
            len(output[1]),
        )
        return output

    async def _run_query_operation[ResultT](
        self,
        operation: str,
        operation_call: Callable[[], Awaitable[ResultT]],
        diagnostics: QueryDiagnostics,
    ) -> ResultT:
        """Translate query driver failures without catching row materialization.

        Buffered execution and stream interactions share classification and
        logging. Transaction control retains its separate lifecycle handling.
        """

        try:
            return await self._run_driver_operation(
                operation, operation_call, recover_constraints=True
            )
        except DatabaseOperationTimeoutError as error:
            if diagnostics.raw:
                raise error from None
            raise
        except Exception as error:
            if diagnostics.raw:
                logger.error(  # noqa: TRY400 - exception text may contain raw SQL
                    "raw driver operation failed",
                    extra={
                        "operation": operation,
                        "backend": self.runtime.backend_family,
                    },
                )
                raise self._execution_error(
                    diagnostics.failure_message, sql="", params=()
                ) from None
            _log_query_failure(
                self.runtime.backend_family,
                operation,
                diagnostics.sql,
                self._format_bound_params(diagnostics.params),
            )
            raise self._execution_error(
                diagnostics.failure_message,
                sql=diagnostics.sql,
                params=diagnostics.params,
            ) from error

    async def _run_driver_operation[ResultT](
        self,
        operation: str,
        operation_call: Callable[[], Awaitable[ResultT]],
        *,
        recover_constraints: bool = False,
    ) -> ResultT:
        """Run one driver operation within the transaction's timeout."""

        try:
            with anyio.fail_after(self.timeout):
                return await operation_call()
        except TimeoutError as error:
            self._connection_reusable = False
            logger.warning(
                "%s %s timed out (timeout=%s)",
                self.runtime.backend_family,
                operation,
                self.timeout,
            )
            raise DatabaseOperationTimeoutError(operation, self.timeout) from error
        except StatementConstraintError as e:
            if recover_constraints and self._nested_stack and self._connection_reusable:
                self._nested_stack[-1].failed = True
            else:
                self._connection_reusable = False
            raise e.original from None
        except BaseException:
            self._connection_reusable = False
            raise

    def _format_bound_params(self, params: tuple[object, ...]) -> str:
        """Apply this runtime's parameter visibility policy to telemetry."""

        return format_bound_params(params, self.runtime.parameter_visibility)

    def _execution_error(
        self,
        message: str,
        *,
        sql: str,
        params: tuple[object, ...],
    ) -> ExecutionError:
        """Build an execution failure carrying the runtime telemetry policy."""

        return ExecutionError(
            message,
            sql=sql,
            params=params,
            parameter_visibility=self.runtime.parameter_visibility,
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
        if not self._connection_reusable:
            msg = "transaction connection is unsafe after a timed-out operation"
            raise DatabaseRuntimeError(msg)
        if self._nested_stack and self._nested_stack[-1].failed:
            msg = "nested transaction requires rollback before further work"
            raise TransactionStateError(msg)
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
        operation_timeout: NonNegativeFloat = 30.0,
    ) -> Database[Literal["sqlite"]]: ...

    @classmethod
    async def initialize(
        cls,
        backend: object | None = None,
        *,
        database: Path | Literal[":memory:"] | None = None,
        pool_size: PositiveInt = 5,
        acquire_timeout: NonNegativeFloat = 30.0,
        operation_timeout: NonNegativeFloat = 30.0,
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
                operation_timeout=operation_timeout,
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
    ) -> SchemaVerificationResult:
        """Verify the live schema against Table Models, a partial structural check.

        Inspects every model before applying the Schema Policy. `strict` raises
        `SchemaVerificationError` with the result attached; `warn` logs drift and
        returns it. Verification ties hand-written Migrations back to current
        model metadata and never creates anything. It remains deliberately
        partial and structural; see `docs/schema-drift.md` for the exact scope.
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
            verification_result = await self.runtime.verify_schema(table_models, policy)
            logger.info(
                "%s database verify completed: %d model(s) %r",
                backend_family,
                len(models),
                table_names,
            )
        except Exception:
            logger.exception("database verify failed")
            raise
        return verification_result

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
        operation_timeout = (
            self.runtime.operation_timeout if timeout is None else timeout
        )
        return Transaction[Any](
            runtime=self.runtime,
            timeout=operation_timeout,
            acquisition_timeout=acquisition_timeout,
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

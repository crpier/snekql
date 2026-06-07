"""Backend-neutral database lifecycle and transaction runtime."""

from __future__ import annotations

from collections.abc import Sequence
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

from snekql._runtime_selection import resolve_runtime_selection
from snekql.errors import (
    DatabaseRuntimeError,
    ExecutionError,
    QueryCompilationError,
    TransactionClosedError,
)
from snekql.mariadb.config import Config as MariaDBConfig
from snekql.model import (
    BackendFamily,
    Table,
    require_model_backend,
    require_model_table_name,
)
from snekql.query import (
    AnySelectQuery,
    DeleteQuery,
    InsertQuery,
    SelectModelQuery,
    SelectTupleQuery,
    SelectValueQuery,
    UpdateQuery,
)
from snekql.sqlite.config import Config as SQLiteConfig
from snekql.storage import SchemaPolicy
from snekql.structured_logging import (
    ResolvedStructuredLogger,
    StructuredLogger,
    resolve_structured_logger,
)
from snekql.validation import NonNegativeFloat, PositiveInt, validate_boundary

SelectOwnerT = TypeVar("SelectOwnerT", bound=Table[Any])
OwnerT = TypeVar("OwnerT", bound=Table[Any])
ReadModelT = TypeVar("ReadModelT", bound=Table[Any])
T = TypeVar("T")
Ts = TypeVarTuple("Ts")


class RuntimeCursor(Protocol):
    """Cursor behavior required by backend-neutral transaction execution."""

    async def fetchone(self) -> Sequence[object] | None: ...

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


class RuntimeBackend(Protocol):
    """Backend adapter seam used by Database and Transaction."""

    acquire_timeout: NonNegativeFloat
    backend_family: BackendFamily
    logger: ResolvedStructuredLogger

    async def acquire(
        self,
        acquisition_timeout: NonNegativeFloat,
    ) -> RuntimeConnection: ...

    async def release(self, connection: object) -> None: ...

    async def close(self, close_timeout: NonNegativeFloat) -> None: ...

    def check_accepting_work(self) -> None: ...

    def compile_select_sql(
        self,
        query: AnySelectQuery,
    ) -> tuple[str, tuple[object, ...]]: ...

    def compile_write_sql(self, query: object) -> tuple[str, tuple[object, ...]]: ...

    def materialize_select_row(
        self,
        query: AnySelectQuery,
        row: Sequence[object],
    ) -> object: ...


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

    async def __aenter__(self) -> Self:
        if self.closed or self.connection is not None:
            msg = "transaction is closed"
            raise TransactionClosedError(msg)
        self.runtime.logger.debug(
            "transaction acquiring connection",
            backend=self.runtime.backend_family,
            timeout=self.timeout,
        )
        connection = await self.runtime.acquire(self.timeout)
        try:
            await connection.begin()
        except Exception as error:
            self.runtime.logger.error(  # noqa: TRY400
                "transaction begin failed",
                backend=self.runtime.backend_family,
                error_type=type(error).__name__,
            )
            await self.runtime.release(connection)
            msg = "could not begin transaction"
            raise DatabaseRuntimeError(msg) from error
        self.connection = connection
        self.runtime.logger.debug(
            "transaction begin",
            backend=self.runtime.backend_family,
        )
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        _ = exc_value
        _ = traceback
        connection = self.connection
        if connection is None:
            msg = "transaction is closed"
            raise TransactionClosedError(msg)
        self.connection = None
        self.closed = True
        try:
            if exc_type is None:
                await connection.commit()
                self.runtime.logger.debug(
                    "transaction commit",
                    backend=self.runtime.backend_family,
                )
            else:
                await connection.rollback()
                self.runtime.logger.debug(
                    "transaction rollback",
                    backend=self.runtime.backend_family,
                    exception_type=exc_type.__name__,
                )
        except Exception as error:
            self.runtime.logger.error(  # noqa: TRY400
                "transaction close failed",
                backend=self.runtime.backend_family,
                error_type=type(error).__name__,
            )
            if exc_type is None:
                msg = "could not close transaction"
                raise DatabaseRuntimeError(msg) from error
        finally:
            await self.runtime.release(connection)
            self.runtime.logger.debug(
                "transaction released",
                backend=self.runtime.backend_family,
            )

    @overload
    async def fetch_all(
        self, query: SelectModelQuery[SelectOwnerT, ReadModelT]
    ) -> list[ReadModelT]: ...
    @overload
    async def fetch_all(self, query: SelectValueQuery[OwnerT, T]) -> list[T]: ...
    @overload
    async def fetch_all(
        self, query: SelectTupleQuery[OwnerT, *Ts]
    ) -> list[tuple[*Ts]]: ...
    async def fetch_all(self, query: object) -> object:
        """Fetch all rows for a select query."""

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
            self.runtime.logger.error(  # noqa: TRY400
                "query failed",
                backend=self.runtime.backend_family,
                error_type=type(error).__name__,
                operation="fetch_all",
                params=params,
                sql=sql,
            )
            msg = "select failed"
            raise ExecutionError(msg, sql=sql, params=params) from error
        self.runtime.logger.debug(
            "query executed",
            backend=self.runtime.backend_family,
            operation="fetch_all",
            params=params,
            row_count=len(rows),
            sql=sql,
        )
        return [
            self.runtime.materialize_select_row(select_query, tuple(row))
            for row in rows
        ]

    @overload
    async def fetch_one(
        self, query: SelectModelQuery[SelectOwnerT, ReadModelT]
    ) -> ReadModelT | None: ...
    @overload
    async def fetch_one(self, query: SelectValueQuery[OwnerT, T]) -> T | None: ...
    @overload
    async def fetch_one(
        self, query: SelectTupleQuery[OwnerT, *Ts]
    ) -> tuple[*Ts] | None: ...
    async def fetch_one(self, query: object) -> object:
        """Fetch one row for a select query."""

        connection = self.require_connection()
        select_query = self._require_select_query(query)
        self._validate_query_backend(select_query)
        sql, params = self.runtime.compile_select_sql(select_query)
        try:
            cursor = await connection.execute(sql, params)
            try:
                row = await cursor.fetchone()
            finally:
                await cursor.close()
        except Exception as error:
            self.runtime.logger.error(  # noqa: TRY400
                "query failed",
                backend=self.runtime.backend_family,
                error_type=type(error).__name__,
                operation="fetch_one",
                params=params,
                sql=sql,
            )
            msg = "select failed"
            raise ExecutionError(msg, sql=sql, params=params) from error
        self.runtime.logger.debug(
            "query executed",
            backend=self.runtime.backend_family,
            operation="fetch_one",
            params=params,
            row_found=row is not None,
            sql=sql,
        )
        if row is None:
            return None
        return self.runtime.materialize_select_row(select_query, tuple(row))

    async def execute(
        self, query: InsertQuery[Any] | UpdateQuery[Any] | DeleteQuery[Any]
    ) -> None:
        """Execute a write query inside this transaction."""

        connection = self.require_connection()
        self._validate_query_backend(query)
        sql, params = self.runtime.compile_write_sql(query)
        try:
            cursor = await connection.execute(sql, params)
            try:
                pass
            finally:
                await cursor.close()
        except Exception as error:
            self.runtime.logger.error(  # noqa: TRY400
                "query failed",
                backend=self.runtime.backend_family,
                error_type=type(error).__name__,
                operation="write",
                params=params,
                sql=sql,
            )
            msg = "write failed"
            raise ExecutionError(msg, sql=sql, params=params) from error
        self.runtime.logger.debug(
            "query executed",
            backend=self.runtime.backend_family,
            operation="write",
            params=params,
            sql=sql,
        )

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
        if isinstance(query, InsertQuery):
            insert_query = cast("InsertQuery[Any]", query)
            return cast("type[Table[Any]]", type(insert_query.row))
        if isinstance(query, SelectModelQuery | SelectValueQuery | SelectTupleQuery):
            return query.state.model
        if isinstance(query, UpdateQuery | DeleteQuery):
            return query.state.model
        msg = "query backend validation requires a snekql query"
        raise QueryCompilationError(msg)

    @staticmethod
    def _require_select_query(query: object) -> AnySelectQuery:
        if isinstance(query, SelectModelQuery | SelectValueQuery | SelectTupleQuery):
            return cast("AnySelectQuery", query)
        msg = "fetch requires a select query"
        raise QueryCompilationError(msg)


class Database:
    """Initialized snekql runtime service for database-backed execution.

    `Database.initialize(..., logger=logger)` is the preferred public construction
    path. The legacy `Database.initialize(logger, ...)` shape remains accepted for
    compatibility. A Database owns connectivity, schema startup work, and
    transaction entry.
    """

    def __init__(self, _initialized: Never, /) -> None:
        self.runtime = cast("RuntimeBackend", None)
        msg = "use Database.initialize(..., logger=logger) to create a Database"
        raise DatabaseRuntimeError(msg)

    @overload
    @classmethod
    async def initialize(
        cls,
        logger: StructuredLogger,
        backend: SQLiteConfig,
        *,
        models: Sequence[type[Table[Any]]] = (),
        schema_policy: SchemaPolicy = "strict",
    ) -> Self: ...

    @overload
    @classmethod
    async def initialize(
        cls,
        logger: StructuredLogger,
        backend: MariaDBConfig,
        *,
        models: Sequence[type[Table[Any]]] = (),
        schema_policy: SchemaPolicy = "strict",
    ) -> Self: ...

    @overload
    @classmethod
    async def initialize(
        cls,
        logger: StructuredLogger,
        *,
        database: Path | Literal[":memory:"],
        models: Sequence[type[Table[Any]]] = (),
        schema_policy: SchemaPolicy = "strict",
        pool_size: PositiveInt = 5,
        acquire_timeout: NonNegativeFloat = 30.0,
    ) -> Self: ...

    @overload
    @classmethod
    async def initialize(
        cls,
        backend: SQLiteConfig,
        *,
        logger: StructuredLogger,
        models: Sequence[type[Table[Any]]] = (),
        schema_policy: SchemaPolicy = "strict",
    ) -> Self: ...

    @overload
    @classmethod
    async def initialize(
        cls,
        backend: MariaDBConfig,
        *,
        logger: StructuredLogger,
        models: Sequence[type[Table[Any]]] = (),
        schema_policy: SchemaPolicy = "strict",
    ) -> Self: ...

    @overload
    @classmethod
    async def initialize(
        cls,
        *,
        logger: StructuredLogger,
        database: Path | Literal[":memory:"],
        models: Sequence[type[Table[Any]]] = (),
        schema_policy: SchemaPolicy = "strict",
        pool_size: PositiveInt = 5,
        acquire_timeout: NonNegativeFloat = 30.0,
    ) -> Self: ...

    @classmethod
    async def initialize(  # noqa: PLR0913
        cls,
        *args: object,
        logger: StructuredLogger | None = None,
        database: Path | Literal[":memory:"] | None = None,
        models: Sequence[type[Table[Any]]] = (),
        schema_policy: SchemaPolicy = "strict",
        pool_size: PositiveInt = 5,
        acquire_timeout: NonNegativeFloat = 30.0,
    ) -> Self:
        """Initialize connectivity, schema startup, and runtime lifecycle."""

        resolved_logger, backend = cls._resolve_initialize_call(args, logger)
        structured_logger = resolve_structured_logger(logger=resolved_logger)
        try:
            runtime_selection = resolve_runtime_selection(
                backend=backend,
                database=database,
                pool_size=pool_size,
                acquire_timeout=acquire_timeout,
            )
            runtime_config = runtime_selection.config
            backend_family = runtime_selection.backend_family
            runtime_selection.validate_model_backends(models)
            table_names = tuple(require_model_table_name(model) for model in models)
            structured_logger.info(
                "database initialization started",
                backend=backend_family,
                model_count=len(models),
                schema_policy=schema_policy,
                table_names=table_names,
            )
            structured_logger.debug(
                "database backend selected",
                backend=backend_family,
                acquire_timeout=runtime_config.acquire_timeout,
                pool_size=runtime_config.pool_size,
            )
            runtime = cast(
                "RuntimeBackend",
                await runtime_selection.initialize_runtime(
                    models,
                    schema_policy,
                    logger=structured_logger,
                ),
            )
            structured_logger.info(
                "database initialization completed",
                backend=backend_family,
                model_count=len(models),
                table_names=table_names,
            )
        except Exception as error:
            structured_logger.error(  # noqa: TRY400
                "database initialization failed",
                error_type=type(error).__name__,
            )
            raise
        database_instance = cls.__new__(cls)
        database_instance.runtime = runtime
        return database_instance

    @staticmethod
    def _resolve_initialize_call(
        args: tuple[object, ...],
        logger: StructuredLogger | None,
    ) -> tuple[StructuredLogger, object | None]:
        if len(args) > 2:  # noqa: PLR2004
            msg = "Database.initialize accepts at most logger and backend positional arguments"
            raise DatabaseRuntimeError(msg)
        if not args:
            if logger is None:
                msg = "Database.initialize requires logger"
                raise DatabaseRuntimeError(msg)
            return logger, None
        if len(args) == 1:
            argument = args[0]
            if logger is not None:
                return logger, argument
            if isinstance(argument, SQLiteConfig | MariaDBConfig):
                msg = "Database.initialize requires logger"
                raise DatabaseRuntimeError(msg)
            return cast("StructuredLogger", argument), None
        if logger is not None:
            msg = "logger cannot be provided twice"
            raise DatabaseRuntimeError(msg)
        return cast("StructuredLogger", args[0]), args[1]

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

        await self.runtime.close(self.runtime.acquire_timeout)

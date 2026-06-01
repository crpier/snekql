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

from snekql.errors import (
    DatabaseRuntimeError,
    ExecutionError,
    QueryCompilationError,
    TransactionClosedError,
)
from snekql.mariadb.config import Config as MariaDBConfig
from snekql.model import Table
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


@validate_boundary(DatabaseRuntimeError, "invalid database numeric configuration")
def _build_legacy_sqlite_config(
    *,
    acquire_timeout: NonNegativeFloat,
    database: Path | Literal[":memory:"],
    pool_size: PositiveInt,
) -> SQLiteConfig:
    """Build an explicit SQLite config for the legacy initializer shape."""

    return SQLiteConfig(
        acquire_timeout=acquire_timeout,
        database=database,
        pool_size=pool_size,
    )


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
        connection = await self.runtime.acquire(self.timeout)
        try:
            await connection.begin()
        except Exception as error:
            await self.runtime.release(connection)
            msg = "could not begin transaction"
            raise DatabaseRuntimeError(msg) from error
        self.connection = connection
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
            else:
                await connection.rollback()
        except Exception as error:
            if exc_type is None:
                msg = "could not close transaction"
                raise DatabaseRuntimeError(msg) from error
        finally:
            await self.runtime.release(connection)

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
        sql, params = self.runtime.compile_select_sql(select_query)
        try:
            cursor = await connection.execute(sql, params)
            try:
                rows = await cursor.fetchall()
            finally:
                await cursor.close()
        except Exception as error:
            msg = "select failed"
            raise ExecutionError(msg, sql=sql, params=params) from error
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
        sql, params = self.runtime.compile_select_sql(select_query)
        try:
            cursor = await connection.execute(sql, params)
            try:
                row = await cursor.fetchone()
            finally:
                await cursor.close()
        except Exception as error:
            msg = "select failed"
            raise ExecutionError(msg, sql=sql, params=params) from error
        if row is None:
            return None
        return self.runtime.materialize_select_row(select_query, tuple(row))

    async def execute(
        self, query: InsertQuery[Any] | UpdateQuery[Any] | DeleteQuery[Any]
    ) -> None:
        """Execute a write query inside this transaction."""

        connection = self.require_connection()
        sql, params = self.runtime.compile_write_sql(query)
        try:
            cursor = await connection.execute(sql, params)
            try:
                return
            finally:
                await cursor.close()
        except Exception as error:
            msg = "write failed"
            raise ExecutionError(msg, sql=sql, params=params) from error

    def require_connection(self) -> RuntimeConnection:
        """Return the active transaction connection or reject use-after-close."""

        connection = self.connection
        if self.closed or connection is None:
            msg = "transaction is closed"
            raise TransactionClosedError(msg)
        return connection

    @staticmethod
    def _require_select_query(query: object) -> AnySelectQuery:
        if isinstance(query, SelectModelQuery | SelectValueQuery | SelectTupleQuery):
            return cast("AnySelectQuery", query)
        msg = "fetch requires a select query"
        raise QueryCompilationError(msg)


class Database:
    """Initialized snekql runtime service for database-backed execution.

    `Database.initialize(...)` is the only public construction path. A Database
    owns connectivity, schema startup work, and transaction entry.
    """

    def __init__(self, _initialized: Never, /) -> None:
        self.runtime = cast("RuntimeBackend", None)
        msg = "use Database.initialize(...) to create a Database"
        raise DatabaseRuntimeError(msg)

    @overload
    @classmethod
    async def initialize(
        cls,
        backend: SQLiteConfig,
        *,
        models: Sequence[type[Table[Any]]] = (),
        schema_policy: SchemaPolicy = "strict",
    ) -> Self: ...

    @overload
    @classmethod
    async def initialize(
        cls,
        backend: MariaDBConfig,
        *,
        models: Sequence[type[Table[Any]]] = (),
        schema_policy: SchemaPolicy = "strict",
    ) -> Self: ...

    @overload
    @classmethod
    async def initialize(
        cls,
        *,
        database: Path | Literal[":memory:"],
        models: Sequence[type[Table[Any]]] = (),
        schema_policy: SchemaPolicy = "strict",
        pool_size: PositiveInt = 5,
        acquire_timeout: NonNegativeFloat = 30.0,
    ) -> Self: ...

    @classmethod
    async def initialize(  # noqa: PLR0913
        cls,
        backend: object | None = None,
        *,
        database: Path | Literal[":memory:"] | None = None,
        models: Sequence[type[Table[Any]]] = (),
        schema_policy: SchemaPolicy = "strict",
        pool_size: PositiveInt = 5,
        acquire_timeout: NonNegativeFloat = 30.0,
    ) -> Self:
        """Initialize connectivity, schema startup, and runtime lifecycle."""

        runtime_config = cls._resolve_backend_config(
            backend=backend,
            database=database,
            pool_size=pool_size,
            acquire_timeout=acquire_timeout,
        )
        if isinstance(runtime_config, MariaDBConfig):
            from snekql.mariadb.runtime import (  # noqa: PLC0415
                initialize_runtime as initialize_mariadb_runtime,
            )

            runtime = await initialize_mariadb_runtime(
                runtime_config,
                models,
                schema_policy,
            )
        else:
            try:
                from snekql.sqlite.runtime import (  # noqa: PLC0415
                    initialize_runtime as initialize_sqlite_runtime,
                )
            except ModuleNotFoundError as error:
                if error.name == "aiosqlite":
                    msg = "SQLite runtime requires the aiosqlite extra; install with snekql[aiosqlite]"
                    raise DatabaseRuntimeError(msg) from error
                raise

            runtime = await initialize_sqlite_runtime(
                runtime_config, models, schema_policy
            )
        database_instance = cls.__new__(cls)
        database_instance.runtime = runtime
        return database_instance

    @validate_boundary(DatabaseRuntimeError, "transaction timeout must be non-negative")
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

    @staticmethod
    def _resolve_backend_config(
        *,
        backend: object | None,
        database: Path | Literal[":memory:"] | None,
        pool_size: PositiveInt,
        acquire_timeout: NonNegativeFloat,
    ) -> SQLiteConfig | MariaDBConfig:
        if backend is not None:
            if not isinstance(backend, SQLiteConfig | MariaDBConfig):
                msg = "unsupported database backend config"
                raise DatabaseRuntimeError(msg)
            if database is not None:
                msg = "backend config cannot be combined with database"
                raise DatabaseRuntimeError(msg)
            return backend
        if database is None:
            msg = "Database.initialize requires a backend config or database"
            raise DatabaseRuntimeError(msg)
        return _build_legacy_sqlite_config(
            acquire_timeout=acquire_timeout,
            database=database,
            pool_size=pool_size,
        )

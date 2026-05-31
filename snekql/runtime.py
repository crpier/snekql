"""Query Runtime for async SQLite database lifecycle and transactions."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from types import TracebackType
from typing import Any, Literal, Never, Self, TypeVar, TypeVarTuple, cast, overload

from aiosqlite import Connection, Error

from snekql._pool import (
    SQLiteConnectionPool,
    close_sqlite_connection,
    normalize_sqlite_database,
    open_sqlite_connection,
)
from snekql.errors import (
    DatabaseRuntimeError,
    ExecutionError,
    QueryCompilationError,
    TransactionClosedError,
)
from snekql.model import Table, encode_model_row, require_model_table_name
from snekql.query import (
    DeleteQuery,
    InsertQuery,
    SelectModelQuery,
    SelectTupleQuery,
    SelectValueQuery,
    UpdateQuery,
)
from snekql.schema import initialize_sqlite_schema, quote_sqlite_identifier
from snekql.schema import validate_schema_models, validate_schema_policy
from snekql.storage import SchemaPolicy

SelectOwnerT = TypeVar("SelectOwnerT", bound=Table[Any])
OwnerT = TypeVar("OwnerT", bound=Table[Any])
ReadModelT = TypeVar("ReadModelT", bound=Table[Any])
T = TypeVar("T")
Ts = TypeVarTuple("Ts")


class Transaction:
    """Async transaction that executes built snekql queries on one connection.

    >>> async def create_user(transaction: Transaction, user: User[Pending]) -> None:
    ...     await transaction.execute(insert(user))
    """

    closed: bool
    connection: Connection | None
    connection_pool: SQLiteConnectionPool
    timeout: float

    def __init__(
        self,
        *,
        connection_pool: SQLiteConnectionPool | None = None,
        timeout: float = 0.0,
    ) -> None:
        if connection_pool is None:
            raise DatabaseRuntimeError("use db.transaction(...) to start a transaction")
        self.closed: bool = False
        self.connection: Connection | None = None
        self.connection_pool: SQLiteConnectionPool = connection_pool
        self.timeout: float = timeout

    async def __aenter__(self) -> Self:
        if self.closed or self.connection is not None:
            raise TransactionClosedError("transaction is closed")
        connection = await self.connection_pool.acquire(self.timeout)
        try:
            await self.execute_sqlite(connection, "BEGIN", ())
        except Error as error:
            await self.connection_pool.release(connection)
            raise DatabaseRuntimeError("could not begin transaction") from error
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
            raise TransactionClosedError("transaction is closed")
        self.connection = None
        self.closed = True
        try:
            if exc_type is None:
                await self.execute_sqlite(connection, "COMMIT", ())
            else:
                await self.execute_sqlite(connection, "ROLLBACK", ())
        except Error as error:
            if exc_type is None:
                raise DatabaseRuntimeError("could not close transaction") from error
        finally:
            await self.connection_pool.release(connection)

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

        _ = query
        _ = self.require_connection()
        raise QueryCompilationError("select execution is not implemented yet")

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

        _ = query
        _ = self.require_connection()
        raise QueryCompilationError("select execution is not implemented yet")

    async def execute(
        self, query: InsertQuery[Any] | UpdateQuery[Any] | DeleteQuery[Any]
    ) -> None:
        """Execute a write query inside this transaction."""

        connection = self.require_connection()
        if not isinstance(query, InsertQuery):
            raise QueryCompilationError("only insert execution is implemented yet")
        sql, params = self.compile_insert(query)
        try:
            await self.execute_sqlite(connection, sql, params)
        except Error as error:
            raise ExecutionError("insert failed", sql=sql, params=params) from error

    def require_connection(self) -> Connection:
        """Return the active transaction connection or reject use-after-close."""

        connection = self.connection
        if self.closed or connection is None:
            raise TransactionClosedError("transaction is closed")
        return connection

    @staticmethod
    def compile_insert(query: InsertQuery[Any]) -> tuple[str, tuple[object, ...]]:
        """Compile a pending model insert into SQLite SQL and parameters."""

        model_class, row_values = encode_model_row(query.row)
        table_name = require_model_table_name(model_class)
        quoted_table = quote_sqlite_identifier(table_name)
        if not row_values:
            return f"INSERT INTO {quoted_table} DEFAULT VALUES", ()
        names = tuple(row_values)
        quoted_columns = ", ".join(quote_sqlite_identifier(name) for name in names)
        placeholders = ", ".join("?" for _ in names)
        sql = f"INSERT INTO {quoted_table} ({quoted_columns}) VALUES ({placeholders})"
        params = tuple(row_values[name] for name in names)
        return sql, params

    @staticmethod
    async def execute_sqlite(
        connection: Connection,
        sql: str,
        params: tuple[object, ...],
    ) -> None:
        """Execute SQLite SQL and close the cursor promptly."""

        cursor = await connection.execute(sql, params)
        try:
            return None
        finally:
            await cursor.close()


class Database:
    """Initialized snekql runtime service for SQLite-backed execution.

    `Database.initialize(...)` is the only public construction path. A Database
    owns connectivity, schema startup work, and transaction entry.
    """

    acquire_timeout: float
    connection_pool: SQLiteConnectionPool

    def __init__(self, _initialized: Never, /) -> None:
        self.acquire_timeout = 0.0
        self.connection_pool = cast(SQLiteConnectionPool, None)
        raise DatabaseRuntimeError("use Database.initialize(...) to create a Database")

    @classmethod
    async def initialize(
        cls,
        *,
        database: Path | Literal[":memory:"],
        models: Sequence[type[Table[Any]]] = (),
        schema_policy: SchemaPolicy = "strict",
        pool_size: int = 5,
        acquire_timeout: float = 30.0,
    ) -> Self:
        """Initialize connectivity, schema startup, and pool lifecycle."""

        if pool_size < 1:
            raise DatabaseRuntimeError("pool_size must be at least 1")
        if acquire_timeout < 0:
            raise DatabaseRuntimeError("acquire_timeout must be non-negative")
        validate_schema_policy(schema_policy)
        validate_schema_models(models)
        database_path = normalize_sqlite_database(database)
        connection = await open_sqlite_connection(database_path)
        try:
            await initialize_sqlite_schema(connection, models, schema_policy)
        except Exception:
            await close_sqlite_connection(connection)
            raise
        database_instance = cls.__new__(cls)
        database_instance.acquire_timeout = acquire_timeout
        database_instance.connection_pool = SQLiteConnectionPool(
            database_path=database_path,
            initial_connection=connection,
            pool_size=pool_size,
        )
        return database_instance

    def transaction(self, *, timeout: float | None = None) -> Transaction:
        """Create a transaction context manager using the runtime pool."""

        self.connection_pool.check_accepting_work()
        acquisition_timeout = self.acquire_timeout if timeout is None else timeout
        if acquisition_timeout < 0:
            raise DatabaseRuntimeError("transaction timeout must be non-negative")
        return Transaction(
            connection_pool=self.connection_pool,
            timeout=acquisition_timeout,
        )

    async def close(self) -> None:
        """Close this database runtime idempotently when shutdown succeeds."""

        await self.connection_pool.close(self.acquire_timeout)

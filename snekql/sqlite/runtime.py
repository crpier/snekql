"""SQLite adapter for the backend-neutral query runtime."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, Literal, cast

import anyio
from aiosqlite import Connection, Cursor

from snekql._pool import (
    SQLiteConnectionPool,
    close_sqlite_connection,
    normalize_sqlite_database,
    open_sqlite_connection,
)
from snekql._schema_startup import validate_schema_models, validate_schema_policy
from snekql.errors import DatabaseRuntimeError
from snekql.model import Table
from snekql.query import AnySelectQuery
from snekql.sqlite.config import Config
from snekql.sqlite.query import (
    compile_sqlite_select_sql,
    compile_sqlite_write_sql,
    materialize_sqlite_select_row,
)
from snekql.sqlite.schema import initialize_sqlite_schema
from snekql.storage import SchemaPolicy
from snekql.structured_logging import ResolvedStructuredLogger
from snekql.validation import NonNegativeFloat


class SQLiteCursorAdapter:
    """Runtime cursor adapter backed by an aiosqlite cursor."""

    def __init__(self, cursor: Cursor) -> None:
        self.cursor: Cursor = cursor

    async def fetchone(self) -> Sequence[object] | None:
        row = await self.cursor.fetchone()
        if row is None:
            return None
        return cast("Sequence[object]", row)

    async def fetchall(self) -> Sequence[Sequence[object]]:
        rows = await self.cursor.fetchall()
        return [cast("Sequence[object]", row) for row in rows]

    async def close(self) -> None:
        await self.cursor.close()


class SQLiteConnectionAdapter:
    """Runtime connection adapter backed by an aiosqlite connection."""

    def __init__(self, connection: Connection) -> None:
        self.connection: Connection = connection

    async def begin(self) -> None:
        await self._execute_control_sql("BEGIN")

    async def commit(self) -> None:
        await self._execute_control_sql("COMMIT")

    async def rollback(self) -> None:
        await self._execute_control_sql("ROLLBACK")

    async def execute(
        self,
        sql: str,
        params: tuple[object, ...],
    ) -> SQLiteCursorAdapter:
        cursor = await self.connection.execute(sql, params)
        return SQLiteCursorAdapter(cursor)

    async def _execute_control_sql(self, sql: str) -> None:
        cursor = await self.connection.execute(sql, ())
        try:
            return
        finally:
            await cursor.close()


class SQLiteRuntime:
    """SQLite adapter satisfying the backend-neutral runtime seam."""

    backend_family: Literal["sqlite"] = "sqlite"

    def __init__(
        self,
        *,
        logger: ResolvedStructuredLogger,
        acquire_timeout: NonNegativeFloat,
        connection_pool: SQLiteConnectionPool,
    ) -> None:
        self.acquire_timeout: NonNegativeFloat = acquire_timeout
        self.connection_pool: SQLiteConnectionPool = connection_pool
        self.logger: ResolvedStructuredLogger = logger

    async def acquire(
        self,
        acquisition_timeout: NonNegativeFloat,
    ) -> SQLiteConnectionAdapter:
        connection = await self.connection_pool.acquire(acquisition_timeout)
        return SQLiteConnectionAdapter(connection)

    async def release(self, connection: object) -> None:
        if not isinstance(connection, SQLiteConnectionAdapter):
            msg = "SQLite runtime cannot release a foreign connection"
            raise DatabaseRuntimeError(msg)
        with anyio.CancelScope(shield=True):
            await self.connection_pool.release(connection.connection)

    async def close(self, close_timeout: NonNegativeFloat) -> None:
        with anyio.CancelScope(shield=True):
            await self.connection_pool.close(close_timeout)

    def check_accepting_work(self) -> None:
        self.connection_pool.check_accepting_work()

    def compile_select_sql(
        self,
        query: AnySelectQuery,
    ) -> tuple[str, tuple[object, ...]]:
        return compile_sqlite_select_sql(query)

    def compile_write_sql(self, query: object) -> tuple[str, tuple[object, ...]]:
        return compile_sqlite_write_sql(query)

    def materialize_select_row(
        self,
        query: AnySelectQuery,
        row: Sequence[object],
    ) -> object:
        return materialize_sqlite_select_row(query, row)


async def initialize_runtime(
    config: Config,
    models: Sequence[type[Table[Any]]],
    schema_policy: SchemaPolicy,
    *,
    logger: ResolvedStructuredLogger,
) -> SQLiteRuntime:
    """Initialize SQLite connectivity, schema startup, and pool lifecycle."""

    validate_schema_policy(schema_policy)
    validate_schema_models(models)
    database_path = normalize_sqlite_database(config.database)
    logger.debug("sqlite connection opening", database_path=database_path)
    connection = await open_sqlite_connection(database_path)
    try:
        await initialize_sqlite_schema(
            connection,
            models,
            schema_policy,
            logger=logger,
        )
    except Exception:
        await close_sqlite_connection(connection)
        raise
    return SQLiteRuntime(
        logger=logger,
        acquire_timeout=config.acquire_timeout,
        connection_pool=SQLiteConnectionPool(
            logger=logger,
            database_path=database_path,
            initial_connection=connection,
            pool_size=config.pool_size,
        ),
    )


__all__ = [
    "SQLiteConnectionAdapter",
    "SQLiteCursorAdapter",
    "SQLiteRuntime",
    "initialize_runtime",
]

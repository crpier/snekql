"""SQLite adapter for the backend-neutral query runtime."""

from __future__ import annotations

import logging
from collections.abc import Sequence
from typing import Any, Literal, cast

import anyio
from aiosqlite import Connection, Cursor

from snekql.errors import DatabaseRuntimeError
from snekql.model import Table
from snekql.query import AnySelectQuery
from snekql.sqlite.config import Config
from snekql.sqlite.migrations import apply_sqlite_migrations
from snekql.sqlite.pool import (
    SQLiteConnectionPool,
    normalize_sqlite_database,
    open_sqlite_connection,
)
from snekql.sqlite.query import (
    compile_sqlite_select_sql,
    compile_sqlite_write_sql,
    materialize_sqlite_select_row,
    materialize_sqlite_write_rows,
)
from snekql.sqlite.schema import verify_sqlite_schema
from snekql.storage import SchemaPolicy
from snekql.validation import NonNegativeFloat

logger = logging.getLogger(__name__)


class SQLiteCursorAdapter:
    """Runtime cursor adapter backed by an aiosqlite cursor."""

    def __init__(self, cursor: Cursor) -> None:
        self.cursor: Cursor = cursor

    @property
    def rowcount(self) -> int:
        return self.cursor.rowcount

    async def fetchone(self) -> Sequence[object] | None:
        row = await self.cursor.fetchone()
        if row is None:
            return None
        return cast("Sequence[object]", row)

    async def fetchmany(self, size: int = 1) -> Sequence[Sequence[object]]:
        rows = await self.cursor.fetchmany(size)
        return [cast("Sequence[object]", row) for row in rows]

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

    async def execute_stream(
        self,
        sql: str,
        params: tuple[object, ...],
    ) -> SQLiteCursorAdapter:
        # aiosqlite's default cursor already yields rows lazily, so incremental
        # fetchmany over it streams without buffering the full result set.
        return await self.execute(sql, params)

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
        acquire_timeout: NonNegativeFloat,
        connection_pool: SQLiteConnectionPool,
    ) -> None:
        self.acquire_timeout: NonNegativeFloat = acquire_timeout
        self.connection_pool: SQLiteConnectionPool = connection_pool

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

    async def apply_migrations(self, migrations: dict[str, str]) -> None:
        """Apply pending migrations on a pooled connection (ADR 0007)."""

        connection = await self.connection_pool.acquire(self.acquire_timeout)
        try:
            await apply_sqlite_migrations(connection, migrations)
        finally:
            await self.connection_pool.release(connection)

    async def verify_schema(
        self,
        models: Sequence[type[Table[Any]]],
        schema_policy: SchemaPolicy,
    ) -> None:
        """Verify the live schema against models on a pooled connection."""

        connection = await self.connection_pool.acquire(self.acquire_timeout)
        try:
            await verify_sqlite_schema(connection, models, schema_policy)
        finally:
            await self.connection_pool.release(connection)

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
        *,
        validate: bool = True,
    ) -> object:
        return materialize_sqlite_select_row(query, row, validate=validate)

    def materialize_write_rows(
        self,
        query: object,
        rows: Sequence[Sequence[object]],
        *,
        validate: bool = True,
    ) -> list[object]:
        return materialize_sqlite_write_rows(query, rows, validate=validate)


async def initialize_runtime(config: Config) -> SQLiteRuntime:
    """Open SQLite connectivity and a connection pool; do no schema work.

    Initialization is connect-only (ADR 0007): it proves it can open and use a
    connection and returns a live runtime. Migrations and verification are
    explicit verbs on the Database.
    """

    database_path = normalize_sqlite_database(config.database)
    logger.debug("sqlite connection opening: %s", database_path)
    connection = await open_sqlite_connection(database_path)
    return SQLiteRuntime(
        acquire_timeout=config.acquire_timeout,
        connection_pool=SQLiteConnectionPool(
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

"""SQLite Migration History bookkeeping and raw-SQL migration execution."""

from __future__ import annotations

from contextlib import AbstractAsyncContextManager, nullcontext
from typing import TYPE_CHECKING

from aiosqlite import Connection

from snekql._migrations import run_migrations
from snekql.sqlite.identifiers import quote_identifier

if TYPE_CHECKING:
    from snekql.structured_logging import ResolvedStructuredLogger

_HISTORY_TABLE = "snekql_migrations"

_CREATE_HISTORY_SQL = (
    f"CREATE TABLE IF NOT EXISTS {quote_identifier(_HISTORY_TABLE)} "
    '("name" TEXT PRIMARY KEY NOT NULL, "applied_at" TEXT NOT NULL) STRICT'
)
"""DDL for the snekql-owned Migration History; STRICT to match managed tables."""

_SELECT_APPLIED_SQL = f"SELECT name FROM {quote_identifier(_HISTORY_TABLE)}"  # noqa: S608

# Server-side ISO-8601 UTC timestamp, mirroring the CurrentTimestamp DDL default
# so applied_at needs no client datetime conversion. It is observability only.
_INSERT_APPLIED_SQL = (
    f"INSERT INTO {quote_identifier(_HISTORY_TABLE)} (name, applied_at) "  # noqa: S608
    "VALUES (?, strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))"
)


async def _execute(
    connection: Connection, sql: str, params: tuple[object, ...]
) -> None:
    cursor = await connection.execute(sql, params)
    try:
        return
    finally:
        await cursor.close()


class SQLiteMigrationBackend:
    """Migration backend answering the neutral runner over an aiosqlite connection.

    The connection runs in autocommit (`isolation_level=None`), so each migration
    body and history row commits as-is with no snekql-owned transaction boundary.
    """

    def __init__(self, connection: Connection) -> None:
        self.connection: Connection = connection

    def migration_lock(self) -> AbstractAsyncContextManager[None]:
        """SQLite has no advisory lock; rely on write serialization (ADR 0002).

        Concurrent runs against one database file serialize their writes through
        SQLite's single-writer file lock, and `busy_timeout` makes a losing
        writer wait rather than raise "database is locked". The seam is a no-op:
        there is no cross-connection lock to acquire, so run migrations from a
        single place (`Database.migrate`) for a strong guarantee.
        """

        return nullcontext()

    async def ensure_history_table(self) -> None:
        await _execute(self.connection, _CREATE_HISTORY_SQL, ())

    async def fetch_applied_names(self) -> set[str]:
        cursor = await self.connection.execute(_SELECT_APPLIED_SQL, ())
        try:
            rows = await cursor.fetchall()
        finally:
            await cursor.close()
        return {str(row[0]) for row in rows}

    async def execute_migration_body(self, sql: str) -> None:
        await _execute(self.connection, sql, ())

    async def record_applied(self, name: str) -> None:
        await _execute(self.connection, _INSERT_APPLIED_SQL, (name,))


async def apply_sqlite_migrations(
    connection: Connection,
    migrations: dict[str, str],
    *,
    logger: ResolvedStructuredLogger,
) -> None:
    """Apply pending SQLite migrations through the backend-neutral runner."""

    await run_migrations(
        SQLiteMigrationBackend(connection),
        migrations,
        logger=logger,
    )

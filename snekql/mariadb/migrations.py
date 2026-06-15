"""MariaDB Migration History bookkeeping and raw-SQL migration execution."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast

from snekql._migrations import run_migrations
from snekql.mariadb.identifiers import quote_identifier
from snekql.mariadb.schema import TEXT_COLLATION

if TYPE_CHECKING:
    from snekql.structured_logging import ResolvedStructuredLogger

_HISTORY_TABLE = "snekql_migrations"

_CREATE_HISTORY_SQL = (
    f"CREATE TABLE {quote_identifier(_HISTORY_TABLE)} ("
    f"name VARCHAR(255) CHARACTER SET utf8mb4 COLLATE {TEXT_COLLATION} "
    "NOT NULL PRIMARY KEY, "
    "applied_at DATETIME(3) NOT NULL"
    ") ENGINE=InnoDB"
)
"""DDL for the snekql-owned Migration History, mirroring managed-table storage."""

# Existence is checked before creating rather than using CREATE TABLE IF NOT
# EXISTS, whose "table already exists" note aiomysql re-raises as a warning on
# every idempotent re-run.
_HISTORY_EXISTS_SQL = (
    "SELECT 1 FROM INFORMATION_SCHEMA.TABLES "
    "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = %s"
)

_SELECT_APPLIED_SQL = f"SELECT name FROM {quote_identifier(_HISTORY_TABLE)}"  # noqa: S608

# Server-side UTC timestamp so applied_at needs no client datetime conversion.
# It is observability only and never read for correctness.
_INSERT_APPLIED_SQL = (
    f"INSERT INTO {quote_identifier(_HISTORY_TABLE)} (name, applied_at) "  # noqa: S608
    "VALUES (%s, UTC_TIMESTAMP(3))"
)


async def _close_cursor(cursor: object) -> None:
    close_result = cast("Any", cursor).close()
    if close_result is not None:
        _ = await close_result


async def _execute(
    connection: object,
    sql: str,
    params: tuple[object, ...] = (),
) -> None:
    cursor = await cast("Any", connection).cursor()
    try:
        _ = await cursor.execute(sql, params)
    finally:
        await _close_cursor(cursor)


class MariaDBMigrationBackend:
    """Migration backend answering the neutral runner over an aiomysql connection.

    The pool opens connections with autocommit disabled, so each bookkeeping step
    is committed explicitly; DDL inside a migration body auto-commits server-side.
    Body and history row are still committed separately — there is no snekql-owned
    transaction boundary (ADR 0001), so migrations must be idempotent.
    """

    def __init__(self, connection: object) -> None:
        self.connection: object = connection

    async def ensure_history_table(self) -> None:
        if await self._history_table_exists():
            return
        await _execute(self.connection, _CREATE_HISTORY_SQL)

    async def fetch_applied_names(self) -> set[str]:
        cursor = await cast("Any", self.connection).cursor()
        try:
            _ = await cursor.execute(_SELECT_APPLIED_SQL)
            rows = await cursor.fetchall()
        finally:
            await _close_cursor(cursor)
        return {str(row[0]) for row in rows}

    async def _history_table_exists(self) -> bool:
        cursor = await cast("Any", self.connection).cursor()
        try:
            _ = await cursor.execute(_HISTORY_EXISTS_SQL, (_HISTORY_TABLE,))
            rows = await cursor.fetchall()
        finally:
            await _close_cursor(cursor)
        return bool(rows)

    async def execute_migration_body(self, sql: str) -> None:
        await _execute(self.connection, sql)
        await cast("Any", self.connection).commit()

    async def record_applied(self, name: str) -> None:
        await _execute(self.connection, _INSERT_APPLIED_SQL, (name,))
        await cast("Any", self.connection).commit()


async def apply_mariadb_migrations(
    connection: object,
    migrations: dict[str, str],
    *,
    logger: ResolvedStructuredLogger,
) -> None:
    """Apply pending MariaDB migrations through the backend-neutral runner."""

    await run_migrations(
        MariaDBMigrationBackend(connection),
        migrations,
        logger=logger,
    )

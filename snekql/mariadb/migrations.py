"""MariaDB Migration History bookkeeping and raw-SQL migration execution."""

from __future__ import annotations

import hashlib
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, Any, cast

from snekql._migrations import run_migrations
from snekql.errors import MigrationLockTimeoutError
from snekql.mariadb.identifiers import quote_identifier
from snekql.mariadb.schema import TEXT_COLLATION
from snekql.validation import NonNegativeFloat

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

    from snekql.structured_logging import ResolvedStructuredLogger

_HISTORY_TABLE = "snekql_migrations"

# MariaDB `GET_LOCK` names are server-wide (not per-schema), so the lock name is
# namespaced by database to avoid serializing migrations across unrelated apps on
# a shared server. Lock names are capped at 64 chars; a long database name is
# folded into a short stable digest so the namespace stays unique and in-bounds.
_LOCK_NAME_PREFIX = "snekql_migrations."
_LOCK_NAME_MAX = 64

_ACQUIRE_LOCK_SQL = "SELECT GET_LOCK(%s, %s)"
_RELEASE_LOCK_SQL = "SELECT RELEASE_LOCK(%s)"


def build_migration_lock_name(database: str) -> str:
    """Build the per-database `GET_LOCK` name, folding long names to a digest."""

    candidate = f"{_LOCK_NAME_PREFIX}{database}"
    if len(candidate) <= _LOCK_NAME_MAX:
        return candidate
    digest = hashlib.sha256(database.encode("utf-8")).hexdigest()[:16]
    return f"{_LOCK_NAME_PREFIX}{digest}"


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

    def __init__(
        self,
        connection: object,
        *,
        lock_name: str,
        lock_timeout: NonNegativeFloat,
    ) -> None:
        self.connection: object = connection
        self.lock_name: str = lock_name
        self.lock_timeout: NonNegativeFloat = lock_timeout

    @asynccontextmanager
    async def migration_lock(self) -> AsyncGenerator[None]:
        """Hold a connection-scoped `GET_LOCK` advisory lock for the apply flow.

        `GET_LOCK` waits up to the acquire timeout and returns 1 on success, 0 on
        timeout, NULL on error; anything but 1 surfaces as a lock timeout. The
        lock is connection-scoped, so `RELEASE_LOCK` frees it on a clean exit and
        a disconnect (crash) frees it server-side.
        """

        await self._acquire_lock()
        try:
            yield
        finally:
            await self._release_lock()

    async def _acquire_lock(self) -> None:
        cursor = await cast("Any", self.connection).cursor()
        try:
            _ = await cursor.execute(
                _ACQUIRE_LOCK_SQL, (self.lock_name, self.lock_timeout)
            )
            row = await cursor.fetchone()
        finally:
            await _close_cursor(cursor)
        if row is None or row[0] != 1:
            msg = (
                f"timed out acquiring migration lock {self.lock_name!r} "
                f"after {self.lock_timeout}s; another instance is migrating"
            )
            raise MigrationLockTimeoutError(msg)

    async def _release_lock(self) -> None:
        await _execute(self.connection, _RELEASE_LOCK_SQL, (self.lock_name,))

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
    lock_name: str,
    lock_timeout: NonNegativeFloat,
    logger: ResolvedStructuredLogger,
) -> None:
    """Apply pending MariaDB migrations through the backend-neutral runner."""

    await run_migrations(
        MariaDBMigrationBackend(
            connection, lock_name=lock_name, lock_timeout=lock_timeout
        ),
        migrations,
        logger=logger,
    )

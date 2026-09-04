"""SQLite adapter for the backend-neutral query runtime."""

from __future__ import annotations

import contextlib
import logging
from collections.abc import Sequence
from typing import TYPE_CHECKING, Any, Literal, cast

import anyio
from aiosqlite import Connection, Cursor, Error
from anyio.lowlevel import checkpoint

from snekql._migrations import MigrationPlan, MigrationResult
from snekql._query_codec import DialectQueryCodec
from snekql._schema_verification import SchemaVerificationResult
from snekql._telemetry import ParameterVisibility
from snekql.errors import DatabaseRuntimeError
from snekql.model import Table
from snekql.sqlite.config import Config
from snekql.sqlite.migrations import (
    SQLiteMigrationConnectionState,
    apply_sqlite_migrations,
    validate_sqlite_migrations,
    verify_sqlite_migrations,
)
from snekql.sqlite.pool import (
    SQLiteConnectionPool,
    normalize_sqlite_database,
    open_sqlite_connection,
)
from snekql.sqlite.retry import (
    DEFAULT_BUSY_RETRY_POLICY,
    BusyRetryPolicy,
    retry_on_sqlite_busy,
)
from snekql.sqlite.schema import verify_sqlite_schema
from snekql.storage import SchemaPolicy
from snekql.validation import NonNegativeFloat

if TYPE_CHECKING:
    from snekql.runtime import TransactionMode

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

    def __init__(
        self,
        connection: Connection,
        *,
        retry_policy: BusyRetryPolicy = DEFAULT_BUSY_RETRY_POLICY,
    ) -> None:
        self.connection: Connection = connection
        self.retry_policy: BusyRetryPolicy = retry_policy

    async def begin(self, mode: TransactionMode = "deferred") -> None:
        if mode == "immediate":
            # ``BEGIN IMMEDIATE`` takes the single writer lock now, so a losing
            # writer contends here -- before doing any read work -- rather than
            # discovering it can't write only at the first write statement. The
            # in-driver ``busy_timeout`` makes that contention wait; the bounded
            # retry-with-jitter absorbs a collision that outlasts the PRAGMA
            # wait, while a genuinely stuck lock still surfaces once the budget
            # is spent. Retrying lock acquisition (before any statement runs) is
            # safe; retrying a write inside an open transaction is not -- under
            # WAL a concurrent commit turns it into an unrecoverable
            # ``SQLITE_BUSY_SNAPSHOT``.
            await retry_on_sqlite_busy(self._begin_immediate, self.retry_policy)
            return
        await self._execute_control_sql("BEGIN")

    async def _begin_immediate(self) -> None:
        await self._execute_control_sql("BEGIN IMMEDIATE")

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
        operation_timeout: NonNegativeFloat = 30.0,
        connection_pool: SQLiteConnectionPool,
        parameter_visibility: ParameterVisibility = "redacted",
        busy_retry_policy: BusyRetryPolicy = DEFAULT_BUSY_RETRY_POLICY,
    ) -> None:
        self.acquire_timeout: NonNegativeFloat = acquire_timeout
        self.operation_timeout: NonNegativeFloat = operation_timeout
        self.parameter_visibility: ParameterVisibility = parameter_visibility
        self.connection_pool: SQLiteConnectionPool = connection_pool
        self.busy_retry_policy: BusyRetryPolicy = busy_retry_policy
        self.query_codec: DialectQueryCodec = DialectQueryCodec.for_backend("sqlite")

    async def acquire(
        self,
        acquisition_timeout: NonNegativeFloat,
    ) -> SQLiteConnectionAdapter:
        connection = await self.connection_pool.acquire(acquisition_timeout)
        return SQLiteConnectionAdapter(connection, retry_policy=self.busy_retry_policy)

    async def release(self, connection: object) -> None:
        if not isinstance(connection, SQLiteConnectionAdapter):
            msg = "SQLite runtime cannot release a foreign connection"
            raise DatabaseRuntimeError(msg)
        with anyio.CancelScope(shield=True):
            await self.connection_pool.release(connection.connection)

    async def discard(self, connection: object) -> None:
        """Physically close a connection whose driver state is uncertain."""

        if not isinstance(connection, SQLiteConnectionAdapter):
            msg = "SQLite runtime cannot discard a foreign connection"
            raise DatabaseRuntimeError(msg)
        with anyio.CancelScope(shield=True):
            await self.connection_pool.discard(connection.connection)

    async def close(self, close_timeout: NonNegativeFloat) -> None:
        with anyio.CancelScope(shield=True):
            await self.connection_pool.close(close_timeout)

    def check_accepting_work(self) -> None:
        self.connection_pool.check_accepting_work()

    def validate_migrations(self, migrations: MigrationPlan) -> None:
        """Reject invalid SQLite bodies before any pool acquisition."""

        validate_sqlite_migrations(migrations)

    async def _release_migration_connection(
        self,
        connection: Connection,
        connection_state: SQLiteMigrationConnectionState,
    ) -> None:
        """Return only a transaction-clean migration connection to the pool."""

        discard = False
        with anyio.CancelScope(shield=True):
            if connection.in_transaction:
                try:
                    await connection.rollback()
                except Exception:
                    discard = True
            if discard or not connection_state.reusable or connection.in_transaction:
                await self.connection_pool.discard(connection)
            else:
                await self.connection_pool.release(connection)
        await checkpoint()

    async def apply_migrations(
        self,
        migrations: MigrationPlan,
        *,
        adopt_legacy: bool = False,
    ) -> MigrationResult:
        """Apply pending migrations on a pooled connection (ADR 0007)."""

        connection = await self.connection_pool.acquire(self.acquire_timeout)
        connection_state = SQLiteMigrationConnectionState()
        try:
            return await apply_sqlite_migrations(
                connection,
                connection_state,
                migrations,
                adopt_legacy=adopt_legacy,
                busy_retry_policy=self.busy_retry_policy,
            )
        finally:
            await self._release_migration_connection(connection, connection_state)

    async def verify_migrations(self, migrations: MigrationPlan) -> None:
        """Read and compare Migration History without changing it."""

        connection = await self.connection_pool.acquire(self.acquire_timeout)
        connection_state = SQLiteMigrationConnectionState()
        try:
            await verify_sqlite_migrations(
                connection,
                connection_state,
                migrations,
            )
        finally:
            await self._release_migration_connection(connection, connection_state)

    async def verify_schema(
        self,
        models: Sequence[type[Table[Any]]],
        schema_policy: SchemaPolicy,
    ) -> SchemaVerificationResult:
        """Verify the live schema against models on a pooled connection."""

        connection = await self.connection_pool.acquire(self.acquire_timeout)
        try:
            return await verify_sqlite_schema(connection, models, schema_policy)
        finally:
            with anyio.CancelScope(shield=True):
                if connection.in_transaction:
                    with contextlib.suppress(Error):
                        await connection.rollback()
                if connection.in_transaction:
                    await self.connection_pool.discard(connection)
                else:
                    await self.connection_pool.release(connection)


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
        operation_timeout=config.operation_timeout,
        connection_pool=SQLiteConnectionPool(
            database_path=database_path,
            initial_connection=connection,
            pool_size=config.pool_size,
        ),
        parameter_visibility=config.parameter_visibility,
        busy_retry_policy=BusyRetryPolicy(
            max_retries=config.busy_max_retries,
            base_backoff=config.busy_base_backoff,
            max_backoff=config.busy_max_backoff,
        ),
    )


__all__ = [
    "SQLiteConnectionAdapter",
    "SQLiteCursorAdapter",
    "SQLiteRuntime",
    "initialize_runtime",
]

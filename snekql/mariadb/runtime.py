"""MariaDB adapter for the backend-neutral query runtime."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable, Sequence
from importlib import import_module
from typing import Any, Literal, cast

import anyio

from snekql.errors import (
    DatabaseClosedError,
    DatabaseCloseTimeoutError,
    DatabaseClosingError,
    DatabaseRuntimeError,
    PoolTimeoutError,
)
from snekql.mariadb.config import Config
from snekql.mariadb.migrations import (
    apply_mariadb_migrations,
    build_migration_lock_name,
)
from snekql.mariadb.query import (
    compile_mariadb_select_sql,
    compile_mariadb_write_sql,
    materialize_mariadb_select_row,
    materialize_mariadb_write_rows,
)
from snekql.mariadb.schema import initialize_mariadb_schema
from snekql.mariadb.settings import configure_mariadb_connection
from snekql.model import Table
from snekql.query import AnySelectQuery
from snekql.storage import SchemaPolicy
from snekql.validation import NonNegativeFloat

logger = logging.getLogger(__name__)


def _import_aiomysql() -> Any:
    """Import the optional MariaDB driver at runtime initialization time."""

    try:
        return cast("Any", import_module("aiomysql"))
    except ModuleNotFoundError as error:
        if error.name == "aiomysql":
            msg = "MariaDB runtime requires the aiomysql extra; install with snekql[aiomysql]"
            raise DatabaseRuntimeError(msg) from error
        raise


class MariaDBCursorAdapter:
    """Runtime cursor adapter backed by an aiomysql cursor."""

    def __init__(self, cursor: object) -> None:
        self.cursor: object = cursor

    async def fetchone(self) -> Sequence[object] | None:
        row = await cast("Any", self.cursor).fetchone()
        if row is None:
            return None
        return cast("Sequence[object]", row)

    async def fetchall(self) -> Sequence[Sequence[object]]:
        rows = await cast("Any", self.cursor).fetchall()
        return [cast("Sequence[object]", row) for row in rows]

    async def close(self) -> None:
        close_result = cast("Any", self.cursor).close()
        if close_result is not None:
            _ = await close_result


class MariaDBConnectionAdapter:
    """Runtime connection adapter backed by an aiomysql connection."""

    def __init__(self, connection: object) -> None:
        self.connection: object = connection

    async def begin(self) -> None:
        await cast("Any", self.connection).begin()

    async def commit(self) -> None:
        await cast("Any", self.connection).commit()

    async def rollback(self) -> None:
        await cast("Any", self.connection).rollback()

    async def execute(
        self,
        sql: str,
        params: tuple[object, ...],
    ) -> MariaDBCursorAdapter:
        cursor = await cast("Any", self.connection).cursor()
        try:
            _ = await cursor.execute(sql, params)
        except Exception:
            close_result = cursor.close()
            if close_result is not None:
                _ = await close_result
            raise
        return MariaDBCursorAdapter(cursor)


class MariaDBConnectionPool:
    """Small lifecycle wrapper around an aiomysql connection pool."""

    def __init__(
        self,
        pool: object,
    ) -> None:
        self.closed: bool = False
        self.closing: bool = False
        self.pool: object = pool

    def check_accepting_work(self) -> None:
        """Reject new work when closed or temporarily closing."""

        if self.closed:
            logger.warning("mariadb database rejected work: closed")
            msg = "database is closed"
            raise DatabaseClosedError(msg)
        if self.closing:
            logger.warning("mariadb database rejected work: closing")
            msg = "database is closing"
            raise DatabaseClosingError(msg)

    async def acquire(self, acquisition_timeout: NonNegativeFloat) -> object:
        """Acquire a MariaDB connection within the requested timeout."""

        self.check_accepting_work()
        logger.debug(
            "mariadb connection acquisition started (timeout=%s)", acquisition_timeout
        )
        try:
            pool = cast("Any", self.pool)
            acquire = cast("Callable[[], Awaitable[object]]", pool.acquire)
            with anyio.fail_after(acquisition_timeout):
                connection = await acquire()
        except TimeoutError as error:
            logger.warning(
                "mariadb connection acquisition timed out (timeout=%s)",
                acquisition_timeout,
            )
            msg = "timed out acquiring database connection"
            raise PoolTimeoutError(msg) from error
        await self._ensure_configured(connection)
        logger.debug("mariadb connection acquired")
        return connection

    async def _ensure_configured(self, connection: object) -> None:
        """Apply required session settings once per physical connection."""

        if getattr(connection, "_snekql_configured", False):
            return
        try:
            await configure_mariadb_connection(connection)
        except Exception:
            release = cast("Any", self.pool).release
            _ = release(connection)
            raise
        try:
            connection._snekql_configured = True  # type: ignore[attr-defined]  # noqa: SLF001
        except AttributeError:
            logger.debug("mariadb connection configuration marker unavailable")

    async def release(self, connection: object) -> None:
        """Return a connection to the underlying aiomysql pool."""

        release = cast("Any", self.pool).release
        _ = release(connection)
        logger.debug("mariadb connection released")

    async def close(self, close_timeout: NonNegativeFloat) -> None:
        """Close the underlying aiomysql pool and wait for connections."""

        logger.debug("mariadb database close started")
        if self.closed:
            logger.debug("mariadb database close skipped: already closed")
            return
        self.closing = True
        try:
            pool = cast("Any", self.pool)
            pool.close()
            wait_closed = cast("Callable[[], Awaitable[None]]", pool.wait_closed)
            with anyio.fail_after(close_timeout):
                await wait_closed()
        except TimeoutError as error:
            logger.warning("mariadb database close timed out")
            msg = "timed out closing database"
            raise DatabaseCloseTimeoutError(msg) from error
        else:
            self.closed = True
            self.closing = False
            logger.debug("mariadb database close completed")


class MariaDBRuntime:
    """MariaDB adapter satisfying the backend-neutral runtime seam."""

    backend_family: Literal["mariadb"] = "mariadb"

    def __init__(
        self,
        *,
        acquire_timeout: NonNegativeFloat,
        connection_pool: MariaDBConnectionPool,
    ) -> None:
        self.acquire_timeout: NonNegativeFloat = acquire_timeout
        self.connection_pool: MariaDBConnectionPool = connection_pool

    async def acquire(
        self,
        acquisition_timeout: NonNegativeFloat,
    ) -> MariaDBConnectionAdapter:
        connection = await self.connection_pool.acquire(acquisition_timeout)
        return MariaDBConnectionAdapter(connection)

    async def release(self, connection: object) -> None:
        if not isinstance(connection, MariaDBConnectionAdapter):
            msg = "MariaDB runtime cannot release a foreign connection"
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
        return compile_mariadb_select_sql(query)

    def compile_write_sql(self, query: object) -> tuple[str, tuple[object, ...]]:
        return compile_mariadb_write_sql(query)

    def materialize_select_row(
        self,
        query: AnySelectQuery,
        row: Sequence[object],
        *,
        validate: bool = True,
    ) -> object:
        return materialize_mariadb_select_row(query, row, validate=validate)

    def materialize_write_rows(
        self,
        query: object,
        rows: Sequence[Sequence[object]],
        *,
        validate: bool = True,
    ) -> list[object]:
        return materialize_mariadb_write_rows(query, rows, validate=validate)


async def initialize_runtime(
    config: Config,
    models: Sequence[type[Table[Any]]],
    schema_policy: SchemaPolicy,
    *,
    migrations: dict[str, str] | None = None,
) -> MariaDBRuntime:
    """Initialize MariaDB connectivity, migrations, schema startup, and pool."""

    aiomysql = _import_aiomysql()
    logger.debug("mariadb pool opening: %s:%s", config.host, config.port)
    pool = await aiomysql.create_pool(
        autocommit=False,
        charset=config.charset,
        connect_timeout=config.acquire_timeout,
        db=config.database,
        host=config.host,
        maxsize=config.pool_size,
        minsize=1,
        password=config.password,
        port=config.port,
        unix_socket=str(config.unix_socket) if config.unix_socket is not None else None,
        user=config.user,
    )
    connection_pool = MariaDBConnectionPool(pool)
    connection = await connection_pool.acquire(config.acquire_timeout)
    try:
        if migrations:
            await apply_mariadb_migrations(
                connection,
                migrations,
                lock_name=build_migration_lock_name(config.database),
                lock_timeout=config.acquire_timeout,
            )
        await initialize_mariadb_schema(
            connection,
            models,
            schema_policy,
            create_missing=not migrations,
        )
    except Exception:
        await connection_pool.release(connection)
        await connection_pool.close(config.acquire_timeout)
        raise
    await connection_pool.release(connection)
    return MariaDBRuntime(
        acquire_timeout=config.acquire_timeout,
        connection_pool=connection_pool,
    )


async def migrate_runtime(
    config: Config,
    migrations: dict[str, str],
) -> None:
    """Apply pending migrations on a short-lived MariaDB pool, no schema startup.

    The migrate-only path shares the apply runner with initialize() but skips
    schema startup and drift verification: it is the dedicated deploy step, not
    an application boot.
    """

    aiomysql = _import_aiomysql()
    logger.debug("mariadb migrate pool opening: %s:%s", config.host, config.port)
    pool = await aiomysql.create_pool(
        autocommit=False,
        charset=config.charset,
        connect_timeout=config.acquire_timeout,
        db=config.database,
        host=config.host,
        maxsize=config.pool_size,
        minsize=1,
        password=config.password,
        port=config.port,
        unix_socket=str(config.unix_socket) if config.unix_socket is not None else None,
        user=config.user,
    )
    connection_pool = MariaDBConnectionPool(pool)
    connection = await connection_pool.acquire(config.acquire_timeout)
    try:
        await apply_mariadb_migrations(
            connection,
            migrations,
            lock_name=build_migration_lock_name(config.database),
            lock_timeout=config.acquire_timeout,
        )
    finally:
        await connection_pool.release(connection)
        await connection_pool.close(config.acquire_timeout)


__all__ = [
    "MariaDBConnectionAdapter",
    "MariaDBConnectionPool",
    "MariaDBCursorAdapter",
    "MariaDBRuntime",
    "initialize_runtime",
    "migrate_runtime",
]

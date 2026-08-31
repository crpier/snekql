"""MariaDB adapter for the backend-neutral query runtime."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable, Sequence
from importlib import import_module
from typing import TYPE_CHECKING, Any, Literal, cast

import anyio

from snekql._pool_gate import FairAdmissionGate
from snekql._query_codec import DialectQueryCodec
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
from snekql.mariadb.schema import verify_mariadb_schema
from snekql.mariadb.settings import configure_mariadb_connection
from snekql.model import Table
from snekql.storage import SchemaPolicy
from snekql.validation import NonNegativeFloat, PositiveInt

if TYPE_CHECKING:
    from snekql.runtime import TransactionMode

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

    @property
    def rowcount(self) -> int:
        return cast("int", cast("Any", self.cursor).rowcount)

    async def fetchone(self) -> Sequence[object] | None:
        row = await cast("Any", self.cursor).fetchone()
        if row is None:
            return None
        return cast("Sequence[object]", row)

    async def fetchmany(self, size: int = 1) -> Sequence[Sequence[object]]:
        rows = await cast("Any", self.cursor).fetchmany(size)
        return [cast("Sequence[object]", row) for row in rows]

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

    async def begin(self, mode: TransactionMode = "deferred") -> None:
        # InnoDB serializes writers with row-level locks rather than one global
        # writer lock, so there is no eager writer-lock acquisition to request:
        # ``immediate`` and ``deferred`` both open an ordinary transaction. The
        # parameter exists to satisfy the backend-neutral ``RuntimeConnection``
        # seam (and is a no-op here).
        del mode
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
        return await self._run_on_cursor(cursor, sql, params)

    async def execute_stream(
        self,
        sql: str,
        params: tuple[object, ...],
    ) -> MariaDBCursorAdapter:
        # A default aiomysql cursor buffers the whole result set client-side on
        # execute, defeating incremental fetch. SSCursor streams rows from the
        # server instead; it must be fully consumed or closed before the next
        # statement runs on this connection, which the held transaction lock and
        # the cursor close in fetch_chunks guarantee.
        ss_cursor = cast("Any", import_module("aiomysql")).SSCursor
        cursor = await cast("Any", self.connection).cursor(ss_cursor)
        return await self._run_on_cursor(cursor, sql, params)

    @staticmethod
    async def _run_on_cursor(
        cursor: Any,
        sql: str,
        params: tuple[object, ...],
    ) -> MariaDBCursorAdapter:
        try:
            _ = await cursor.execute(sql, params)
        except Exception:
            close_result = cursor.close()
            if close_result is not None:
                _ = await close_result
            raise
        return MariaDBCursorAdapter(cursor)


class MariaDBConnectionPool:
    """Small lifecycle wrapper around an aiomysql connection pool.

    aiomysql's own checkout has no fairness guarantee: when the pool is
    exhausted it wakes a blocked acquirer without regard to arrival order, so a
    task that releases and immediately re-acquires can barge past tasks that
    were already waiting. This wrapper puts the shared FIFO admission gate
    (``snekql/_pool_gate.py``) in front of ``pool.acquire()``: at most
    ``pool_size`` acquirers are admitted at once, and parked acquirers are
    served strictly in arrival order. Because admission never exceeds the
    underlying pool's capacity, ``pool.acquire()`` always finds a free
    connection and never blocks, so the gate alone decides service order.
    """

    def __init__(
        self,
        pool: object,
        *,
        pool_size: PositiveInt = 1,
    ) -> None:
        self.closed: bool = False
        self.closing: bool = False
        self.pool: object = pool
        self.pool_size: PositiveInt = pool_size
        self.gate: FairAdmissionGate = FairAdmissionGate(
            capacity=pool_size,
            check_accepting_work=self.check_accepting_work,
            log_label="mariadb",
        )

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

        logger.debug(
            "mariadb connection acquisition started (timeout=%s)", acquisition_timeout
        )
        deadline = anyio.current_time() + acquisition_timeout
        await self.gate.admit(deadline, acquisition_timeout)
        try:
            connection = await self._checkout(deadline, acquisition_timeout)
        except BaseException:
            await self.gate.release()
            raise
        try:
            await self._ensure_configured(connection)
        except BaseException:
            # ``_ensure_configured`` returns the connection to the underlying
            # pool on failure; free our admission slot so a waiter can proceed.
            await self.gate.release()
            raise
        logger.debug("mariadb connection acquired")
        return connection

    async def _checkout(
        self,
        deadline: float,
        acquisition_timeout: NonNegativeFloat,
    ) -> object:
        """Check a connection out of the underlying aiomysql pool.

        The admission gate guarantees a free connection, so this should not
        block; the deadline only guards against a misbehaving driver.
        """

        try:
            pool = cast("Any", self.pool)
            acquire = cast("Callable[[], Awaitable[object]]", pool.acquire)
            remaining = deadline - anyio.current_time()
            with anyio.fail_after(remaining):
                return await acquire()
        except TimeoutError as error:
            logger.warning(
                "mariadb connection acquisition timed out (timeout=%s)",
                acquisition_timeout,
            )
            msg = "timed out acquiring database connection"
            raise PoolTimeoutError(msg) from error

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
            cast("Any", connection)._snekql_configured = True  # noqa: SLF001
        except AttributeError:
            logger.debug("mariadb connection configuration marker unavailable")

    async def release(self, connection: object) -> None:
        """Return a connection to the underlying aiomysql pool.

        Returns the connection to the driver before freeing the admission slot
        so the next FIFO waiter always finds a free connection to check out.
        Shielded so a cancellation between the two steps cannot leak a slot.
        """

        with anyio.CancelScope(shield=True):
            release = cast("Any", self.pool).release
            _ = release(connection)
            await self.gate.release()
            logger.debug("mariadb connection released")

    async def close(self, close_timeout: NonNegativeFloat) -> None:
        """Close the underlying aiomysql pool and wait for connections."""

        logger.debug("mariadb database close started")
        if self.closed:
            logger.debug("mariadb database close skipped: already closed")
            return
        async with self.gate.condition:
            self.closing = True
            # Wake parked acquirers so they re-check ``check_accepting_work``
            # and fail fast instead of waiting out their own deadline.
            self.gate.condition.notify_all()
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
        migration_lock_name: str,
    ) -> None:
        self.acquire_timeout: NonNegativeFloat = acquire_timeout
        self.connection_pool: MariaDBConnectionPool = connection_pool
        self.migration_lock_name: str = migration_lock_name
        self.query_codec: DialectQueryCodec = DialectQueryCodec.for_backend("mariadb")

    async def acquire(
        self,
        acquisition_timeout: NonNegativeFloat,
    ) -> MariaDBConnectionAdapter:
        connection = await self.connection_pool.acquire(acquisition_timeout)
        return MariaDBConnectionAdapter(connection)

    async def apply_migrations(self, migrations: dict[str, str]) -> None:
        """Apply pending migrations on a pooled connection under the lock (ADR 0007)."""

        connection = await self.connection_pool.acquire(self.acquire_timeout)
        try:
            await apply_mariadb_migrations(
                connection,
                migrations,
                lock_name=self.migration_lock_name,
                lock_timeout=self.acquire_timeout,
            )
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
            await verify_mariadb_schema(connection, models, schema_policy)
        finally:
            await self.connection_pool.release(connection)

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


async def initialize_runtime(config: Config) -> MariaDBRuntime:
    """Open MariaDB connectivity and a connection pool; do no schema work.

    Initialization is connect-only (ADR 0007): it opens the pool, proves it can
    acquire and configure a connection, and returns a live runtime. Migrations
    and verification are explicit verbs on the Database.
    """

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
    connection_pool = MariaDBConnectionPool(pool, pool_size=config.pool_size)
    # Prove connectivity (and apply session settings once) before returning.
    connection = await connection_pool.acquire(config.acquire_timeout)
    await connection_pool.release(connection)
    return MariaDBRuntime(
        acquire_timeout=config.acquire_timeout,
        connection_pool=connection_pool,
        migration_lock_name=build_migration_lock_name(config.database),
    )


__all__ = [
    "MariaDBConnectionAdapter",
    "MariaDBConnectionPool",
    "MariaDBCursorAdapter",
    "MariaDBRuntime",
    "initialize_runtime",
]

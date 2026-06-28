"""MariaDB adapter for the backend-neutral query runtime."""

from __future__ import annotations

import logging
from collections import deque
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
from snekql.mariadb.schema import verify_mariadb_schema
from snekql.mariadb.settings import configure_mariadb_connection
from snekql.model import Table
from snekql.query import AnySelectQuery
from snekql.storage import SchemaPolicy
from snekql.validation import NonNegativeFloat, PositiveInt

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
    were already waiting. This wrapper puts a FIFO admission gate
    in front of ``pool.acquire()``, mirroring the ticket queue in
    ``snekql/sqlite/pool.py``: at most ``pool_size`` acquirers are admitted at
    once, and parked acquirers are served strictly in arrival order. Because
    admission never exceeds the underlying pool's capacity, ``pool.acquire()``
    always finds a free connection and never blocks, so the gate alone decides
    service order.
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
        self.condition: anyio.Condition = anyio.Condition()
        # Number of acquirers that hold an admission slot (a checked-out or
        # about-to-be-checked-out connection). Bounded by ``pool_size``.
        self._admitted: int = 0
        # FIFO queue of waiting-acquirer ticket numbers. A parked acquirer may
        # only claim a slot when its ticket is at the front, which stops a task
        # that just released from barging ahead of earlier waiters.
        self._waiters: deque[int] = deque()
        self._next_ticket: int = 0

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
        await self._admit(deadline, acquisition_timeout)
        try:
            connection = await self._checkout(deadline, acquisition_timeout)
        except BaseException:
            await self._release_admission()
            raise
        try:
            await self._ensure_configured(connection)
        except BaseException:
            # ``_ensure_configured`` returns the connection to the underlying
            # pool on failure; free our admission slot so a waiter can proceed.
            await self._release_admission()
            raise
        logger.debug("mariadb connection acquired")
        return connection

    async def _admit(
        self,
        deadline: float,
        acquisition_timeout: NonNegativeFloat,
    ) -> None:
        """Take a FIFO admission slot, parking in arrival order under contention.

        Holds ``self.condition`` only while inspecting/claiming the gate; the
        underlying checkout happens after this returns.
        """

        ticket: int | None = None
        while True:
            async with self.condition:
                try:
                    self.check_accepting_work()
                except BaseException:
                    # Rejected (closing/closed) while already queued: drop our
                    # ticket so later FIFO waiters are not blocked behind us.
                    if ticket is not None:
                        self._discard_waiter(ticket)
                    raise
                if self._waiter_is_served_first(ticket) and (
                    self._admitted < self.pool_size
                ):
                    if ticket is not None:
                        _ = self._waiters.popleft()
                    self._admitted += 1
                    return
                ticket = self._enqueue_waiter(ticket)
                await self._wait_for_release(ticket, deadline, acquisition_timeout)

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

    async def _release_admission(self) -> None:
        """Free an admission slot and wake the next FIFO waiter.

        Shielded because it runs on cleanup paths (acquisition failure and
        release): dropping the slot must complete even under cancellation, or a
        parked FIFO waiter stalls until its own deadline.
        """

        with anyio.CancelScope(shield=True):
            async with self.condition:
                self._admitted -= 1
                self.condition.notify_all()

    def _waiter_is_served_first(self, ticket: int | None) -> bool:
        """Return whether this acquirer may claim a slot now.

        A fresh acquirer (no ticket yet) may proceed only when nobody is queued
        ahead of it; a parked acquirer may proceed only at the front of the
        queue. Must be called while holding ``self.condition``.
        """

        if ticket is None:
            return not self._waiters
        return bool(self._waiters) and self._waiters[0] == ticket

    def _enqueue_waiter(self, ticket: int | None) -> int:
        """Append a new FIFO ticket for a parking acquirer, or reuse its own.

        Must be called while holding ``self.condition``.
        """

        if ticket is not None:
            return ticket
        ticket = self._next_ticket
        self._next_ticket += 1
        self._waiters.append(ticket)
        return ticket

    async def _wait_for_release(
        self,
        ticket: int,
        deadline: float,
        acquisition_timeout: NonNegativeFloat,
    ) -> None:
        """Wait for a slot to free up, or time out the acquisition.

        Must be called while holding ``self.condition``; drops ``ticket`` and
        raises ``PoolTimeoutError`` when the deadline passes.
        """

        remaining_timeout = deadline - anyio.current_time()
        if remaining_timeout > 0:
            try:
                with anyio.fail_after(remaining_timeout):
                    await self.condition.wait()
            except TimeoutError as error:
                self._discard_waiter(ticket)
                logger.warning(
                    "mariadb connection acquisition timed out (timeout=%s)",
                    acquisition_timeout,
                )
                msg = "timed out acquiring database connection"
                raise PoolTimeoutError(msg) from error
            except BaseException:
                # Cancelled while parked: drop our ticket so later FIFO waiters
                # are not blocked behind a dead acquirer. ``condition.wait`` has
                # re-acquired the lock by the time it propagates, so this runs
                # safely under cancellation.
                self._discard_waiter(ticket)
                raise
            return
        self._discard_waiter(ticket)
        logger.warning(
            "mariadb connection acquisition timed out (timeout=%s)",
            acquisition_timeout,
        )
        msg = "timed out acquiring database connection"
        raise PoolTimeoutError(msg)

    def _discard_waiter(self, ticket: int) -> None:
        """Drop a no-longer-waiting ticket and let the next waiter retry.

        Must be called while holding ``self.condition``.
        """

        if ticket in self._waiters:
            self._waiters.remove(ticket)
        self.condition.notify_all()

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
        """Return a connection to the underlying aiomysql pool.

        Returns the connection to the driver before freeing the admission slot
        so the next FIFO waiter always finds a free connection to check out.
        Shielded so a cancellation between the two steps cannot leak a slot.
        """

        with anyio.CancelScope(shield=True):
            release = cast("Any", self.pool).release
            _ = release(connection)
            await self._release_admission()
            logger.debug("mariadb connection released")

    async def close(self, close_timeout: NonNegativeFloat) -> None:
        """Close the underlying aiomysql pool and wait for connections."""

        logger.debug("mariadb database close started")
        if self.closed:
            logger.debug("mariadb database close skipped: already closed")
            return
        async with self.condition:
            self.closing = True
            # Wake parked acquirers so they re-check ``check_accepting_work``
            # and fail fast instead of waiting out their own deadline.
            self.condition.notify_all()
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

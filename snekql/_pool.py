"""Internal async SQLite connection pool for Query Runtime."""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from pathlib import Path

from aiosqlite import Connection, Error, connect

from snekql.errors import (
    DatabaseClosedError,
    DatabaseCloseTimeoutError,
    DatabaseClosingError,
    DatabaseRuntimeError,
    PoolTimeoutError,
)
from snekql.structured_logging import ResolvedStructuredLogger
from snekql.validation import NonNegativeFloat, PositiveInt


def normalize_sqlite_database(database: object) -> str:
    """Convert the public database initializer value to an aiosqlite path."""

    if type(database) is str and database == ":memory:":
        return ":memory:"
    if isinstance(database, Path):
        return str(database)
    msg = "database must be a pathlib.Path or the exact string ':memory:'"
    raise DatabaseRuntimeError(
        msg,
    )


async def open_sqlite_connection(database_path: str) -> Connection:
    """Open and prove an async SQLite connection."""

    try:
        connection = await connect(database_path, isolation_level=None)
        cursor = await connection.execute("SELECT 1")
        try:
            _ = await cursor.fetchone()
        finally:
            await cursor.close()
    except Error as error:
        msg = "could not initialize SQLite connection"
        raise DatabaseRuntimeError(msg) from error
    else:
        return connection


async def close_sqlite_connection(connection: Connection) -> None:
    """Close an async SQLite connection with package-originated errors."""

    try:
        await connection.close()
    except Error as error:
        msg = "could not close SQLite connection"
        raise DatabaseRuntimeError(msg) from error


class SQLiteConnectionPool:
    """Bounded lazy async SQLite connection pool owned by a Database."""

    active_connections: int
    closed: bool
    closing: bool
    condition: asyncio.Condition
    database_path: str
    idle_connections: list[Connection]
    opening_connections: int
    pool_size: PositiveInt

    def __init__(
        self,
        *,
        database_path: str,
        initial_connection: Connection,
        logger: ResolvedStructuredLogger,
        pool_size: PositiveInt,
    ) -> None:
        self.active_connections: int = 0
        self.closed: bool = False
        self.closing: bool = False
        self.condition: asyncio.Condition = asyncio.Condition()
        self.database_path: str = database_path
        self.idle_connections: list[Connection] = [initial_connection]
        self.logger: ResolvedStructuredLogger = logger
        self.opening_connections: int = 0
        self.pool_size: PositiveInt = pool_size

    def check_accepting_work(self) -> None:
        """Reject new work when closed or temporarily closing."""

        if self.closed:
            self.logger.warning("database rejected work", reason="closed")
            msg = "database is closed"
            raise DatabaseClosedError(msg)
        if self.closing:
            self.logger.warning("database rejected work", reason="closing")
            msg = "database is closing"
            raise DatabaseClosingError(msg)

    async def acquire(self, acquisition_timeout: NonNegativeFloat, /) -> Connection:
        """Acquire an existing or lazily-created connection within timeout."""

        self.logger.debug(
            "connection acquisition started",
            backend="sqlite",
            timeout=acquisition_timeout,
        )
        event_loop = asyncio.get_running_loop()
        deadline = event_loop.time() + acquisition_timeout
        while True:
            async with self.condition:
                self.check_accepting_work()
                if self.idle_connections:
                    connection = self.idle_connections.pop()
                    self.active_connections += 1
                    self.logger.debug(
                        "connection acquired",
                        backend="sqlite",
                        source="idle",
                    )
                    return connection
                if self.connection_count() < self.pool_size:
                    self.opening_connections += 1
                    break
                remaining_timeout = deadline - event_loop.time()
                if remaining_timeout <= 0:
                    self.logger.warning(
                        "connection acquisition timed out",
                        backend="sqlite",
                        timeout=acquisition_timeout,
                    )
                    msg = "timed out acquiring database connection"
                    raise PoolTimeoutError(msg)
                try:
                    _ = await asyncio.wait_for(
                        self.condition.wait(),
                        timeout=remaining_timeout,
                    )
                except TimeoutError as error:
                    self.logger.warning(
                        "connection acquisition timed out",
                        backend="sqlite",
                        timeout=acquisition_timeout,
                    )
                    msg = "timed out acquiring database connection"
                    raise PoolTimeoutError(
                        msg,
                    ) from error

        try:
            opened_connection = await open_sqlite_connection(self.database_path)
        except Exception:
            async with self.condition:
                self.opening_connections -= 1
                self.condition.notify_all()
            raise
        async with self.condition:
            self.opening_connections -= 1
            if not self.closed and not self.closing:
                self.active_connections += 1
                self.condition.notify_all()
                self.logger.debug(
                    "connection acquired",
                    backend="sqlite",
                    source="opened",
                )
                return opened_connection
        await close_sqlite_connection(opened_connection)
        self.check_accepting_work()
        msg = "database is closing"
        raise DatabaseClosingError(msg)

    async def release(self, connection: Connection) -> None:
        """Return a checked-out connection or close it during shutdown."""

        should_close = False
        async with self.condition:
            self.active_connections -= 1
            if self.closed or self.closing:
                should_close = True
            else:
                self.idle_connections.append(connection)
            self.condition.notify_all()
        self.logger.debug(
            "connection released",
            backend="sqlite",
            closed=should_close,
        )
        if should_close:
            await close_sqlite_connection(connection)

    async def close(self, close_timeout: NonNegativeFloat, /) -> None:
        """Close idle connections and wait for checked-out work to finish."""

        self.logger.debug("database close started", backend="sqlite")
        async with self.condition:
            if self.closed:
                self.logger.debug("database close skipped", backend="sqlite")
                return
            if self.closing:
                msg = "database is already closing"
                raise DatabaseClosingError(msg)
            self.closing = True
            idle_connections = list(self.idle_connections)
            self.idle_connections.clear()
            self.condition.notify_all()
        await self.close_connections(idle_connections)

        event_loop = asyncio.get_running_loop()
        deadline = event_loop.time() + close_timeout
        while True:
            async with self.condition:
                if self.active_connections == 0 and self.opening_connections == 0:
                    remaining_idle_connections = list(self.idle_connections)
                    self.idle_connections.clear()
                    self.closed = True
                    self.closing = False
                    self.condition.notify_all()
                    break
                remaining_timeout = deadline - event_loop.time()
                if remaining_timeout <= 0:
                    self.closing = False
                    self.condition.notify_all()
                    self.logger.warning("database close timed out", backend="sqlite")
                    msg = "database close timed out"
                    raise DatabaseCloseTimeoutError(msg)
                try:
                    _ = await asyncio.wait_for(
                        self.condition.wait(),
                        timeout=remaining_timeout,
                    )
                except TimeoutError as error:
                    self.closing = False
                    self.condition.notify_all()
                    self.logger.warning("database close timed out", backend="sqlite")
                    msg = "database close timed out"
                    raise DatabaseCloseTimeoutError(msg) from error
        await self.close_connections(remaining_idle_connections)
        self.logger.debug("database close completed", backend="sqlite")

    def connection_count(self) -> int:
        """Return all open, checked-out, and currently opening connections."""

        return (
            len(self.idle_connections)
            + self.active_connections
            + self.opening_connections
        )

    @staticmethod
    async def close_connections(connections: Sequence[Connection]) -> None:
        """Close a sequence of SQLite connections."""

        for connection in connections:
            await close_sqlite_connection(connection)

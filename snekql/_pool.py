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


def normalize_sqlite_database(database: object) -> str:
    """Convert the public database initializer value to an aiosqlite path."""

    if type(database) is str and database == ":memory:":
        return ":memory:"
    if isinstance(database, Path):
        return str(database)
    raise DatabaseRuntimeError(
        "database must be a pathlib.Path or the exact string ':memory:'",
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
        return connection
    except Error as error:
        raise DatabaseRuntimeError("could not initialize SQLite connection") from error


async def close_sqlite_connection(connection: Connection) -> None:
    """Close an async SQLite connection with package-originated errors."""

    try:
        await connection.close()
    except Error as error:
        raise DatabaseRuntimeError("could not close SQLite connection") from error


class SQLiteConnectionPool:
    """Bounded lazy async SQLite connection pool owned by a Database."""

    active_connections: int
    closed: bool
    closing: bool
    condition: asyncio.Condition
    database_path: str
    idle_connections: list[Connection]
    opening_connections: int
    pool_size: int

    def __init__(
        self,
        *,
        database_path: str,
        initial_connection: Connection,
        pool_size: int,
    ) -> None:
        self.active_connections: int = 0
        self.closed: bool = False
        self.closing: bool = False
        self.condition: asyncio.Condition = asyncio.Condition()
        self.database_path: str = database_path
        self.idle_connections: list[Connection] = [initial_connection]
        self.opening_connections: int = 0
        self.pool_size: int = pool_size

    def check_accepting_work(self) -> None:
        """Reject new work when closed or temporarily closing."""

        if self.closed:
            raise DatabaseClosedError("database is closed")
        if self.closing:
            raise DatabaseClosingError("database is closing")

    async def acquire(self, timeout: float, /) -> Connection:
        """Acquire an existing or lazily-created connection within timeout."""

        event_loop = asyncio.get_running_loop()
        deadline = event_loop.time() + timeout
        while True:
            async with self.condition:
                self.check_accepting_work()
                if self.idle_connections:
                    connection = self.idle_connections.pop()
                    self.active_connections += 1
                    return connection
                if self.connection_count() < self.pool_size:
                    self.opening_connections += 1
                    break
                remaining_timeout = deadline - event_loop.time()
                if remaining_timeout <= 0:
                    raise PoolTimeoutError("timed out acquiring database connection")
                try:
                    _ = await asyncio.wait_for(
                        self.condition.wait(),
                        timeout=remaining_timeout,
                    )
                except TimeoutError as error:
                    raise PoolTimeoutError(
                        "timed out acquiring database connection",
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
                return opened_connection
        await close_sqlite_connection(opened_connection)
        self.check_accepting_work()
        raise DatabaseClosingError("database is closing")

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
        if should_close:
            await close_sqlite_connection(connection)

    async def close(self, timeout: float, /) -> None:
        """Close idle connections and wait for checked-out work to finish."""

        async with self.condition:
            if self.closed:
                return
            if self.closing:
                raise DatabaseClosingError("database is already closing")
            self.closing = True
            idle_connections = list(self.idle_connections)
            self.idle_connections.clear()
            self.condition.notify_all()
        await self.close_connections(idle_connections)

        event_loop = asyncio.get_running_loop()
        deadline = event_loop.time() + timeout
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
                    raise DatabaseCloseTimeoutError("database close timed out")
                try:
                    _ = await asyncio.wait_for(
                        self.condition.wait(),
                        timeout=remaining_timeout,
                    )
                except TimeoutError as error:
                    self.closing = False
                    self.condition.notify_all()
                    raise DatabaseCloseTimeoutError(
                        "database close timed out"
                    ) from error
        await self.close_connections(remaining_idle_connections)

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

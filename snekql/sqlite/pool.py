"""Internal async SQLite connection pool for Query Runtime."""

from __future__ import annotations

import logging
from collections import deque
from collections.abc import Sequence
from pathlib import Path

import anyio
from aiosqlite import Connection, Error, connect

from snekql.errors import (
    DatabaseClosedError,
    DatabaseCloseTimeoutError,
    DatabaseClosingError,
    DatabaseRuntimeError,
    PoolTimeoutError,
)
from snekql.sqlite.settings import apply_sqlite_connection_settings
from snekql.validation import NonNegativeFloat, PositiveInt

logger = logging.getLogger(__name__)


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
        await apply_sqlite_connection_settings(
            connection,
            file_backed=database_path != ":memory:",
        )
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
    condition: anyio.Condition
    database_path: str
    idle_connections: list[Connection]
    opening_connections: int
    pool_size: PositiveInt

    def __init__(
        self,
        *,
        database_path: str,
        initial_connection: Connection,
        pool_size: PositiveInt,
    ) -> None:
        self.active_connections: int = 0
        self.closed: bool = False
        self.closing: bool = False
        self.condition: anyio.Condition = anyio.Condition()
        self.database_path: str = database_path
        self.idle_connections: list[Connection] = [initial_connection]
        self.opening_connections: int = 0
        self.pool_size: PositiveInt = pool_size
        # FIFO queue of waiting-acquirer ticket numbers. A parked acquirer may
        # only claim a connection when its ticket is at the front, which stops a
        # task that just released from barging ahead of earlier waiters.
        self._waiters: deque[int] = deque()
        self._next_ticket: int = 0

    def check_accepting_work(self) -> None:
        """Reject new work when closed or temporarily closing."""

        if self.closed:
            logger.warning("sqlite database rejected work: closed")
            msg = "database is closed"
            raise DatabaseClosedError(msg)
        if self.closing:
            logger.warning("sqlite database rejected work: closing")
            msg = "database is closing"
            raise DatabaseClosingError(msg)

    async def acquire(self, acquisition_timeout: NonNegativeFloat, /) -> Connection:
        """Acquire an existing or lazily-created connection within timeout."""

        logger.debug(
            "sqlite connection acquisition started (timeout=%s)", acquisition_timeout
        )
        deadline = anyio.current_time() + acquisition_timeout
        ticket: int | None = None
        while True:
            async with self.condition:
                self.check_accepting_work()
                if self._waiter_is_served_first(ticket):
                    if self.idle_connections:
                        if ticket is not None:
                            _ = self._waiters.popleft()
                        connection = self.idle_connections.pop()
                        self.active_connections += 1
                        logger.debug("sqlite connection acquired from idle pool")
                        return connection
                    if self.connection_count() < self.pool_size:
                        if ticket is not None:
                            _ = self._waiters.popleft()
                        self.opening_connections += 1
                        break
                ticket = self._enqueue_waiter(ticket)
                await self._wait_for_release(ticket, deadline, acquisition_timeout)

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
                logger.debug("sqlite connection acquired from newly opened connection")
                return opened_connection
        await close_sqlite_connection(opened_connection)
        self.check_accepting_work()
        msg = "database is closing"
        raise DatabaseClosingError(msg)

    async def release(self, connection: Connection) -> None:
        """Return a checked-out connection or close it during shutdown."""

        with anyio.CancelScope(shield=True):
            should_close = False
            async with self.condition:
                self.active_connections -= 1
                if self.closed or self.closing:
                    should_close = True
                else:
                    self.idle_connections.append(connection)
                self.condition.notify_all()
            logger.debug("sqlite connection released (closed=%s)", should_close)
            if should_close:
                await close_sqlite_connection(connection)

    async def close(self, close_timeout: NonNegativeFloat, /) -> None:
        """Close idle connections and wait for checked-out work to finish."""

        logger.debug("sqlite database close started")
        async with self.condition:
            if self.closed:
                logger.debug("sqlite database close skipped: already closed")
                return
            if self.closing:
                msg = "database is already closing"
                raise DatabaseClosingError(msg)
            self.closing = True
            idle_connections = list(self.idle_connections)
            self.idle_connections.clear()
            self.condition.notify_all()
        await self.close_connections(idle_connections)

        deadline = anyio.current_time() + close_timeout
        while True:
            async with self.condition:
                if self.active_connections == 0 and self.opening_connections == 0:
                    remaining_idle_connections = list(self.idle_connections)
                    self.idle_connections.clear()
                    self.closed = True
                    self.closing = False
                    self.condition.notify_all()
                    break
                remaining_timeout = deadline - anyio.current_time()
                if remaining_timeout <= 0:
                    self.closing = False
                    self.condition.notify_all()
                    logger.warning("sqlite database close timed out")
                    msg = "database close timed out"
                    raise DatabaseCloseTimeoutError(msg)
                try:
                    with anyio.fail_after(remaining_timeout):
                        await self.condition.wait()
                except TimeoutError as error:
                    self.closing = False
                    self.condition.notify_all()
                    logger.warning("sqlite database close timed out")
                    msg = "database close timed out"
                    raise DatabaseCloseTimeoutError(msg) from error
        await self.close_connections(remaining_idle_connections)
        logger.debug("sqlite database close completed")

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

    def _waiter_is_served_first(self, ticket: int | None) -> bool:
        """Return whether this acquirer is allowed to claim a connection now.

        A fresh acquirer (no ticket yet) may proceed only when nobody is queued
        ahead of it; a parked acquirer may proceed only at the front of the
        queue.
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
        """Wait for a connection to free up, or time out the acquisition.

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
                    "sqlite connection acquisition timed out (timeout=%s)",
                    acquisition_timeout,
                )
                msg = "timed out acquiring database connection"
                raise PoolTimeoutError(msg) from error
            return
        self._discard_waiter(ticket)
        logger.warning(
            "sqlite connection acquisition timed out (timeout=%s)",
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

"""Internal async SQLite connection pool for Query Runtime."""

from __future__ import annotations

import logging
from collections.abc import Sequence
from pathlib import Path
from typing import NoReturn

import anyio
from aiosqlite import Connection, Error, connect

from snekql._pool_gate import FairAdmissionGate
from snekql.errors import (
    DatabaseClosedError,
    DatabaseCloseTimeoutError,
    DatabaseClosingError,
    DatabaseRuntimeError,
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
    """Bounded lazy async SQLite connection pool owned by a Database.

    Admission is bounded by the shared FIFO gate (``snekql/_pool_gate.py``):
    an acquirer first takes one of ``pool_size`` admission slots, then checks
    out an idle connection or lazily opens a new one. The gate's counter-based
    capacity check is equivalent to the structural predicate this pool used to
    evaluate (an idle connection exists, or idle + active + opening is below
    ``pool_size``): every admitted acquirer holds exactly one connection —
    idle-to-be-claimed, freshly opening, or checked out — so
    ``gate.admitted < pool_size`` holds exactly when a connection or a free
    opening slot is available.
    """

    closed: bool
    closing: bool
    database_path: str
    gate: FairAdmissionGate
    idle_connections: list[Connection]
    pool_size: PositiveInt

    def __init__(
        self,
        *,
        database_path: str,
        initial_connection: Connection,
        pool_size: PositiveInt,
    ) -> None:
        self.closed: bool = False
        self.closing: bool = False
        self.database_path: str = database_path
        self.idle_connections: list[Connection] = [initial_connection]
        self.pool_size: PositiveInt = pool_size
        self.gate: FairAdmissionGate = FairAdmissionGate(
            capacity=pool_size,
            check_accepting_work=self.check_accepting_work,
            log_label="sqlite",
        )

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
        await self.gate.admit(deadline, acquisition_timeout)
        try:
            async with self.gate.condition:
                if self.idle_connections:
                    connection = self.idle_connections.pop()
                    logger.debug("sqlite connection acquired from idle pool")
                    return connection
            opened_connection = await open_sqlite_connection(self.database_path)
            async with self.gate.condition:
                if not self.closed and not self.closing:
                    logger.debug(
                        "sqlite connection acquired from newly opened connection"
                    )
                    return opened_connection
            # Shutdown began while we were opening: discard the fresh
            # connection and reject the acquisition.
            await close_sqlite_connection(opened_connection)
            self.check_accepting_work()
            self._reject_closed_during_open()
        except BaseException:
            await self.gate.release()
            raise

    @staticmethod
    def _reject_closed_during_open() -> NoReturn:
        """Reject an acquisition whose fresh connection was closed mid-shutdown."""

        msg = "database is closing"
        raise DatabaseClosingError(msg)

    async def release(self, connection: Connection) -> None:
        """Return a checked-out connection or close it during shutdown."""

        with anyio.CancelScope(shield=True):
            should_close = False
            async with self.gate.condition:
                if self.closed or self.closing:
                    should_close = True
                else:
                    self.idle_connections.append(connection)
            # Return the connection to storage before freeing the admission
            # slot so the next FIFO waiter always finds it available.
            await self.gate.release()
            logger.debug("sqlite connection released (closed=%s)", should_close)
            if should_close:
                await close_sqlite_connection(connection)

    async def close(self, close_timeout: NonNegativeFloat, /) -> None:
        """Close idle connections and wait for checked-out work to finish."""

        logger.debug("sqlite database close started")
        async with self.gate.condition:
            if self.closed:
                logger.debug("sqlite database close skipped: already closed")
                return
            if self.closing:
                msg = "database is already closing"
                raise DatabaseClosingError(msg)
            self.closing = True
            idle_connections = list(self.idle_connections)
            self.idle_connections.clear()
            self.gate.condition.notify_all()
        await self.close_connections(idle_connections)

        deadline = anyio.current_time() + close_timeout
        while True:
            async with self.gate.condition:
                if self.gate.admitted == 0:
                    remaining_idle_connections = list(self.idle_connections)
                    self.idle_connections.clear()
                    self.closed = True
                    self.closing = False
                    self.gate.condition.notify_all()
                    break
                remaining_timeout = deadline - anyio.current_time()
                if remaining_timeout <= 0:
                    self.closing = False
                    self.gate.condition.notify_all()
                    logger.warning("sqlite database close timed out")
                    msg = "database close timed out"
                    raise DatabaseCloseTimeoutError(msg)
                try:
                    with anyio.fail_after(remaining_timeout):
                        await self.gate.condition.wait()
                except TimeoutError as error:
                    self.closing = False
                    self.gate.condition.notify_all()
                    logger.warning("sqlite database close timed out")
                    msg = "database close timed out"
                    raise DatabaseCloseTimeoutError(msg) from error
        await self.close_connections(remaining_idle_connections)
        logger.debug("sqlite database close completed")

    @staticmethod
    async def close_connections(connections: Sequence[Connection]) -> None:
        """Close a sequence of SQLite connections."""

        for connection in connections:
            await close_sqlite_connection(connection)

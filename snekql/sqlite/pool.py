"""Internal async SQLite connection pool for Query Runtime."""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import Sequence
from pathlib import Path
from typing import Literal, NoReturn

import anyio
from aiosqlite import Connection, Error, connect

from snekql._pool_gate import FairAdmissionGate
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


async def open_sqlite_connection(
    database_path: str, *, durability: Literal["normal", "full"] = "normal"
) -> Connection:
    """Open and prove an async SQLite connection without leaking partial state."""

    connection: Connection | None = None
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
            durability=durability,
        )
    except BaseException as error:
        if connection is not None:
            with anyio.CancelScope(shield=True):
                with contextlib.suppress(Exception):
                    await connection.close()
        if isinstance(error, Error):
            msg = "could not initialize SQLite connection"
            raise DatabaseRuntimeError(msg) from error
        raise
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
    discard_tasks: set[asyncio.Task[None]]

    def __init__(
        self,
        *,
        database_path: str,
        initial_connection: Connection,
        durability: Literal["normal", "full"] = "normal",
        pool_size: PositiveInt,
    ) -> None:
        self.closed: bool = False
        self.closing: bool = False
        self.database_path: str = database_path
        self.durability: Literal["normal", "full"] = durability
        self.idle_connections: list[Connection] = [initial_connection]
        self.pool_size: PositiveInt = pool_size
        self.discard_tasks: set[asyncio.Task[None]] = set()
        self._close_task: asyncio.Task[None] | None = None
        self._pending_close_connections: list[Connection] = []
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
        """Count unsuccessful checkouts without changing pool cleanup ownership."""
        logger.debug(
            "sqlite connection acquisition started (timeout=%s)", acquisition_timeout
        )
        deadline = anyio.current_time() + acquisition_timeout
        try:
            await self.gate.admit(deadline, acquisition_timeout)
            entered_checkout = False
            connection: Connection | None = None
            try:
                with self.gate.telemetry.measure("pool_checkout"):
                    entered_checkout = True
                    connection = await self._acquire(deadline)
            except BaseException:
                if connection is not None:
                    await self.discard(connection)
                elif not entered_checkout:
                    await self.gate.release()
                raise
            else:
                return connection
        except BaseException as error:
            if isinstance(error, anyio.get_cancelled_exc_class()):
                self.gate.acquisition_cancellations += 1
            else:
                self.gate.acquisition_failures += 1
            raise

    async def _acquire(self, deadline: float, /) -> Connection:
        """Acquire an existing or lazily-created connection within timeout."""

        opening: asyncio.Task[Connection] | None = None
        try:
            async with self.gate.condition:
                if self.idle_connections:
                    connection = self.idle_connections.pop()
                    logger.debug("sqlite connection acquired from idle pool")
                    return connection
            opening = asyncio.create_task(
                open_sqlite_connection(self.database_path, durability=self.durability)
            )
            with anyio.fail_after(deadline - anyio.current_time()):
                opened_connection = await asyncio.shield(opening)
                async with self.gate.condition:
                    if not self.closed and not self.closing:
                        logger.debug(
                            "sqlite connection acquired from newly opened connection"
                        )
                        return opened_connection
            self.check_accepting_work()
            self._reject_closed_during_open()
        except BaseException as error:
            if opening is None:
                await self.gate.release()
            else:
                # Opening/cleanup may be waiting on SQLite's worker thread.
                # Detach from the caller's deadline, but retain capacity until
                # the opening task and any resulting connection are closed.
                opening.cancel()
                task = asyncio.create_task(self._close_opening(opening))
                self.discard_tasks.add(task)
                task.add_done_callback(self._discard_finished)
            if isinstance(error, TimeoutError):
                logger.warning("sqlite connection acquisition timed out")
                msg = "timed out acquiring database connection"
                raise PoolTimeoutError(msg) from error
            raise

    async def _close_opening(self, opening: asyncio.Task[Connection]) -> None:
        """Reap failed opening or close a completed connection before freeing its slot."""

        try:
            connection = await opening
        except asyncio.CancelledError:
            await self.gate.release()
            return
        except Exception:
            # The opener cleans partial state before raising. This is an opening
            # failure, not a failure closing a successfully opened connection.
            logger.debug("sqlite discarded opening failed", exc_info=True)
            await self.gate.release()
            return
        await self._close_discarded(connection)

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
            if should_close:
                # Physical cleanup must outlive the returning caller and keep its
                # admission slot until complete, just like an unsafe discard.
                await self.discard(connection, count_discard=False)
            else:
                # Store the reusable connection before waking the next FIFO waiter.
                await self.gate.release()
            logger.debug("sqlite connection released (closed=%s)", should_close)

    async def discard(
        self, connection: Connection, *, count_discard: bool = True
    ) -> None:
        """Detach unsafe state immediately and close it in the background."""

        if count_discard:
            self.gate.discarded_connections += 1
        with anyio.CancelScope(shield=True):
            with contextlib.suppress(Exception):
                await connection.interrupt()
            task = asyncio.create_task(self._close_discarded(connection))
            self.discard_tasks.add(task)
            task.add_done_callback(self._discard_finished)
            logger.warning("sqlite connection discarded")

    async def _close_discarded(self, connection: Connection) -> None:
        """Close a detached connection before releasing its capacity slot."""

        try:
            await close_sqlite_connection(connection)
        except Exception:
            # Unknown physical state cannot become spare capacity. Quarantine
            # the pool before releasing the slot; shutdown retains the handle.
            async with self.gate.condition:
                self._pending_close_connections.append(connection)
                self.closing = True
                self.gate.condition.notify_all()
            raise
        finally:
            await self.gate.release()

    def _discard_finished(self, task: asyncio.Task[None]) -> None:
        """Consume detached-close failures and release the task reference."""

        self.discard_tasks.discard(task)
        try:
            task.result()
        except Exception:
            logger.exception("sqlite discarded connection close failed")

    async def close(self, close_timeout: NonNegativeFloat, /) -> None:
        """Join one owned shutdown operation without propagating caller cancellation.

        AnyIO shielding alone does not stop native Task.cancel(). Keeping the
        operation in a separate task preserves ownership of detached idle
        connections and lets later callers await the same shutdown.
        """

        if self._close_task is None or self._close_task.done():
            if self.closed:
                logger.debug("sqlite database close skipped: already closed")
                return
            self._close_task = asyncio.create_task(self._close(close_timeout))
            self._close_task.add_done_callback(self._close_finished)
        await asyncio.shield(self._close_task)

    @staticmethod
    def _close_finished(task: asyncio.Task[None]) -> None:
        """Observe failures even when all close callers have been cancelled."""

        try:
            task.result()
        except asyncio.CancelledError:
            return
        except Exception:
            logger.exception("sqlite close operation failed")

    async def _close(self, close_timeout: NonNegativeFloat) -> None:
        """Close idle connections and wait for checked-out work to finish."""

        logger.debug("sqlite database close started")
        async with self.gate.condition:
            if self.closed:
                logger.debug("sqlite database close skipped: already closed")
                return
            # The owned task serializes close attempts. A previous failed physical
            # close keeps work rejected, but a new close must retry retained handles.
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
                    break
                remaining_timeout = deadline - anyio.current_time()
                if remaining_timeout <= 0:
                    self.closing = bool(self._pending_close_connections)
                    self.gate.condition.notify_all()
                    logger.warning("sqlite database close timed out")
                    msg = "database close timed out"
                    raise DatabaseCloseTimeoutError(msg)
                try:
                    with anyio.fail_after(remaining_timeout):
                        await self.gate.condition.wait()
                except TimeoutError as error:
                    self.closing = bool(self._pending_close_connections)
                    self.gate.condition.notify_all()
                    logger.warning("sqlite database close timed out")
                    msg = "database close timed out"
                    raise DatabaseCloseTimeoutError(msg) from error
        await self.close_connections(remaining_idle_connections)
        async with self.gate.condition:
            self.closed = True
            self.closing = False
            self.gate.condition.notify_all()
        logger.debug("sqlite database close completed")

    async def close_connections(self, connections: Sequence[Connection]) -> None:
        """Attempt all idle closes and retain failed handles for a later shutdown."""

        self._pending_close_connections.extend(connections)
        first_error: Exception | None = None
        for connection in tuple(self._pending_close_connections):
            try:
                await close_sqlite_connection(connection)
            except Exception as e:
                if first_error is None:
                    first_error = e
            else:
                self._pending_close_connections.remove(connection)
        if first_error is not None:
            raise first_error

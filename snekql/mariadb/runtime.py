"""MariaDB adapter for the backend-neutral query runtime."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable, Sequence
from importlib import import_module
from re import fullmatch
from typing import TYPE_CHECKING, Any, Literal, cast

import anyio
from anyio.lowlevel import checkpoint

from snekql._migrations import MigrationPlan, MigrationResult
from snekql._pool_gate import FairAdmissionGate
from snekql._query_codec import DialectQueryCodec
from snekql._raw import NativeParameters
from snekql._schema_verification import SchemaVerificationResult
from snekql._statement_failure import StatementConstraintError
from snekql._telemetry import ParameterVisibility
from snekql.errors import (
    DatabaseClosedError,
    DatabaseCloseTimeoutError,
    DatabaseClosingError,
    DatabaseFailure,
    DatabaseRuntimeError,
    FailureCategory,
    PoolTimeoutError,
)
from snekql.mariadb.config import Config
from snekql.mariadb.migrations import (
    MariaDBMigrationBackend,
    apply_mariadb_migrations,
    build_migration_lock_name,
    validate_mariadb_migrations,
    verify_mariadb_migrations,
)
from snekql.mariadb.schema import verify_mariadb_schema
from snekql.mariadb.settings import configure_mariadb_connection
from snekql.model import Table
from snekql.storage import SchemaPolicy
from snekql.validation import NonNegativeFloat, PositiveInt

if TYPE_CHECKING:
    from snekql.runtime import CommitOutcome, IsolationLevel, TransactionMode

logger = logging.getLogger(__name__)

_ER_LOCK_DEADLOCK = 1213
"""InnoDB rolled back the transaction selected as the deadlock victim."""

_SERVER_STATUS_IN_TRANS_READONLY = 0x2000
"""MariaDB protocol flag for the active transaction, not its session default."""


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
    def columns(self) -> tuple[str, ...] | None:
        description = cast(
            "tuple[tuple[str, object, object, object, object, object, object], ...] | None",
            cast("Any", self.cursor).description,
        )
        return (
            None if description is None else tuple(column[0] for column in description)
        )

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

    async def complete(self) -> bool:
        """Finish only the first result; never load the next to detect it.

        aiomysql cursor.close calls nextset and can buffer subsequent results.
        Its private result status is the adapter's isolated protocol boundary.
        Finishing an unbuffered first result makes its trailing status visible.
        """

        cursor = cast("Any", self.cursor)
        result = cursor._result  # noqa: SLF001
        if result is not None:
            if result.unbuffered_active:
                await result._finish_unbuffered_query()  # noqa: SLF001
            if result.has_next:
                cursor._connection.close()  # noqa: SLF001
                cursor._connection = None  # noqa: SLF001
                return True
        await self.close()
        return False

    async def close(self) -> None:
        close_result = cast("Any", self.cursor).close()
        if close_result is not None:
            _ = await close_result


class MariaDBConnectionAdapter:
    """Runtime connection adapter backed by an aiomysql connection."""

    def __init__(self, connection: object) -> None:
        self.connection: object = connection
        self.commit_outcome: CommitOutcome = "not_attempted"

    async def begin(
        self,
        mode: TransactionMode = "deferred",
        *,
        read_only: bool | None = None,
        isolation: IsolationLevel | None = None,
    ) -> None:
        # InnoDB serializes writers with row-level locks rather than one global
        # writer lock, so there is no eager writer-lock acquisition to request:
        # ``immediate`` and ``deferred`` both open an ordinary transaction. The
        # parameter exists to satisfy the backend-neutral ``RuntimeConnection``
        # seam (and is a no-op here).
        del mode
        if isolation is not None:
            isolation_sql = {
                "read_uncommitted": "READ UNCOMMITTED",
                "read_committed": "READ COMMITTED",
                "repeatable_read": "REPEATABLE READ",
                "serializable": "SERIALIZABLE",
            }[isolation]
            cursor = await self.execute(
                f"SET TRANSACTION ISOLATION LEVEL {isolation_sql}", ()
            )
            await cursor.close()
        if read_only is not None:
            cursor = await self.execute(
                "SET TRANSACTION READ ONLY"
                if read_only
                else "SET TRANSACTION READ WRITE",
                (),
            )
            await cursor.close()
        await cast("Any", self.connection).begin()

    def is_read_only(self) -> bool:
        """Use server status so inherited and next-transaction overrides both count."""
        return bool(
            cast("Any", self.connection).server_status
            & _SERVER_STATUS_IN_TRANS_READONLY
        )

    async def commit(self) -> None:
        self.commit_outcome = "unknown"
        try:
            await cast("Any", self.connection).commit()
        except _import_aiomysql().Error as e:
            # InnoDB's deadlock response means the transaction was rolled back.
            # Other error packets, including generic serialization states, do not
            # establish the outcome of COMMIT.
            if e.args and e.args[0] == _ER_LOCK_DEADLOCK:
                self.commit_outcome = "rejected"
            raise
        self.commit_outcome = "committed"

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

    async def execute_raw(
        self,
        sql: str,
        params: NativeParameters,
        *,
        stream: bool = False,
    ) -> MariaDBCursorAdapter:
        """Use native binding without forwarding server warning text."""

        driver = _import_aiomysql()
        base = driver.SSCursor if stream else driver.Cursor

        class RawCursor(base):
            async def _show_warnings(self, connection: object) -> None:
                # aiomysql's default implementation emits server text and runs
                # SHOW WARNINGS, which also interferes with result completion.
                del connection

        cursor = await cast("Any", self.connection).cursor(RawCursor)
        try:
            if params is None:
                await cursor.execute(sql)
            else:
                await cursor.execute(sql, params)
        except BaseException as e:
            if isinstance(e, Exception) and self._recoverable_constraint(e):
                await cursor.close()
                raise StatementConstraintError(e) from e
            # Do not ask cursor.close to consume unknown additional results.
            cast("Any", self.connection).close()
            raise
        return MariaDBCursorAdapter(cursor)

    def _recoverable_constraint(self, error: BaseException) -> bool:
        """Only completed, recognized constraint packets are candidates for rollback.

        The allowed server codes cover NULL, duplicate key, foreign-key delete/
        insert, and CHECK violations. Deadlocks and lock timeouts are excluded.
        """
        driver = _import_aiomysql()
        return bool(
            isinstance(error, (driver.IntegrityError, driver.OperationalError))
            and bool(error.args)
            and error.args[0] in {1048, 1062, 1451, 1452, 4025}
            and bool(cast("Any", self.connection).get_transaction_status())
        )

    async def _run_on_cursor(
        self,
        cursor: Any,
        sql: str,
        params: tuple[object, ...],
    ) -> MariaDBCursorAdapter:
        try:
            _ = await cursor.execute(sql, params)
        except Exception as e:
            close_result = cursor.close()
            if close_result is not None:
                _ = await close_result
            if self._recoverable_constraint(e):
                raise StatementConstraintError(e) from e
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
        health_check: Literal["passive", "checkout"] = "passive",
        max_connection_idle: float | None = None,
        max_connection_lifetime: float | None = None,
    ) -> None:
        self.closed: bool = False
        self.closing: bool = False
        self._close_task: asyncio.Task[None] | None = None
        self.pool: object = pool
        self.health_check: Literal["passive", "checkout"] = health_check
        self.max_connection_idle: float | None = max_connection_idle
        self.max_connection_lifetime: float | None = max_connection_lifetime
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
            with anyio.fail_after(deadline - anyio.current_time()):
                await self._ensure_configured(connection)
        except BaseException as error:
            # Configuration discards the physical connection on failure, then
            # this releases admission capacity. Checkout and configuration use
            # the same deadline rather than granting configuration a new budget.
            await self.gate.release()
            if isinstance(error, TimeoutError):
                logger.warning("mariadb connection configuration timed out")
                msg = "timed out acquiring database connection"
                raise PoolTimeoutError(msg) from error
            raise
        try:
            self.check_accepting_work()
        except BaseException:
            await self.discard(connection)
            raise
        logger.debug("mariadb connection acquired")
        return connection

    async def _checkout(
        self,
        deadline: float,
        acquisition_timeout: NonNegativeFloat,
    ) -> object:
        """Check a connection out of the underlying aiomysql pool.

        Recycling, physical replacement, and an optional health probe share the
        caller's remaining acquisition budget. No Transaction has begun here.
        """

        try:
            pool = cast("Any", self.pool)
            acquire = cast("Callable[[], Awaitable[object]]", pool.acquire)
            remaining = deadline - anyio.current_time()
            with anyio.fail_after(remaining):
                while True:
                    connection = await acquire()
                    # aiomysql's connected_time uses the event loop clock. Its
                    # last_usage instead tracks cursor creation, not idle time.
                    driver_connection = cast("Any", connection)
                    now = asyncio.get_running_loop().time()
                    returned_at = getattr(connection, "_snekql_returned_at", None)
                    lifetime_expired = (
                        self.max_connection_lifetime is not None
                        and now - driver_connection.connected_time
                        >= self.max_connection_lifetime
                    )
                    idle_expired = (
                        self.max_connection_idle is not None
                        and returned_at is not None
                        and now - returned_at >= self.max_connection_idle
                    )
                    if lifetime_expired or idle_expired:
                        driver_connection.close()
                        _ = pool.release(connection)
                        await checkpoint()
                        continue
                    if self.health_check == "checkout":
                        try:
                            # Reconnection on this object would retain the old
                            # session-configuration marker for a new server session.
                            await driver_connection.ping(reconnect=False)
                        except BaseException:
                            driver_connection.close()
                            _ = pool.release(connection)
                            raise
                    return connection
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
        except BaseException:
            cast("Any", connection).close()
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
            if self.max_connection_idle is not None:
                returned_at = asyncio.get_running_loop().time()
                cast("Any", connection)._snekql_returned_at = returned_at  # noqa: SLF001
            release = cast("Any", self.pool).release
            _ = release(connection)
            await self.gate.release()
            logger.debug("mariadb connection released")
        await checkpoint()

    async def discard(self, connection: object) -> None:
        """Physically close a connection whose lock ownership is uncertain."""

        with anyio.CancelScope(shield=True):
            cast("Any", connection).close()
            release = cast("Any", self.pool).release
            _ = release(connection)
            await self.gate.release()
            logger.warning("mariadb connection discarded")
        await checkpoint()

    async def close(self, close_timeout: NonNegativeFloat) -> None:
        """Join owned shutdown without passing caller cancellation to cleanup."""

        if self._close_task is None or self._close_task.done():
            if self.closed:
                return
            self._close_task = asyncio.create_task(self._close(close_timeout))
            self._close_task.add_done_callback(self._close_finished)
        await asyncio.shield(self._close_task)

    @staticmethod
    def _close_finished(task: asyncio.Task[None]) -> None:
        """Observe failure even if all shutdown waiters have cancelled."""

        try:
            task.result()
        except asyncio.CancelledError:
            return
        except Exception:
            logger.error("mariadb shutdown failed")  # noqa: TRY400 - omit driver secrets

    async def _close(self, close_timeout: NonNegativeFloat) -> None:
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
                # Driver release does not notify wait_closed for an already
                # closed socket. Our gate tracks those returns and in-flight opens.
                async with self.gate.condition:
                    while self.gate.admitted:
                        await self.gate.condition.wait()
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
        operation_timeout: NonNegativeFloat = 30.0,
        connection_pool: MariaDBConnectionPool,
        migration_lock_name: str,
        parameter_visibility: ParameterVisibility = "redacted",
    ) -> None:
        self.acquire_timeout: NonNegativeFloat = acquire_timeout
        self.operation_timeout: NonNegativeFloat = operation_timeout
        self.parameter_visibility: ParameterVisibility = parameter_visibility
        self.connection_pool: MariaDBConnectionPool = connection_pool
        self.migration_lock_name: str = migration_lock_name
        self.query_codec: DialectQueryCodec = DialectQueryCodec.for_backend("mariadb")

    @staticmethod
    def classify_failure(error: Exception) -> DatabaseFailure | None:
        """Keep structured native fields without parsing potentially sensitive messages."""
        if not isinstance(error, _import_aiomysql().Error):
            return None
        code = error.args[0] if error.args else None
        code = code if type(code) is int else None
        sqlstate = getattr(error, "sqlstate", None)
        categories: dict[int, FailureCategory] = {
            1062: "unique_violation",
            1048: "not_null_violation",
            1451: "foreign_key_violation",
            1452: "foreign_key_violation",
            4025: "check_violation",
            1205: "lock_conflict",
            _ER_LOCK_DEADLOCK: "deadlock",
            1927: "connection_loss",
            2006: "connection_loss",
            2013: "connection_loss",
            2055: "connection_loss",
        }
        category = categories.get(code, "unknown") if code is not None else "unknown"
        if category == "unknown" and isinstance(sqlstate, str):
            if sqlstate == "40001":
                category = "serialization_conflict"
            elif fullmatch(r"08[A-Z0-9]{3}", sqlstate):
                category = "connection_loss"
        constraint = getattr(error, "constraint_name", None)
        return DatabaseFailure(
            backend="mariadb",
            category=category,
            code=code,
            sqlstate=sqlstate if isinstance(sqlstate, str) else None,
            constraint=constraint if isinstance(constraint, str) else None,
        )

    async def acquire(
        self,
        acquisition_timeout: NonNegativeFloat,
    ) -> MariaDBConnectionAdapter:
        connection = await self.connection_pool.acquire(acquisition_timeout)
        return MariaDBConnectionAdapter(connection)

    async def apply_migrations(
        self,
        migrations: MigrationPlan,
        *,
        adopt_legacy: bool = False,
    ) -> MigrationResult:
        """Apply pending migrations on a pooled connection under the lock (ADR 0007)."""

        connection = await self.connection_pool.acquire(self.acquire_timeout)
        backend = MariaDBMigrationBackend(
            connection,
            lock_name=self.migration_lock_name,
            lock_timeout=self.acquire_timeout,
        )
        try:
            return await apply_mariadb_migrations(
                backend,
                migrations,
                adopt_legacy=adopt_legacy,
            )
        finally:
            if backend.connection_reusable:
                await self.connection_pool.release(connection)
            else:
                await self.connection_pool.discard(connection)

    async def verify_migrations(self, migrations: MigrationPlan) -> None:
        """Verify Migration History without changing it."""

        connection = await self.connection_pool.acquire(self.acquire_timeout)
        try:
            await verify_mariadb_migrations(connection, migrations)
        finally:
            await self.connection_pool.release(connection)

    async def verify_schema(
        self,
        models: Sequence[type[Table[Any]]],
        schema_policy: SchemaPolicy,
    ) -> SchemaVerificationResult:
        """Verify the live schema against models on a pooled connection."""

        connection = await self.connection_pool.acquire(self.acquire_timeout)
        try:
            return await verify_mariadb_schema(connection, models, schema_policy)
        finally:
            await self.connection_pool.release(connection)

    async def release(self, connection: object) -> None:
        if not isinstance(connection, MariaDBConnectionAdapter):
            msg = "MariaDB runtime cannot release a foreign connection"
            raise DatabaseRuntimeError(msg)
        with anyio.CancelScope(shield=True):
            await self.connection_pool.release(connection.connection)

    async def discard(self, connection: object) -> None:
        """Physically close a connection whose driver state is uncertain."""

        if not isinstance(connection, MariaDBConnectionAdapter):
            msg = "MariaDB runtime cannot discard a foreign connection"
            raise DatabaseRuntimeError(msg)
        with anyio.CancelScope(shield=True):
            await self.connection_pool.discard(connection.connection)

    async def close(self, close_timeout: NonNegativeFloat) -> None:
        try:
            with anyio.CancelScope(shield=True):
                await self.connection_pool.close(close_timeout)
        except _import_aiomysql().Error as e:
            msg = "could not close MariaDB database"
            raise DatabaseRuntimeError(msg, failure=self.classify_failure(e)) from e

    def check_accepting_work(self) -> None:
        self.connection_pool.check_accepting_work()

    def validate_migrations(self, migrations: MigrationPlan) -> None:
        """Reject bodies that can escape the owned transaction or lock."""

        validate_mariadb_migrations(migrations)


async def _close_partial_pool(
    pool: object,
    close_timeout: NonNegativeFloat,
) -> None:
    """Bound cleanup of a pool that cannot be returned from initialization."""

    driver_pool = cast("Any", pool)
    driver_pool.close()
    wait_closed = cast("Callable[[], Awaitable[None]]", driver_pool.wait_closed)
    with anyio.move_on_after(close_timeout, shield=True) as cancel_scope:
        await wait_closed()
    if cancel_scope.cancel_called:
        logger.error("mariadb partial pool cleanup timed out")


async def initialize_runtime(config: Config) -> MariaDBRuntime:
    """Open MariaDB connectivity and a connection pool; do no schema work.

    Initialization is connect-only (ADR 0007): it opens the pool, proves it can
    acquire and configure a connection, and returns a live runtime. Migrations
    and verification are explicit verbs on the Database.
    """

    _import_aiomysql()
    logger.debug("mariadb pool opening: %s:%s", config.host, config.port)
    create_pool = import_module("snekql.mariadb._pool").create_pool
    pool = await create_pool(
        require_tls=config.tls is not None,
        autocommit=False,
        charset=config.charset,
        connect_timeout=config.acquire_timeout,
        db=config.database,
        host=config.host,
        maxsize=config.pool_size,
        minsize=1,
        password=config.password,
        port=config.port,
        ssl=(
            config.tls._create_ssl_context()  # noqa: SLF001
            if config.tls is not None
            else None
        ),
        unix_socket=str(config.unix_socket) if config.unix_socket is not None else None,
        user=config.user,
    )
    connection_pool = MariaDBConnectionPool(
        pool,
        pool_size=config.pool_size,
        health_check=config.health_check,
        max_connection_idle=config.max_connection_idle,
        max_connection_lifetime=config.max_connection_lifetime,
    )
    try:
        # Prove connectivity (and apply session settings once) before returning.
        connection = await connection_pool.acquire(config.acquire_timeout)
        await connection_pool.release(connection)
    except BaseException:
        try:
            await _close_partial_pool(pool, config.operation_timeout)
        except Exception:
            logger.error("mariadb partial pool cleanup failed")  # noqa: TRY400 - omit driver secrets
        raise
    return MariaDBRuntime(
        acquire_timeout=config.acquire_timeout,
        operation_timeout=config.operation_timeout,
        connection_pool=connection_pool,
        migration_lock_name=build_migration_lock_name(config.database),
        parameter_visibility=config.parameter_visibility,
    )


__all__ = [
    "MariaDBConnectionAdapter",
    "MariaDBConnectionPool",
    "MariaDBCursorAdapter",
    "MariaDBRuntime",
    "initialize_runtime",
]

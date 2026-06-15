"""Runtime async-safety and lifecycle regression tests."""

from __future__ import annotations

from collections.abc import Sequence

import anyio
import anyio.lowlevel
from snektest import assert_eq, assert_raises, test

from snekql import (
    MISSING,
    Database,
    DatabaseCloseTimeoutError,
    DatabaseClosingError,
    Fetched,
    Integer,
    Model,
    Pending,
    Text,
    Transaction,
    insert,
    select,
)
from snekql.mariadb.runtime import MariaDBConnectionPool
from snekql.model import BackendFamily
from snekql.query import AnySelectQuery
from snekql.runtime import RuntimeConnection
from snekql.structured_logging import ResolvedStructuredLogger
from snekql.validation import NonNegativeFloat
from tests.helpers import NULL_LOGGER


class _AsyncUser[S = Pending](Model[S, "_AsyncUser[Fetched]"]):
    """Table model used by async lifecycle tests."""

    id: _AsyncUser.GenCol[int] = Integer(
        primary_key=True,
        auto_increment=True,
        default=MISSING,
    )
    email: _AsyncUser.Col[str] = Text(nullable=False)


class _FakeCursor:
    """Minimal runtime cursor for fake transaction connections."""

    async def fetchone(self) -> Sequence[object] | None:
        return None

    async def fetchall(self) -> Sequence[Sequence[object]]:
        return []

    async def close(self) -> None:
        return None


class _SlowExecuteConnection:
    """Connection fake that exposes whether commit races an active query."""

    def __init__(self) -> None:
        self.allow_execute_finish: anyio.Event = anyio.Event()
        self.commit_called: bool = False
        self.execute_started: anyio.Event = anyio.Event()

    async def begin(self) -> None:
        return None

    async def commit(self) -> None:
        self.commit_called = True

    async def rollback(self) -> None:
        return None

    async def execute(self, sql: str, params: tuple[object, ...]) -> _FakeCursor:
        _ = sql
        _ = params
        self.execute_started.set()
        await self.allow_execute_finish.wait()
        return _FakeCursor()


class _ReleaseBlockingConnection:
    """Connection fake used to cancel transaction cleanup during release."""

    async def begin(self) -> None:
        return None

    async def commit(self) -> None:
        return None

    async def rollback(self) -> None:
        return None

    async def execute(self, sql: str, params: tuple[object, ...]) -> _FakeCursor:
        _ = sql
        _ = params
        return _FakeCursor()


class _FakeRuntime:
    """Runtime fake with just enough behavior for Transaction lifecycle tests."""

    backend_family: BackendFamily = "sqlite"

    def __init__(self, connection: RuntimeConnection) -> None:
        self.acquire_timeout: NonNegativeFloat = 1.0
        self.connection: RuntimeConnection = connection
        self.logger: ResolvedStructuredLogger = NULL_LOGGER
        self.release_allowed: anyio.Event = anyio.Event()
        self.release_started: anyio.Event = anyio.Event()
        self.released: bool = False

    async def acquire(
        self,
        acquisition_timeout: NonNegativeFloat,
    ) -> RuntimeConnection:
        _ = acquisition_timeout
        return self.connection

    async def release(self, connection: object) -> None:
        _ = connection
        self.release_started.set()
        await self.release_allowed.wait()
        self.released = True

    async def close(self, close_timeout: NonNegativeFloat) -> None:
        _ = close_timeout

    def check_accepting_work(self) -> None:
        return None

    def compile_select_sql(
        self,
        query: AnySelectQuery,
    ) -> tuple[str, tuple[object, ...]]:
        _ = query
        return "SELECT 1", ()

    def compile_write_sql(self, query: object) -> tuple[str, tuple[object, ...]]:
        _ = query
        return "INSERT INTO async_user VALUES (?)", ("alice@example.com",)

    def materialize_select_row(
        self,
        query: AnySelectQuery,
        row: Sequence[object],
        *,
        validate: bool = True,
    ) -> object:
        _ = query
        _ = row
        _ = validate
        return object()

    def materialize_write_rows(
        self,
        query: object,
        rows: Sequence[Sequence[object]],
        *,
        validate: bool = True,
    ) -> list[object]:
        _ = query
        _ = rows
        _ = validate
        return []


class _NeverClosingPool:
    """aiomysql-like pool fake whose close wait times out."""

    def __init__(self) -> None:
        self.close_called: bool = False

    async def acquire(self) -> object:
        return object()

    def close(self) -> None:
        self.close_called = True

    def release(self, connection: object) -> None:
        _ = connection

    async def wait_closed(self) -> None:
        await anyio.sleep_forever()


@test(mark="medium")
async def sqlite_memory_database_serializes_concurrent_work_on_one_connection() -> None:
    """Exact ':memory:' databases do not lazily open independent schemas."""

    database = await Database.initialize(
        logger=NULL_LOGGER,
        database=":memory:",
        models=[_AsyncUser],
        pool_size=5,
    )
    try:
        async with (
            anyio.create_task_group() as task_group,
            database.transaction() as tx,
        ):
            await tx.execute(insert(_AsyncUser(email="held@example.com")))
            task_group.start_soon(_insert_async_user, database, "second@example.com")
            await anyio.lowlevel.checkpoint()

        async with database.transaction() as tx:
            emails = await tx.fetch_all(select(_AsyncUser.email).all())
    finally:
        await database.close()

    assert_eq(sorted(emails), ["held@example.com", "second@example.com"])


@test(mark="fast")
async def shared_transaction_close_waits_for_active_query() -> None:
    """A shared Transaction serializes close behind in-flight query execution."""

    connection = _SlowExecuteConnection()
    runtime = _FakeRuntime(connection)
    transaction = Transaction(runtime=runtime, timeout=1.0)
    _ = await transaction.__aenter__()

    async with anyio.create_task_group() as task_group:
        task_group.start_soon(
            transaction.execute,
            insert(_AsyncUser(email="alice@example.com")),
        )
        await connection.execute_started.wait()
        task_group.start_soon(transaction.__aexit__, None, None, None)
        await anyio.lowlevel.checkpoint()

        assert_eq(connection.commit_called, False)
        connection.allow_execute_finish.set()
        runtime.release_allowed.set()

    assert_eq(connection.commit_called, True)


@test(mark="fast")
async def transaction_cleanup_release_is_shielded_from_cancellation() -> None:
    """Cancellation during Transaction.__aexit__ does not skip connection release."""

    runtime = _FakeRuntime(_ReleaseBlockingConnection())
    transaction = Transaction(runtime=runtime, timeout=1.0)
    _ = await transaction.__aenter__()
    close_finished = anyio.Event()
    close_scope: anyio.CancelScope | None = None

    async def close_transaction() -> None:
        nonlocal close_scope
        with anyio.CancelScope() as cancel_scope:
            close_scope = cancel_scope
            await transaction.__aexit__(None, None, None)
        close_finished.set()

    async with anyio.create_task_group() as task_group:
        task_group.start_soon(close_transaction)
        await runtime.release_started.wait()
        assert close_scope is not None
        close_scope.cancel()
        await anyio.lowlevel.checkpoint()

        assert_eq(close_finished.is_set(), False)
        assert_eq(runtime.released, False)
        runtime.release_allowed.set()
        await close_finished.wait()

    assert_eq(runtime.released, True)


@test(mark="fast")
async def mariadb_close_timeout_keeps_pool_rejecting_new_work() -> None:
    """A timed-out MariaDB close cannot re-admit work after pool.close()."""

    pool = MariaDBConnectionPool(_NeverClosingPool(), logger=NULL_LOGGER)

    with assert_raises(DatabaseCloseTimeoutError):
        await pool.close(0.0)

    with assert_raises(DatabaseClosingError):
        pool.check_accepting_work()


async def _insert_async_user(database: Database, email: str) -> None:
    async with database.transaction(timeout=1.0) as tx:
        await tx.execute(insert(_AsyncUser(email=email)))

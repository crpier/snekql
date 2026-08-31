"""Unit tests for the MariaDB migration advisory lock seam (no server needed).

These exercise the lock-name namespacing and the `GET_LOCK` result handling over
a fake aiomysql-shaped connection, so they run without the shared MariaDB server.
"""

from __future__ import annotations

import anyio
from snektest import assert_eq, assert_raises, assert_true, test

from snekql.errors import MigrationLockError, MigrationLockTimeoutError
from snekql.mariadb.migrations import (
    MariaDBMigrationBackend,
    build_migration_lock_name,
)


class _FakeCursor:
    """Records executed SQL and replays a scripted single-row result."""

    def __init__(self, connection: _FakeLockConnection) -> None:
        self.connection: _FakeLockConnection = connection

    async def execute(self, sql: str, params: tuple[object, ...] = ()) -> None:
        self.connection.executed.append((sql, params))

    async def fetchone(self) -> tuple[object, ...] | None:
        releasing = bool(
            self.connection.executed
            and "RELEASE_LOCK" in self.connection.executed[-1][0]
        )
        if self.connection.fail_at == ("release" if releasing else "acquire"):
            msg = "driver lock failure"
            raise RuntimeError(msg)
        return self.connection.current_result

    async def close(self) -> None:
        return None


class _FakeLockConnection:
    """Minimal aiomysql-shaped connection answering only the lock seam."""

    def __init__(
        self,
        lock_result: tuple[object, ...] | None,
        *,
        fail_at: str | None = None,
        release_results: tuple[tuple[object, ...] | None, ...] = ((1,), (0,)),
    ) -> None:
        self.fail_at: str | None = fail_at
        self.lock_result: tuple[object, ...] | None = lock_result
        self.release_results: tuple[tuple[object, ...] | None, ...] = release_results
        self.executed: list[tuple[str, tuple[object, ...]]] = []

    @property
    def current_result(self) -> tuple[object, ...] | None:
        if self.executed and "RELEASE_LOCK" in self.executed[-1][0]:
            release_count = sum("RELEASE_LOCK" in sql for sql, _ in self.executed)
            index = min(release_count - 1, len(self.release_results) - 1)
            return self.release_results[index]
        return self.lock_result

    async def cursor(self) -> _FakeCursor:
        return _FakeCursor(self)


class _BlockingCursor(_FakeCursor):
    """Blocks one configured lock result so cancellation behavior is observable."""

    async def fetchone(self) -> tuple[object, ...] | None:
        connection = self.connection
        if isinstance(connection, _BlockingLockConnection):
            releasing = bool(
                connection.executed and "RELEASE_LOCK" in connection.executed[-1][0]
            )
            if (releasing and connection.block_release) or (
                not releasing and connection.block_acquire
            ):
                connection.operation_started.set()
                await connection.allow_operation.wait()
        return await super().fetchone()


class _BlockingLockConnection(_FakeLockConnection):
    """Fake connection with cancellable acquisition or release result reads."""

    def __init__(
        self, *, block_acquire: bool = False, block_release: bool = False
    ) -> None:
        super().__init__(lock_result=(1,))
        self.allow_operation = anyio.Event()
        self.block_acquire: bool = block_acquire
        self.block_release: bool = block_release
        self.operation_started = anyio.Event()

    async def cursor(self) -> _BlockingCursor:
        return _BlockingCursor(self)


def _backend(connection: _FakeLockConnection) -> MariaDBMigrationBackend:
    return MariaDBMigrationBackend(
        connection, lock_name="snekql_migrations.app", lock_timeout=5.0
    )


@test(mark="fast")
def short_database_name_keeps_a_readable_lock_name() -> None:
    """A short database name produces the human-readable namespaced lock name."""

    assert_eq(build_migration_lock_name("app"), "snekql_migrations.app")


@test(mark="fast")
def long_database_name_folds_into_a_bounded_digest() -> None:
    """A long database name folds to a stable digest within the 64-char cap."""

    name = build_migration_lock_name("d" * 80)
    assert_true(len(name) <= 64)
    assert_eq(name, build_migration_lock_name("d" * 80))
    assert_true(name.startswith("snekql_migrations."))


@test(mark="fast")
async def acquired_lock_is_released_on_exit() -> None:
    """A granted lock runs the body and releases on a clean exit."""

    connection = _FakeLockConnection(lock_result=(1,))

    async with _backend(connection).migration_lock():
        pass

    executed_sql = [sql for sql, _ in connection.executed]
    assert_true(any("GET_LOCK" in sql for sql in executed_sql))
    assert_true(any("RELEASE_LOCK" in sql for sql in executed_sql))


@test(mark="fast")
async def lock_timeout_surfaces_as_migration_lock_timeout_error() -> None:
    """A `GET_LOCK` timeout (0) surfaces as MigrationLockTimeoutError, no release."""

    connection = _FakeLockConnection(lock_result=(0,))

    with assert_raises(MigrationLockTimeoutError):
        async with _backend(connection).migration_lock():
            pass

    executed_sql = [sql for sql, _ in connection.executed]
    assert_true(all("RELEASE_LOCK" not in sql for sql in executed_sql))


@test(mark="fast")
async def unconfirmed_release_marks_the_connection_unsafe() -> None:
    """A non-success release result raises a lock error and forbids pool reuse."""

    connection = _FakeLockConnection(lock_result=(1,), release_results=((0,),))
    backend = _backend(connection)

    with assert_raises(MigrationLockError):
        async with backend.migration_lock():
            pass

    assert_true(not backend.connection_reusable)


@test(mark="fast")
async def lock_driver_failures_use_the_public_error_and_forbid_reuse() -> None:
    """Driver errors never escape the Migration lock-error boundary."""

    acquire_connection = _FakeLockConnection(
        lock_result=(1,),
        fail_at="acquire",
    )
    acquire_backend = _backend(acquire_connection)
    with assert_raises(MigrationLockError):
        async with acquire_backend.migration_lock():
            pass
    assert_true(not acquire_backend.connection_reusable)

    release_connection = _FakeLockConnection(
        lock_result=(1,),
        fail_at="release",
    )
    release_backend = _backend(release_connection)
    with assert_raises(MigrationLockError):
        async with release_backend.migration_lock():
            pass
    assert_true(not release_backend.connection_reusable)


@test(mark="fast")
async def recursive_lock_ownership_is_fully_released() -> None:
    """Every recursive reference is released before the connection is reusable."""

    connection = _FakeLockConnection(
        lock_result=(1,),
        release_results=((1,), (1,), (0,)),
    )
    backend = _backend(connection)

    async with backend.migration_lock():
        pass

    release_count = sum("RELEASE_LOCK" in sql for sql, _ in connection.executed)
    assert_eq(release_count, 3)
    assert_true(backend.connection_reusable)


@test(mark="fast")
async def cancelled_lock_acquisition_keeps_the_connection_unsafe() -> None:
    """Cancellation can leave `GET_LOCK` ownership ambiguous, forcing discard."""

    connection = _BlockingLockConnection(block_acquire=True)
    backend = _backend(connection)
    cancel_scope = anyio.CancelScope()
    operation_finished = anyio.Event()

    async def acquire_lock() -> None:
        with cancel_scope:
            async with backend.migration_lock():
                pass
        operation_finished.set()

    async with anyio.create_task_group() as task_group:
        task_group.start_soon(acquire_lock)
        await connection.operation_started.wait()
        cancel_scope.cancel()
        await operation_finished.wait()

    assert_true(not backend.connection_reusable)


@test(mark="fast")
async def lock_release_finishes_under_cancellation_shield() -> None:
    """Cancellation waits for a confirmed release before allowing pool reuse."""

    connection = _BlockingLockConnection(block_release=True)
    backend = _backend(connection)
    cancel_scope = anyio.CancelScope()
    operation_finished = anyio.Event()

    async def acquire_and_cancel() -> None:
        with cancel_scope:
            async with backend.migration_lock():
                cancel_scope.cancel()
        operation_finished.set()

    async with anyio.create_task_group() as task_group:
        task_group.start_soon(acquire_and_cancel)
        await connection.operation_started.wait()
        assert_true(not operation_finished.is_set())
        connection.allow_operation.set()
        await operation_finished.wait()

    assert_true(backend.connection_reusable)

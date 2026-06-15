"""Unit tests for the MariaDB migration advisory lock seam (no server needed).

These exercise the lock-name namespacing and the `GET_LOCK` result handling over
a fake aiomysql-shaped connection, so they run without the shared MariaDB server.
"""

from __future__ import annotations

from snektest import assert_eq, assert_raises, assert_true, test

from snekql.errors import MigrationLockTimeoutError
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
        return self.connection.lock_result

    async def close(self) -> None:
        return None


class _FakeLockConnection:
    """Minimal aiomysql-shaped connection answering only the lock seam."""

    def __init__(self, lock_result: tuple[object, ...] | None) -> None:
        self.lock_result: tuple[object, ...] | None = lock_result
        self.executed: list[tuple[str, tuple[object, ...]]] = []

    async def cursor(self) -> _FakeCursor:
        return _FakeCursor(self)


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

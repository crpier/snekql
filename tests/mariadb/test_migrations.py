"""MariaDB imperative migrate/verify, history recording, and idempotent re-run tests.

The MariaDB server fixture is shared across the session, so each test uses
globally-unique migration names and table names and asserts only its own
Migration History rows, never the full set.
"""

from __future__ import annotations

import anyio
from snektest import (
    AsyncFixture,
    assert_eq,
    assert_raises,
    assert_true,
    load_fixture,
    test,
)

from snekql import mariadb
from snekql.mariadb import (
    PENDING_GENERATION,
    Database,
    Fetched,
    MigrationError,
    Pending,
)
from snekql.testing.mariadb import TemporaryMariaDBServer
from tests.helpers import provide_mariadb_server


def _create_user_table_sql(table_name: str) -> str:
    return (
        f"CREATE TABLE `{table_name}` ("
        "`id` BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY, "
        "`email` VARCHAR(255) CHARACTER SET utf8mb4 COLLATE utf8mb4_bin NOT NULL"
        ") ENGINE=InnoDB"
    )


async def _fetch_applied_names(server: TemporaryMariaDBServer) -> list[str]:
    result = await server.run_sql("SELECT name FROM snekql_migrations")
    lines = [line for line in result.stdout.splitlines() if line]
    return lines[1:]


async def _table_exists(server: TemporaryMariaDBServer, table_name: str) -> bool:
    sql = (
        "SELECT TABLE_NAME FROM INFORMATION_SCHEMA.TABLES"
        " WHERE TABLE_SCHEMA = DATABASE()"
        f" AND TABLE_NAME = '{table_name}'"
    )
    result = await server.run_sql(sql)
    lines = [line for line in result.stdout.splitlines() if line]
    return table_name in lines[1:]


async def mariadb_server() -> AsyncFixture[TemporaryMariaDBServer]:
    """Provide the shared local MariaDB server for migration tests."""

    server = await load_fixture(provide_mariadb_server())
    yield server


@test(mark="medium")
async def migrate_creates_table_and_records_history() -> None:
    """A migration body runs against MariaDB and its name is recorded in history."""

    server = await load_fixture(mariadb_server())
    database = await Database.initialize(server.config())
    await database.migrate(
        {"mig_create_users": _create_user_table_sql("mig_users_t1")},
    )
    await database.close()

    assert_true("mig_create_users" in await _fetch_applied_names(server))


@test(mark="medium")
async def re_migrating_does_not_reapply_recorded_migration() -> None:
    """Re-running an already-applied migration records it exactly once."""

    create_audit = (
        "CREATE TABLE `mig_audit_t2` ("
        "`id` BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY"
        ") ENGINE=InnoDB"
    )
    migrations = {"mig_audit_idem": create_audit}
    server = await load_fixture(mariadb_server())

    database = await Database.initialize(server.config())
    await database.migrate(migrations)
    await database.migrate(migrations)
    await database.close()

    applied = await _fetch_applied_names(server)
    assert_eq(applied.count("mig_audit_idem"), 1)


@test(mark="medium")
async def concurrent_migrate_applies_each_migration_once() -> None:
    """Two instances migrating concurrently apply a non-idempotent body once.

    The create-table body is not idempotent: absent the migration advisory lock,
    the loser would re-run it and raise a duplicate-table error. The lock makes
    the loser wait, observe the recorded history, and apply nothing.
    """

    server = await load_fixture(mariadb_server())
    migrations = {"mig_concurrent": _create_user_table_sql("mig_concurrent_t5")}

    async def _migrate_and_close() -> None:
        database = await Database.initialize(server.config())
        await database.migrate(migrations)
        await database.close()

    async with anyio.create_task_group() as task_group:
        task_group.start_soon(_migrate_and_close)
        task_group.start_soon(_migrate_and_close)

    assert_eq((await _fetch_applied_names(server)).count("mig_concurrent"), 1)


@test(mark="medium")
async def failing_migration_leaves_partial_chain_state() -> None:
    """A mid-chain failure halts: earlier objects/history persist, later ones never run.

    MariaDB DDL auto-commits server-side, so the first body's table and its
    history row survive the failure while the failing and following bodies leave
    nothing — the documented backend-neutral partial-failure guarantee.
    """

    migrations = {
        "mig62_partial_ok": _create_user_table_sql("mig62_partial_ok_t"),
        # ALTER of a table no migration created fails at execution time.
        "mig62_partial_break": "ALTER TABLE `mig62_missing_t` ADD COLUMN `x` BIGINT",
        "mig62_partial_later": (
            "CREATE TABLE `mig62_partial_later_t` ("
            "`id` BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY"
            ") ENGINE=InnoDB"
        ),
    }
    server = await load_fixture(mariadb_server())
    database = await Database.initialize(server.config())
    try:
        with assert_raises(MigrationError):
            await database.migrate(migrations)
    finally:
        await database.close()

    applied = await _fetch_applied_names(server)
    assert_true("mig62_partial_ok" in applied)
    assert_true("mig62_partial_break" not in applied)
    assert_true(await _table_exists(server, "mig62_partial_ok_t"))
    assert_true(not await _table_exists(server, "mig62_partial_later_t"))


@test(mark="medium")
async def fixed_retry_resumes_from_the_failure_point() -> None:
    """Replacing the failing body and re-migrating applies only the still-pending bodies."""

    failing = {
        "mig62_retry_ok": _create_user_table_sql("mig62_retry_ok_t"),
        "mig62_retry_break": "ALTER TABLE `mig62_retry_missing_t` ADD COLUMN `x` BIGINT",
        "mig62_retry_later": (
            "CREATE TABLE `mig62_retry_later_t` ("
            "`id` BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY"
            ") ENGINE=InnoDB"
        ),
    }
    fixed = dict(failing)
    fixed["mig62_retry_break"] = (
        "ALTER TABLE `mig62_retry_ok_t` ADD COLUMN `status` "
        "VARCHAR(255) CHARACTER SET utf8mb4 COLLATE utf8mb4_bin"
    )
    server = await load_fixture(mariadb_server())

    database = await Database.initialize(server.config())
    with assert_raises(MigrationError):
        await database.migrate(failing)
    await database.migrate(fixed)
    await database.close()

    applied = await _fetch_applied_names(server)
    assert_true("mig62_retry_break" in applied)
    assert_true("mig62_retry_later" in applied)
    assert_true(await _table_exists(server, "mig62_retry_later_t"))


@test(mark="medium")
async def verify_passes_against_migration_created_schema() -> None:
    """Verification runs after migration and passes on a matching schema."""

    class MigUser[S = Pending](mariadb.Model[S, "MigUser[Fetched]"]):
        """Model whose DDL matches the create-user migration body."""

        __tablename__ = "mig_verify_t3"

        id: MigUser.GenCol[int] = mariadb.Integer(
            primary_key=True, auto_increment=True, default=PENDING_GENERATION
        )
        email: MigUser.Col[str] = mariadb.Text(nullable=False)

    server = await load_fixture(mariadb_server())
    database = await Database.initialize(server.config())
    await database.migrate(
        {"mig_verify_users": _create_user_table_sql("mig_verify_t3")},
    )
    await database.verify([MigUser])
    await database.close()

    assert_true("mig_verify_users" in await _fetch_applied_names(server))

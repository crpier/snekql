"""MariaDB migration apply, history recording, and idempotent re-run tests.

The MariaDB server fixture is shared across the session, so each test uses
globally-unique migration names and table names and asserts only its own
Migration History rows, never the full set.
"""

from __future__ import annotations

import anyio
from snektest import AsyncFixture, assert_eq, assert_true, load_fixture, test

from snekql import mariadb
from snekql.mariadb import MISSING, Database, Fetched, Pending
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


async def mariadb_server() -> AsyncFixture[TemporaryMariaDBServer]:
    """Provide the shared local MariaDB server for migration tests."""

    server = await load_fixture(provide_mariadb_server())
    yield server


@test(mark="medium")
async def migration_creates_table_and_records_history() -> None:
    """A migration body runs against MariaDB and its name is recorded in history."""

    server = await load_fixture(mariadb_server())
    database = await Database.initialize(
        server.config(),
        migrations={"mig_create_users": _create_user_table_sql("mig_users_t1")},
    )
    await database.close()

    assert_true("mig_create_users" in await _fetch_applied_names(server))


@test(mark="medium")
async def reinitializing_does_not_reapply_recorded_migration() -> None:
    """Re-running an already-applied migration records it exactly once."""

    create_audit = (
        "CREATE TABLE `mig_audit_t2` ("
        "`id` BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY"
        ") ENGINE=InnoDB"
    )
    migrations = {"mig_audit_idem": create_audit}
    server = await load_fixture(mariadb_server())

    first = await Database.initialize(server.config(), migrations=migrations)
    await first.close()
    second = await Database.initialize(server.config(), migrations=migrations)
    await second.close()

    applied = await _fetch_applied_names(server)
    assert_eq(applied.count("mig_audit_idem"), 1)


@test(mark="medium")
async def concurrent_initialize_applies_each_migration_once() -> None:
    """Two instances initializing concurrently apply a non-idempotent body once.

    The create-table body is not idempotent: absent the migration advisory lock,
    the loser would re-run it and raise a duplicate-table error. The lock makes
    the loser wait, observe the recorded history, and apply nothing.
    """

    server = await load_fixture(mariadb_server())
    migrations = {"mig_concurrent": _create_user_table_sql("mig_concurrent_t5")}

    async def _initialize_and_close() -> None:
        database = await Database.initialize(server.config(), migrations=migrations)
        await database.close()

    async with anyio.create_task_group() as task_group:
        task_group.start_soon(_initialize_and_close)
        task_group.start_soon(_initialize_and_close)

    assert_eq((await _fetch_applied_names(server)).count("mig_concurrent"), 1)


@test(mark="medium")
async def standalone_migrate_applies_without_full_initialize() -> None:
    """Database.migrate applies a pending body and records history without initialize."""

    server = await load_fixture(mariadb_server())
    await Database.migrate(
        server.config(),
        migrations={"mig_standalone": _create_user_table_sql("mig_standalone_t4")},
    )

    assert_true("mig_standalone" in await _fetch_applied_names(server))


@test(mark="medium")
async def models_verify_against_migration_created_schema() -> None:
    """Drift verification still runs after migrations and passes on a matching schema."""

    class MigUser[S = Pending](mariadb.Model[S, "MigUser[Fetched]"]):
        """Model whose DDL matches the create-user migration body."""

        __tablename__ = "mig_verify_t3"

        id: MigUser.GenCol[int] = mariadb.Integer(
            primary_key=True, auto_increment=True, default=MISSING
        )
        email: MigUser.Col[str] = mariadb.Text(nullable=False)

    server = await load_fixture(mariadb_server())
    database = await Database.initialize(
        server.config(),
        models=[MigUser],
        migrations={"mig_verify_users": _create_user_table_sql("mig_verify_t3")},
    )
    await database.close()

    assert_true("mig_verify_users" in await _fetch_applied_names(server))

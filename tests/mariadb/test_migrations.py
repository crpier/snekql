"""MariaDB imperative migrate/verify, history recording, and idempotent re-run tests.

The MariaDB server fixture is shared across the session, so each test uses
globally-unique migration names and table names and asserts only its own
Migration History rows, never the full set.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from hashlib import sha256

import anyio
from snektest import (
    assert_eq,
    assert_raises,
    assert_true,
    fixture,
    load_fixture,
    test,
)

from snekql import mariadb
from snekql.mariadb import (
    PENDING_GENERATION,
    Database,
    Fetched,
    MigrationDeclarationError,
    MigrationError,
    MigrationHistoryError,
    MigrationResult,
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


@fixture
async def mariadb_server() -> AsyncGenerator[TemporaryMariaDBServer]:
    """Provide the shared local MariaDB server for migration tests."""

    server = await load_fixture(provide_mariadb_server())
    yield server


@test(mark="medium")
async def migrate_creates_table_and_records_history() -> None:
    """A migration body runs against MariaDB and its name is recorded in history."""

    server = await load_fixture(mariadb_server())
    database = await Database.initialize(server.config())
    result = await database.migrate(
        {"mig_create_users": _create_user_table_sql("mig_users_t1")},
    )
    await database.close()

    assert_true("mig_create_users" in await _fetch_applied_names(server))
    assert_eq(
        result,
        MigrationResult(
            applied=("mig_create_users",),
            already_applied=(),
            legacy_adopted=False,
        ),
    )


@test(mark="medium")
async def empty_mariadb_declarations_inspect_without_read_only_mutation() -> None:
    """Empty verification is read-only; empty migration checks and creates history."""

    server = await load_fixture(mariadb_server())
    database = await Database.initialize(server.config())

    await database.verify_migrations({})
    assert_true(not await _table_exists(server, "snekql_migrations"))
    result = await database.migrate({})
    assert_eq(
        result,
        MigrationResult(
            applied=(),
            already_applied=(),
            legacy_adopted=False,
        ),
    )
    await database.migrate(
        {"mig_after_empty": _create_user_table_sql("mig_after_empty_t")}
    )
    with assert_raises(MigrationHistoryError):
        await database.migrate({})
    await database.close()


@test(mark="medium")
async def verify_migrations_accepts_the_exact_mariadb_head() -> None:
    """A replica can verify exact ordered checksummed history without applying."""

    migrations = {"mig_verify_head": _create_user_table_sql("mig_verify_head_t")}
    server = await load_fixture(mariadb_server())
    database = await Database.initialize(server.config())
    await database.migrate(migrations)

    result = await database.verify_migrations(migrations)
    await database.close()

    assert_eq(result, None)


@test(mark="medium")
async def edited_mariadb_body_is_rejected() -> None:
    """A recorded MariaDB name cannot hide changed SQL bytes."""

    migrations = {"mig_edit": _create_user_table_sql("mig_edit_t")}
    server = await load_fixture(mariadb_server())
    database = await Database.initialize(server.config())
    await database.migrate(migrations)

    with assert_raises(MigrationHistoryError):
        await database.migrate({"mig_edit": f"{migrations['mig_edit']} "})
    await database.close()


@test(mark="medium")
async def explicit_mariadb_legacy_adoption_baselines_history() -> None:
    """Explicit consent upgrades exact v1 rows through restartable staging."""

    server = await load_fixture(mariadb_server())
    create_user = _create_user_table_sql("mig_legacy_t")
    await server.run_sql(create_user)
    await server.run_sql(
        "CREATE TABLE `snekql_migrations` ("
        "name VARCHAR(255) CHARACTER SET utf8mb4 COLLATE utf8mb4_bin "
        "NOT NULL PRIMARY KEY, applied_at DATETIME(3) NOT NULL"
        ") ENGINE=InnoDB; "
        "INSERT INTO `snekql_migrations` (name, applied_at) "
        "VALUES ('mig_legacy', UTC_TIMESTAMP(3))"
    )
    database = await Database.initialize(server.config())

    with assert_raises(MigrationHistoryError):
        await database.migrate({"mig_legacy": create_user})
    result = await database.migrate({"mig_legacy": create_user}, adopt_legacy=True)
    await database.close()

    assert_eq(
        result,
        MigrationResult(
            applied=(),
            already_applied=("mig_legacy",),
            legacy_adopted=True,
        ),
    )


@test(mark="medium")
async def empty_mariadb_legacy_history_upgrades_without_adoption() -> None:
    """An empty exact v1 table upgrades without a trust decision."""

    server = await load_fixture(mariadb_server())
    await server.run_sql(
        "CREATE TABLE `snekql_migrations` ("
        "name VARCHAR(255) CHARACTER SET utf8mb4 COLLATE utf8mb4_bin "
        "NOT NULL PRIMARY KEY, applied_at DATETIME(3) NOT NULL"
        ") ENGINE=InnoDB"
    )
    database = await Database.initialize(server.config())

    result = await database.migrate({})
    await database.close()

    assert_eq(
        result,
        MigrationResult(
            applied=(),
            already_applied=(),
            legacy_adopted=False,
        ),
    )


@test(mark="medium")
async def mariadb_transaction_control_is_rejected_before_pool_acquisition() -> None:
    """Bodies cannot end the transaction that owns their history insert."""

    server = await load_fixture(mariadb_server())
    database = await Database.initialize(
        server.config(pool_size=1, acquire_timeout=0.01)
    )

    async with database.transaction():
        for body in (
            "COMMIT",
            "INSERT INTO item VALUES (1); ROLLBACK",
            "SET autocommit = 1",
            "SELECT GET_LOCK('other', 0)",
            "INSERT INTO item VALUES (1); /*! COMMIT */",
            "INSERT INTO item VALUES (1); /*M! COMMIT */",
            "INSERT INTO item VALUES (1); SELECT 1--1; COMMIT",
            "PREPARE migration_stmt FROM 'COMMIT'; EXECUTE migration_stmt",
            "CALL commits_work()",
            "SET SESSION check_constraint_checks = 0",
            "SET @@SESSION.sql_mode = ''",
            "SET SESSION `check_constraint_checks` = 0",
            "SET SESSION `sql_mode` = ''",
            "SET NAMES latin1",
        ):
            with assert_raises(MigrationDeclarationError):
                await database.migrate({"invalid_body": body})
    await database.close()


@test(mark="medium")
async def mariadb_unknown_history_objects_and_schemas_fail_closed() -> None:
    """Views, malformed staging, and fake final checks are never adopted."""

    server = await load_fixture(mariadb_server())
    await server.run_sql(
        "CREATE VIEW snekql_migrations AS "
        "SELECT 1 AS position, 'name' AS name, "
        "REPEAT('0', 64) AS checksum, UTC_TIMESTAMP(3) AS applied_at"
    )
    database = await Database.initialize(server.config())
    with assert_raises(MigrationHistoryError):
        await database.verify_migrations({})
    with assert_raises(MigrationHistoryError):
        await database.migrate({})
    await database.close()

    await server.run_sql("DROP VIEW snekql_migrations")
    await server.reset_database()
    await server.run_sql(
        "CREATE TABLE snekql_migrations ("
        "name BIGINT NOT NULL PRIMARY KEY, applied_at TEXT NULL, "
        "position BIGINT UNSIGNED NULL, checksum VARBINARY(64) NULL"
        ") ENGINE=InnoDB"
    )
    database = await Database.initialize(server.config())
    with assert_raises(MigrationHistoryError):
        await database.migrate({})
    await database.close()

    await server.reset_database()
    await server.run_sql(
        "CREATE TABLE snekql_migrations ("
        "position BIGINT UNSIGNED NOT NULL PRIMARY KEY, "
        "name VARBINARY(1020) NOT NULL, "
        "checksum VARBINARY(64) NOT NULL, applied_at DATETIME(3) NOT NULL, "
        "UNIQUE KEY uq_snekql_migrations_name (name), "
        "CONSTRAINT chk_snekql_migrations_position CHECK (1), "
        "CONSTRAINT chk_snekql_migrations_name CHECK (1), "
        "CONSTRAINT chk_snekql_migrations_checksum CHECK (1)"
        ") ENGINE=InnoDB"
    )
    database = await Database.initialize(server.config())
    with assert_raises(MigrationHistoryError):
        await database.verify_migrations({})
    await database.close()

    await server.reset_database()
    database = await Database.initialize(server.config())
    await database.migrate({})
    await database.close()
    await server.run_sql(
        "ALTER TABLE snekql_migrations MODIFY COLUMN applied_at "
        "DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) "
        "ON UPDATE CURRENT_TIMESTAMP(3)"
    )
    database = await Database.initialize(server.config())
    with assert_raises(MigrationHistoryError):
        await database.verify_migrations({})
    await database.close()

    await server.reset_database()
    database = await Database.initialize(server.config())
    await database.migrate({})
    await database.close()
    await server.run_sql(
        "CREATE TRIGGER mutate_snekql_history BEFORE INSERT "
        "ON snekql_migrations FOR EACH ROW SET NEW.position = NEW.position"
    )
    database = await Database.initialize(server.config())
    with assert_raises(MigrationHistoryError):
        await database.verify_migrations({})
    await database.close()


@test(mark="medium")
async def populated_staging_resumes_without_repeating_legacy_consent() -> None:
    """Persisted positions and checksums prove that adoption already occurred."""

    server = await load_fixture(mariadb_server())
    name = "snake_🐍"
    body = "SELECT 1"
    checksum = sha256(body.encode("utf-8")).hexdigest()
    await server.run_sql(
        "CREATE TABLE snekql_migrations ("
        "name VARCHAR(255) CHARACTER SET utf8mb4 COLLATE utf8mb4_bin "
        "NOT NULL PRIMARY KEY, applied_at DATETIME(3) NOT NULL"
        ") ENGINE=InnoDB; "
        "INSERT INTO snekql_migrations (name, applied_at) VALUES "
        "(CONVERT(0x736E616B655FF09F908D USING utf8mb4), UTC_TIMESTAMP(3)); "
        "ALTER TABLE snekql_migrations "
        "ADD COLUMN position BIGINT UNSIGNED NULL, "
        "ADD COLUMN checksum VARBINARY(64) NULL; "
        "UPDATE snekql_migrations SET position = 1, "
        f"checksum = '{checksum}'"
    )
    database = await Database.initialize(server.config(charset="latin1"))

    result = await database.migrate({name: body})
    await database.close()

    assert_eq(result.applied, ())
    assert_eq(result.already_applied, (name,))
    assert_true(result.legacy_adopted)


@test(mark="medium")
async def mariadb_legacy_adoption_resumes_from_staging() -> None:
    """A restart after nullable v2 columns were added completes safely."""

    server = await load_fixture(mariadb_server())
    create_user = _create_user_table_sql("mig_staging_t")
    await server.run_sql(create_user)
    await server.run_sql(
        "CREATE TABLE `snekql_migrations` ("
        "name VARCHAR(255) CHARACTER SET utf8mb4 COLLATE utf8mb4_bin "
        "NOT NULL PRIMARY KEY, applied_at DATETIME(3) NOT NULL, "
        "position BIGINT UNSIGNED NULL, checksum VARBINARY(64) NULL"
        ") ENGINE=InnoDB; "
        "INSERT INTO `snekql_migrations` (name, applied_at) "
        "VALUES ('mig_staging', UTC_TIMESTAMP(3))"
    )
    database = await Database.initialize(server.config())

    result = await database.migrate({"mig_staging": create_user}, adopt_legacy=True)
    await database.close()

    assert_true(result.legacy_adopted)
    history = await server.run_sql(
        "SELECT position, checksum FROM `snekql_migrations` WHERE name = 'mig_staging'"
    )
    assert_true("1" in history.stdout.splitlines()[1].split("\t")[0])


@test(mark="medium")
async def transactional_dml_rolls_back_when_history_insert_fails() -> None:
    """InnoDB DML and its v2 history row share one commit."""

    migrations = {
        "mig_dml_table": (
            "CREATE TABLE `mig_dml_t` (`id` BIGINT NOT NULL PRIMARY KEY) ENGINE=InnoDB"
        )
    }
    server = await load_fixture(mariadb_server())
    database = await Database.initialize(server.config())
    await database.migrate(migrations)

    with assert_raises(MigrationHistoryError):
        await database.migrate(
            {
                **migrations,
                "mig_dml_insert": (
                    "CREATE TRIGGER `reject_migration_history` BEFORE INSERT "
                    "ON `snekql_migrations` FOR EACH ROW "
                    "SIGNAL SQLSTATE '45000' "
                    "SET MESSAGE_TEXT = 'blocked history insert'; "
                    "INSERT INTO `mig_dml_t` (`id`) VALUES (1)"
                ),
            }
        )
    await database.close()

    rows = await server.run_sql("SELECT COUNT(*) FROM `mig_dml_t`")
    triggers = await server.run_sql(
        "SHOW TRIGGERS WHERE `Trigger` = 'reject_migration_history'"
    )
    assert_true("0" in rows.stdout.splitlines()[1:])
    assert_true("reject_migration_history" in triggers.stdout)


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
    try:
        with assert_raises(MigrationError):
            await database.migrate(failing)
        await database.migrate(fixed)
    finally:
        await database.close()

    applied = await _fetch_applied_names(server)
    assert_true("mig62_retry_break" in applied)
    assert_true("mig62_retry_later" in applied)
    assert_true(await _table_exists(server, "mig62_retry_later_t"))


@test(mark="medium")
async def multi_statement_body_can_leave_a_partial_object() -> None:
    """A multi-statement body that fails mid-way leaves earlier objects behind on MariaDB.

    This is the backend-divergent case (see docs/migrations.md): MariaDB accepts a
    multi-statement body and auto-commits each DDL statement server-side, so the
    first statement's table survives even though a later statement fails and the
    body is never recorded. SQLite cannot reproduce this — its driver rejects
    multi-statement bodies outright. snekql does no cleanup, which is why such
    bodies must be idempotent.
    """

    body = (
        f"{_create_user_table_sql('mig62_partial_obj_t')}; "
        "ALTER TABLE `mig62_partial_obj_missing_t` ADD COLUMN `x` BIGINT"
    )
    server = await load_fixture(mariadb_server())
    database = await Database.initialize(server.config())
    try:
        with assert_raises(MigrationError):
            await database.migrate({"mig62_partial_obj": body})
    finally:
        await database.close()

    # The failing body is not recorded, but its first statement's table survives.
    assert_true("mig62_partial_obj" not in await _fetch_applied_names(server))
    assert_true(await _table_exists(server, "mig62_partial_obj_t"))


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

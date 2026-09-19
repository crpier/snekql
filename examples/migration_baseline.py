"""One-time baseline adoption for a reviewed, dedicated account database.

Back up the database and stop writers, DDL jobs, and deployers before calling
these functions. Keep them stopped through post-verification. These examples
are not generic schema-equivalence checkers or application startup hooks.
Fresh databases use ordinary `migrate()` with the same literal declaration.
"""

from snekql import mariadb, sqlite

SQLITE_MIGRATIONS = {
    "001_reviewed_baseline": (
        'CREATE TABLE IF NOT EXISTS "baseline_account" ("id" INTEGER PRIMARY KEY, '
        '"balance" INTEGER NOT NULL CHECK ("balance" >= 0)) STRICT'
    ),
}
MARIADB_MIGRATIONS = {
    "001_reviewed_baseline": (
        "CREATE TABLE IF NOT EXISTS baseline_account (id BIGINT NOT NULL PRIMARY KEY, "
        "balance BIGINT NOT NULL, CONSTRAINT ck_baseline_balance CHECK (balance >= 0)) "
        "ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin"
    ),
}


# These are independently reviewed catalog outputs, not generated from the
# migration text or models. Formatting/version changes require another review.
_SQLITE_REVIEWED_CREATE = (
    'CREATE TABLE "baseline_account" ("id" INTEGER PRIMARY KEY, '
    '"balance" INTEGER NOT NULL CHECK ("balance" >= 0)) STRICT'
)
_MARIADB_REVIEWED_CREATE = """CREATE TABLE `baseline_account` (
  `id` bigint(20) NOT NULL,
  `balance` bigint(20) NOT NULL,
  PRIMARY KEY (`id`),
  CONSTRAINT `ck_baseline_balance` CHECK (`balance` >= 0)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin"""


class SQLiteAccount[S = sqlite.Pending](
    sqlite.Model[S, "SQLiteAccount[sqlite.Fetched]"]
):
    __tablename__ = "baseline_account"

    id: sqlite.Col[int] = sqlite.Integer(primary_key=True)
    balance: sqlite.Col[int] = sqlite.Integer()


class MariaDBAccount[S = mariadb.Pending](
    mariadb.Model[S, "MariaDBAccount[mariadb.Fetched]"]
):
    __tablename__ = "baseline_account"

    id: mariadb.Col[int] = mariadb.Integer(primary_key=True)
    balance: mariadb.Col[int] = mariadb.Integer()


class BaselineReviewError(sqlite.MigrationError):
    """The live database does not match this application's reviewed baseline."""


async def adopt_sqlite(database: sqlite.Database) -> sqlite.MigrationResult:
    """Adopt a reviewed existing SQLite database using the canonical migration body."""
    if (await database.migration_status(SQLITE_MIGRATIONS)).history_present:
        msg = "baseline adoption requires absent migration history"
        raise BaselineReviewError(msg)
    await database.verify([SQLiteAccount])
    async with database.transaction(read_only=True) as transaction:
        catalog = await transaction.fetch_all(
            sqlite.raw(
                "SELECT type, name, sql FROM main.sqlite_schema "
                "WHERE name NOT GLOB 'sqlite_*' ORDER BY type, name"
            )
        )
        invalid = await transaction.fetch_one(
            sqlite.raw(
                "SELECT COUNT(*) AS count FROM main.baseline_account WHERE balance < 0"
            )
        )
    if invalid["count"] != 0:
        msg = "existing balances violate the reviewed baseline"
        raise BaselineReviewError(msg)
    if catalog != [
        {"type": "table", "name": "baseline_account", "sql": _SQLITE_REVIEWED_CREATE}
    ]:
        msg = "SQLite catalog differs from the reviewed baseline"
        raise BaselineReviewError(msg)
    result = await database.migrate(SQLITE_MIGRATIONS)
    await database.verify_migrations(SQLITE_MIGRATIONS)
    await database.verify([SQLiteAccount])
    return result


async def adopt_mariadb(database: mariadb.Database) -> mariadb.MigrationResult:
    """Adopt a reviewed existing MariaDB database using the canonical migration body."""
    if (await database.migration_status(MARIADB_MIGRATIONS)).history_present:
        msg = "baseline adoption requires absent migration history"
        raise BaselineReviewError(msg)
    await database.verify([MariaDBAccount])
    async with database.transaction(read_only=True) as transaction:
        definition = await transaction.fetch_one(
            mariadb.raw("SHOW CREATE TABLE baseline_account")
        )
        inventory = await transaction.fetch_all(
            mariadb.raw(
                "SELECT TABLE_NAME AS name, TABLE_TYPE AS kind FROM INFORMATION_SCHEMA.TABLES "
                "WHERE TABLE_SCHEMA = DATABASE() "
                "UNION ALL SELECT TRIGGER_NAME, 'TRIGGER' FROM INFORMATION_SCHEMA.TRIGGERS "
                "WHERE TRIGGER_SCHEMA = DATABASE() "
                "UNION ALL SELECT ROUTINE_NAME, ROUTINE_TYPE FROM INFORMATION_SCHEMA.ROUTINES "
                "WHERE ROUTINE_SCHEMA = DATABASE() "
                "UNION ALL SELECT EVENT_NAME, 'EVENT' FROM INFORMATION_SCHEMA.EVENTS "
                "WHERE EVENT_SCHEMA = DATABASE() ORDER BY kind, name"
            )
        )
        invalid = await transaction.fetch_one(
            mariadb.raw(
                "SELECT COUNT(*) AS count FROM baseline_account WHERE balance < 0"
            )
        )
    if invalid["count"] != 0:
        msg = "existing balances violate the reviewed baseline"
        raise BaselineReviewError(msg)
    if inventory != [{"name": "baseline_account", "kind": "BASE TABLE"}]:
        msg = "MariaDB contains objects outside the reviewed baseline"
        raise BaselineReviewError(msg)
    if definition["Create Table"] != _MARIADB_REVIEWED_CREATE:
        msg = "MariaDB table definition differs from the reviewed baseline"
        raise BaselineReviewError(msg)
    result = await database.migrate(MARIADB_MIGRATIONS)
    await database.verify_migrations(MARIADB_MIGRATIONS)
    await database.verify([MariaDBAccount])
    return result

"""MariaDB recovery for one reviewed, pure-DDL migration.

Stop writers and deployers and take a backup before reconciliation. This is not
an automatic retry loop, schema inference, or a repair of arbitrary migrations.
"""

from snekql import mariadb

MIGRATIONS = {
    "001_entries": (
        "CREATE TABLE recovery_entries (id BIGINT NOT NULL PRIMARY KEY) "
        "ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin"
    ),
    "002_note": (
        "ALTER TABLE recovery_entries ADD COLUMN IF NOT EXISTS note "
        "VARCHAR(255) CHARACTER SET utf8mb4 COLLATE utf8mb4_bin NULL"
    ),
}

_BEFORE = """CREATE TABLE `recovery_entries` (
  `id` bigint(20) NOT NULL,
  PRIMARY KEY (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin"""
_AFTER = """CREATE TABLE `recovery_entries` (
  `id` bigint(20) NOT NULL,
  `note` varchar(255) DEFAULT NULL,
  PRIMARY KEY (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin"""


class RecoveryReviewError(mariadb.MigrationError):
    """Actual effects do not match the operator's reviewed replay conditions."""


async def resume_reviewed_ddl(database: mariadb.Database) -> mariadb.MigrationResult:
    """Resume this exact pure-DDL change only from a reviewed before/after shape."""
    status = await database.migration_status(MIGRATIONS)
    if status.applied not in {("001_entries",), ("001_entries", "002_note")}:
        msg = "recovery requires the initial migration to be recorded"
        raise RecoveryReviewError(msg)
    async with database.transaction(read_only=True) as transaction:
        definition = await transaction.fetch_one(
            mariadb.raw("SHOW CREATE TABLE recovery_entries")
        )
    accepted = {_AFTER} if not status.pending else {_BEFORE, _AFTER}
    if definition["Create Table"] not in accepted:
        msg = "actual DDL differs from the reviewed recovery conditions"
        raise RecoveryReviewError(msg)
    result = await database.migrate(MIGRATIONS)
    await database.verify_migrations(MIGRATIONS)
    return result

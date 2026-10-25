"""Expand, dual-write, backfill, then contract during a maintenance cutover.

This example renames `name` to `display_name` without changing its meaning.
Drain all old-only writers before backfilling; bridge writers must write both
columns atomically. Stop and drain every writer before `contract_*`. Start the
new-column-only application after contract finishes. This is not a zero-downtime
contract guarantee or a general migration framework.
"""

from dataclasses import dataclass

from snekql import mariadb, sqlite
from snekql.sqlite import MigrationContext

_MAX_BATCH_SIZE = 1000
"""Bound lock duration and transaction size independently of total row count."""


async def sqlite_customers(migration: MigrationContext) -> None:
    """Apply one reviewed revision."""
    await migration.execute(
        "CREATE TABLE rollout_customer (id INTEGER PRIMARY KEY CHECK (id > 0), name TEXT NOT NULL) STRICT"
    )


async def sqlite_expand(migration: MigrationContext) -> None:
    """Apply one reviewed revision."""
    await migration.execute("ALTER TABLE rollout_customer ADD COLUMN display_name TEXT")


async def sqlite_checkpoint(migration: MigrationContext) -> None:
    """Apply one reviewed revision."""
    await migration.execute(
        "CREATE TABLE rollout_backfill (id INTEGER PRIMARY KEY CHECK (id = 1), last_id INTEGER NOT NULL CHECK (last_id >= 0)) STRICT"
    )


async def sqlite_seed_checkpoint(migration: MigrationContext) -> None:
    """Apply one reviewed revision."""
    await migration.execute("INSERT INTO rollout_backfill VALUES (1, 0)")


SQLITE_EXPANDED = {
    "001_customers": sqlite_customers,
    "002_expand": sqlite_expand,
    "003_checkpoint": sqlite_checkpoint,
    "004_seed_checkpoint": sqlite_seed_checkpoint,
}


async def mariadb_customers(migration: MigrationContext) -> None:
    """Apply one reviewed revision."""
    await migration.execute(
        "CREATE TABLE rollout_customer (id BIGINT NOT NULL PRIMARY KEY CHECK (id > 0), name VARCHAR(255) CHARACTER SET utf8mb4 COLLATE utf8mb4_bin NOT NULL) ENGINE=InnoDB"
    )


async def mariadb_expand(migration: MigrationContext) -> None:
    """Apply one reviewed revision."""
    await migration.execute(
        "ALTER TABLE rollout_customer ADD COLUMN IF NOT EXISTS display_name VARCHAR(255) CHARACTER SET utf8mb4 COLLATE utf8mb4_bin NULL"
    )


async def mariadb_checkpoint(migration: MigrationContext) -> None:
    """Apply one reviewed revision."""
    await migration.execute(
        "CREATE TABLE IF NOT EXISTS rollout_backfill (id BIGINT NOT NULL PRIMARY KEY CHECK (id = 1), last_id BIGINT NOT NULL CHECK (last_id >= 0)) ENGINE=InnoDB"
    )


async def mariadb_seed_checkpoint(migration: MigrationContext) -> None:
    """Apply one reviewed revision."""
    await migration.execute("INSERT INTO rollout_backfill VALUES (1, 0)")


MARIADB_EXPANDED = {
    "001_customers": mariadb_customers,
    "002_expand": mariadb_expand,
    "003_checkpoint": mariadb_checkpoint,
    "004_seed_checkpoint": mariadb_seed_checkpoint,
}


@dataclass(frozen=True)
class BackfillProgress:
    """One acknowledged batch, not proof that a contract deployment is safe."""

    done: bool
    last_id: int
    updated: int


class BackfillError(sqlite.SnekqlError):
    """The batch request or contract preconditions are invalid."""


def _position(value: object) -> int:
    """Require real nonnegative integer cursors, without coercing corrupt state."""
    if type(value) is not int or value < 0:
        msg = "backfill positions must be nonnegative integers"
        raise BackfillError(msg)
    return value


async def backfill_sqlite_batch(
    database: sqlite.Database, *, batch_size: int = 100
) -> BackfillProgress:
    """Commit one page's conditional updates and checkpoint in one transaction."""
    if type(batch_size) is not int or not 1 <= batch_size <= _MAX_BATCH_SIZE:
        msg = "batch_size must be an integer from 1 to 1000"
        raise BackfillError(msg)
    async with database.transaction(mode="immediate") as transaction:
        checkpoint = await transaction.fetch_one(
            sqlite.raw("SELECT last_id FROM rollout_backfill WHERE id=1")
        )
        after = _position(checkpoint["last_id"])
        rows = await transaction.fetch_all(
            sqlite.raw(
                "SELECT id FROM rollout_customer WHERE id > :after ORDER BY id LIMIT :size",
                params={"after": after, "size": batch_size},
            )
        )
        last_id = _position(rows[-1]["id"]) if rows else after
        updated = await transaction.execute(
            sqlite.raw(
                "UPDATE rollout_customer SET display_name=name "
                "WHERE id > :after AND id <= :last AND display_name IS NULL",
                params={"after": after, "last": last_id},
            )
        )
        await transaction.execute(
            sqlite.raw(
                "UPDATE rollout_backfill SET last_id=:last WHERE id=1",
                params={"last": last_id},
            )
        )
    return BackfillProgress(
        done=len(rows) < batch_size, last_id=last_id, updated=updated
    )


async def backfill_mariadb_batch(
    database: mariadb.Database, *, batch_size: int = 100
) -> BackfillProgress:
    """Lock the checkpoint before data rows, serializing competing batch workers."""
    if type(batch_size) is not int or not 1 <= batch_size <= _MAX_BATCH_SIZE:
        msg = "batch_size must be an integer from 1 to 1000"
        raise BackfillError(msg)
    async with database.transaction() as transaction:
        checkpoint = await transaction.fetch_one(
            mariadb.raw("SELECT last_id FROM rollout_backfill WHERE id=1 FOR UPDATE")
        )
        after = _position(checkpoint["last_id"])
        rows = await transaction.fetch_all(
            mariadb.raw(
                "SELECT id FROM rollout_customer WHERE id > %(after)s ORDER BY id LIMIT %(size)s FOR UPDATE",
                params={"after": after, "size": batch_size},
            )
        )
        last_id = _position(rows[-1]["id"]) if rows else after
        updated = await transaction.execute(
            mariadb.raw(
                "UPDATE rollout_customer SET display_name=name "
                "WHERE id > %(after)s AND id <= %(last)s AND display_name IS NULL",
                params={"after": after, "last": last_id},
            )
        )
        await transaction.execute(
            mariadb.raw(
                "UPDATE rollout_backfill SET last_id=%(last)s WHERE id=1",
                params={"last": last_id},
            )
        )
    return BackfillProgress(
        done=len(rows) < batch_size, last_id=last_id, updated=updated
    )


async def sqlite_contract(migration: MigrationContext) -> None:
    """Apply one reviewed revision."""
    await migration.execute("""
              CREATE TABLE rollout_customer_new (
              id INTEGER PRIMARY KEY CHECK (id > 0), display_name TEXT NOT NULL
              ) STRICT;
          """)
    await migration.execute("""
              INSERT INTO rollout_customer_new SELECT id, display_name FROM rollout_customer;
          """)
    await migration.execute("""
              DROP TABLE rollout_customer;
          """)
    await migration.execute("""
              ALTER TABLE rollout_customer_new RENAME TO rollout_customer;
          """)
    await migration.execute("""
              DROP TABLE rollout_backfill;
          """)


SQLITE_CONTRACTED = {
    **SQLITE_EXPANDED,
    "005_contract": sqlite_contract,
}


async def mariadb_contract(migration: MigrationContext) -> None:
    """Apply one reviewed revision."""
    await migration.execute("""
              ALTER TABLE rollout_customer
              MODIFY display_name VARCHAR(255) CHARACTER SET utf8mb4 COLLATE utf8mb4_bin NOT NULL,
              DROP COLUMN name;
          """)
    await migration.execute("""
              DROP TABLE rollout_backfill;
          """)


MARIADB_CONTRACTED = {
    **MARIADB_EXPANDED,
    "005_contract": mariadb_contract,
}


async def contract_sqlite(database: sqlite.Database) -> sqlite.MigrationResult:
    """After externally draining all writers, verify data before removing old storage."""
    await database.verify_migrations(SQLITE_EXPANDED)
    async with database.transaction(read_only=True) as transaction:
        invalid = await transaction.fetch_one(
            sqlite.raw(
                "SELECT COUNT(*) AS count FROM rollout_customer "
                "WHERE display_name IS NULL OR display_name <> name"
            )
        )
    if invalid["count"] != 0:
        msg = "backfill is incomplete or old and new values disagree"
        raise BackfillError(msg)
    result = await database.migrate(SQLITE_CONTRACTED)
    await database.verify_migrations(SQLITE_CONTRACTED)
    return result


async def contract_mariadb(database: mariadb.Database) -> mariadb.MigrationResult:
    """Contract only under a maintenance window; MariaDB DDL remains non-atomic."""
    await database.verify_migrations(MARIADB_EXPANDED)
    async with database.transaction(read_only=True) as transaction:
        invalid = await transaction.fetch_one(
            mariadb.raw(
                "SELECT COUNT(*) AS count FROM rollout_customer "
                "WHERE display_name IS NULL OR BINARY display_name <> BINARY name"
            )
        )
    if invalid["count"] != 0:
        msg = "backfill is incomplete or old and new values disagree"
        raise BackfillError(msg)
    result = await database.migrate(MARIADB_CONTRACTED)
    await database.verify_migrations(MARIADB_CONTRACTED)
    return result

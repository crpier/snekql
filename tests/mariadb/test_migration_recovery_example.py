"""Reconcile real implicit DDL commits before retrying a reviewed migration."""

from collections.abc import AsyncGenerator
from dataclasses import dataclass
from typing import Any
from unittest.mock import patch

from aiomysql import Connection
from aiomysql.cursors import Cursor
from pymysql.err import OperationalError
from snektest import assert_eq, assert_raises, fixture, load_fixture, test

from examples.migration_recovery import (
    MIGRATIONS,
    RecoveryReviewError,
    resume_reviewed_ddl,
)
from snekql import mariadb
from tests.helpers import provide_mariadb_server


@dataclass(frozen=True)
class RecoveryCase:
    config: mariadb.Config
    database: mariadb.Database


@fixture
async def provide_interrupted_ddl() -> AsyncGenerator[RecoveryCase]:
    """Fail history insertion after the server has acknowledged the implicit DDL commit."""
    server = await load_fixture(provide_mariadb_server())
    config = server.config(pool_size=1)
    async with await mariadb.Database.initialize(config) as database:
        await database.migrate({"001_entries": MIGRATIONS["001_entries"]})
        async with database.transaction() as transaction:
            await transaction.execute(
                mariadb.raw("INSERT INTO recovery_entries VALUES (1)")
            )
        execute = Cursor.execute

        async def fail_history(self: Cursor, query: str, args: Any = None) -> Any:
            if query.startswith("INSERT INTO `snekql_migrations`"):
                msg = "injected history write failure"
                raise OperationalError(2013, msg)
            return await execute(self, query, args)

        with (
            patch.object(Cursor, "execute", fail_history),
            assert_raises(mariadb.MigrationHistoryError),
        ):
            await database.migrate(MIGRATIONS)
        yield RecoveryCase(config, database)


@test(mark="slow")
async def pending_history_can_have_committed_ddl() -> None:
    """Pending status does not mean the SQL body had no persistent effects."""
    case = await load_fixture(provide_interrupted_ddl())

    status = await case.database.migration_status(MIGRATIONS)
    async with case.database.transaction() as transaction:
        rows = await transaction.fetch_all(
            mariadb.raw("SELECT id, note FROM recovery_entries")
        )

    assert_eq(status.pending, ("002_note",))
    assert_eq(rows, [{"id": 1, "note": None}])


@test(mark="slow")
async def reviewed_replay_records_history_after_restart() -> None:
    """A fresh connection can resume pure idempotent DDL after inspecting its effects."""
    case = await load_fixture(provide_interrupted_ddl())
    await case.database.close()

    async with await mariadb.Database.initialize(case.config) as restarted:
        result = await resume_reviewed_ddl(restarted)
        await restarted.verify_migrations(MIGRATIONS)

    assert_eq(result.applied, ("002_note",))


@test(mark="slow")
async def mismatched_existing_column_is_not_replayed() -> None:
    """IF NOT EXISTS would hide an incompatible column, so reconciliation must reject it."""
    case = await load_fixture(provide_interrupted_ddl())
    async with case.database.transaction() as transaction:
        await transaction.execute(
            mariadb.raw("ALTER TABLE recovery_entries MODIFY note BIGINT NULL")
        )

    with assert_raises(RecoveryReviewError):
        await resume_reviewed_ddl(case.database)
    assert_eq((await case.database.migration_status(MIGRATIONS)).pending, ("002_note",))


@test(mark="slow")
async def acknowledged_server_commit_is_not_replayed_after_lost_reply() -> None:
    """When the history row committed, reconnecting resolves the uncertain outcome."""
    server = await load_fixture(provide_mariadb_server())
    async with await mariadb.Database.initialize(server.config()) as database:
        await database.migrate({"001_entries": MIGRATIONS["001_entries"]})
        commit = Connection.commit

        async def lose_reply(self: Connection) -> None:
            await commit(self)
            msg = "injected lost commit reply"
            raise OperationalError(2013, msg)

        with (
            patch.object(Connection, "commit", lose_reply),
            assert_raises(mariadb.MigrationHistoryError),
        ):
            await database.migrate(MIGRATIONS)
    async with await mariadb.Database.initialize(server.config()) as restarted:
        result = await resume_reviewed_ddl(restarted)

    assert_eq(result.applied, ())
    assert_eq(result.already_applied, ("001_entries", "002_note"))


@test(mark="slow")
async def replaying_mixed_dml_ddl_can_duplicate_data_effects() -> None:
    """Idempotent DDL does not make preceding DML safe to repeat after an implicit commit."""
    server = await load_fixture(provide_mariadb_server())
    migrations = {
        "001_counter": "CREATE TABLE recovery_counter (id BIGINT PRIMARY KEY, value BIGINT NOT NULL) ENGINE=InnoDB",
        "002_change": "UPDATE recovery_counter SET value=value+1; ALTER TABLE recovery_counter ADD COLUMN IF NOT EXISTS note TEXT",
    }
    async with await mariadb.Database.initialize(server.config()) as database:
        await database.migrate({"001_counter": migrations["001_counter"]})
        async with database.transaction() as transaction:
            await transaction.execute(
                mariadb.raw("INSERT INTO recovery_counter VALUES (1, 0)")
            )
        execute = Cursor.execute

        async def fail_history(self: Cursor, query: str, args: Any = None) -> Any:
            if query.startswith("INSERT INTO `snekql_migrations`"):
                msg = "injected history write failure"
                raise OperationalError(2013, msg)
            return await execute(self, query, args)

        with (
            patch.object(Cursor, "execute", fail_history),
            assert_raises(mariadb.MigrationHistoryError),
        ):
            await database.migrate(migrations)
        # Deliberately demonstrate an unsafe operator action, not a recovery recipe.
        await database.migrate(migrations)
        async with database.transaction() as transaction:
            row = await transaction.fetch_one(
                mariadb.raw("SELECT value FROM recovery_counter WHERE id=1")
            )

    assert_eq(row, {"value": 2})

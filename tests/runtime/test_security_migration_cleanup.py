"""Migration cleanup retains its lease under repeated native cancellation."""

import asyncio
from collections.abc import Iterable
from typing import Literal
from unittest.mock import patch

from aiosqlite import Connection, Cursor
from anyio import Event, fail_after, sleep_forever
from snektest import Param, assert_eq, assert_raises, load_fixture, test

from snekql import sqlite
from tests.runtime.test_security_lifecycle import single_connection_file


@test(
    [
        Param[Literal["migrate", "verify", "status"]]("migrate", name="apply"),
        Param[Literal["migrate", "verify", "status"]]("verify", name="verify"),
        Param[Literal["migrate", "verify", "status"]]("status", name="status"),
    ],
    mark="medium",
)
async def cancelled_migration_recovers_pool_capacity(
    operation: Literal["migrate", "verify", "status"],
) -> None:
    """Cancellation at driver rollback checkpoints cannot abandon a pool slot."""
    database = await load_fixture(single_connection_file())
    body_entered = Event()
    rollback_entered = asyncio.Queue[None]()
    original_execute = Connection.execute
    original_rollback = Connection.rollback

    async def execute(
        connection: Connection,
        sql: str,
        parameters: Iterable[object] | None = None,
    ) -> Cursor:
        if (
            operation == "migrate" and sql.strip() == "INSERT INTO entries VALUES (2)"
        ) or (
            operation != "migrate" and sql.startswith("SELECT position, name, checksum")
        ):
            body_entered.set()
            await sleep_forever()
        return await original_execute(connection, sql, parameters)

    async def rollback(connection: Connection) -> None:
        rollback_entered.put_nowait(None)
        await asyncio.sleep(0)
        await original_rollback(connection)

    async def migrate() -> None:
        migrations = {
            "001": "CREATE TABLE entries (value INTEGER PRIMARY KEY) STRICT",
        }
        if operation == "migrate":
            migrations["002"] = (
                "INSERT INTO entries VALUES (1); INSERT INTO entries VALUES (2)"
            )
            await database.migrate(migrations)
        elif operation == "verify":
            await database.verify_migrations(migrations)
        else:
            await database.migration_status(migrations)

    # Pause only at the external driver boundary; assert recovery through Database.
    with (
        patch.object(Connection, "execute", execute),
        patch.object(Connection, "rollback", rollback),
    ):
        pending = asyncio.create_task(migrate())
        try:
            with fail_after(5):
                await body_entered.wait()
                pending.cancel()
                await rollback_entered.get()
                pending.cancel()
                await rollback_entered.get()
                pending.cancel()
                with assert_raises(asyncio.CancelledError):
                    await pending
        finally:
            if not pending.done():
                pending.cancel()
                with assert_raises(asyncio.CancelledError):
                    await pending

    with fail_after(5):
        async with database.transaction(timeout=1) as transaction:
            rows = await transaction.fetch_all(sqlite.raw("SELECT value FROM entries"))
    assert_eq(rows, [])

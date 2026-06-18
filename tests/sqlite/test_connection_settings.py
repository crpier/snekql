"""SQLite per-connection required-settings application and enforcement."""

from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory

from aiosqlite import Connection
from snektest import assert_eq, assert_raises, test

from snekql.sqlite import (
    MISSING,
    Database,
    ExecutionError,
    Fetched,
    ForeignKey,
    Integer,
    Model,
    Pending,
    insert,
)
from snekql.sqlite.pool import close_sqlite_connection, open_sqlite_connection
from snekql.sqlite.settings import SQLITE_BUSY_TIMEOUT_MS
from tests.helpers import NULL_LOGGER


async def _pragma_value(connection: Connection, pragma: str) -> object:
    cursor = await connection.execute(f"PRAGMA {pragma}")
    try:
        row = await cursor.fetchone()
    finally:
        await cursor.close()
    return row[0] if row is not None else None


@test(mark="medium")
async def open_connection_applies_required_pragmas() -> None:
    """Every opened connection has foreign_keys, busy_timeout, and UTF-8 set."""

    with TemporaryDirectory() as directory:
        connection = await open_sqlite_connection(str(Path(directory) / "app.db"))
        try:
            assert_eq(await _pragma_value(connection, "foreign_keys"), 1)
            assert_eq(
                await _pragma_value(connection, "busy_timeout"),
                SQLITE_BUSY_TIMEOUT_MS,
            )
            assert_eq(await _pragma_value(connection, "encoding"), "UTF-8")
        finally:
            await close_sqlite_connection(connection)


@test(mark="medium")
async def inserting_a_row_that_violates_a_foreign_key_is_rejected() -> None:
    """Emitted FK constraints are enforced now that foreign_keys is ON."""

    class Parent[S = Pending](Model[S, "Parent[Fetched]"]):
        """Referenced table."""

        id: Parent.GenCol[int] = Integer(
            primary_key=True,
            auto_increment=True,
            default=MISSING,
        )

    class Child[S = Pending](Model[S, "Child[Fetched]"]):
        """Table whose parent_id is an enforced foreign key."""

        id: Child.GenCol[int] = Integer(
            primary_key=True,
            auto_increment=True,
            default=MISSING,
        )
        parent_id: Child.FKCol[Parent, int] = ForeignKey(Parent.id, nullable=False)

    with TemporaryDirectory() as directory:
        database_path = Path(directory) / "app.db"
        database = await Database.initialize(
            logger=NULL_LOGGER,
            database=database_path,
            models=[Parent, Child],
        )
        try:
            with assert_raises(ExecutionError):
                async with database.transaction() as tx:
                    await tx.execute(insert(Child(parent_id=999)))
        finally:
            await database.close()

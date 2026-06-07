"""SQLite Database runtime lifecycle behavior tests."""

from __future__ import annotations

import asyncio
from pathlib import Path
from sqlite3 import connect
from tempfile import TemporaryDirectory

from snektest import assert_eq, assert_raises, test

from snekql import (
    MISSING,
    Database,
    DatabaseClosedError,
    DatabaseCloseTimeoutError,
    DatabaseClosingError,
    DatabaseRuntimeError,
    Fetched,
    Integer,
    Model,
    Pending,
    PoolTimeoutError,
    Text,
    insert,
)
from tests.helpers import NULL_LOGGER


class RuntimeUser[S = Pending](Model[S, "RuntimeUser[Fetched]"]):
    """Table model used by transaction runtime tests."""

    id: RuntimeUser.GenCol[int] = Integer(
        primary_key=True,
        auto_increment=True,
        default=MISSING,
    )
    email: RuntimeUser.Col[str] = Text(nullable=False)


def _count_users(database_path: Path) -> int:
    connection = connect(database_path)
    try:
        cursor = connection.execute('SELECT COUNT(*) FROM "runtime_user"')
        value = cursor.fetchone()[0]
        assert isinstance(value, int)
        return value
    finally:
        connection.close()


@test(mark="medium")
async def successful_transaction_commits() -> None:
    """A transaction commits writes when its context exits successfully."""

    with TemporaryDirectory() as directory:
        database_path = Path(directory) / "app.db"
        database = await Database.initialize(
            logger=NULL_LOGGER, database=database_path, models=[RuntimeUser]
        )
        try:
            async with database.transaction() as tx:
                await tx.execute(insert(RuntimeUser(email="alice@example.com")))
        finally:
            await database.close()

        assert_eq(_count_users(database_path), 1)


@test(mark="medium")
async def exceptional_transaction_rolls_back() -> None:
    """A transaction rolls back writes when its context exits exceptionally."""

    with TemporaryDirectory() as directory:
        database_path = Path(directory) / "app.db"
        database = await Database.initialize(
            logger=NULL_LOGGER, database=database_path, models=[RuntimeUser]
        )
        try:
            with assert_raises(ValueError):
                async with database.transaction() as tx:
                    await tx.execute(
                        insert(RuntimeUser(email="rollback@example.com")),
                    )
                    msg = "force rollback"
                    raise ValueError(msg)
        finally:
            await database.close()

        assert_eq(_count_users(database_path), 0)


@test(mark="medium")
async def pool_exhaustion_raises_pool_timeout() -> None:
    """A checkout beyond pool_size waits only up to the transaction timeout."""

    database = await Database.initialize(
        logger=NULL_LOGGER,
        database=":memory:",
        pool_size=1,
        acquire_timeout=0.0,
    )
    try:
        async with database.transaction():
            with assert_raises(PoolTimeoutError):
                async with database.transaction(timeout=0.0):
                    pass
    finally:
        await database.close()


@test(mark="medium")
async def pool_configuration_rejects_invalid_bounds() -> None:
    """Pool size and acquisition timeout validate their documented lower bounds."""

    with assert_raises(DatabaseRuntimeError):
        _ = await Database.initialize(
            logger=NULL_LOGGER, database=":memory:", pool_size=0
        )

    with assert_raises(DatabaseRuntimeError):
        _ = await Database.initialize(
            logger=NULL_LOGGER, database=":memory:", acquire_timeout=-0.1
        )

    database = await Database.initialize(
        logger=NULL_LOGGER, database=":memory:", pool_size=5
    )
    await database.close()


@test(mark="medium")
async def close_rejects_new_transactions_while_waiting_for_checkouts() -> None:
    """Closing temporarily rejects new transactions until checked-out work exits."""

    database = await Database.initialize(
        logger=NULL_LOGGER,
        database=":memory:",
        pool_size=1,
        acquire_timeout=1.0,
    )
    async with database.transaction():
        close_task = asyncio.create_task(database.close())
        await asyncio.sleep(0)
        with assert_raises(DatabaseClosingError):
            _ = database.transaction()
    await close_task

    with assert_raises(DatabaseClosedError):
        _ = database.transaction()


@test(mark="medium")
async def timed_out_close_keeps_database_retryable() -> None:
    """A close timeout leaves the database open once checked-out work returns."""

    database = await Database.initialize(
        logger=NULL_LOGGER,
        database=":memory:",
        pool_size=1,
        acquire_timeout=0.0,
    )
    transaction = database.transaction()
    _ = await transaction.__aenter__()

    with assert_raises(DatabaseCloseTimeoutError):
        await database.close()

    await transaction.__aexit__(None, None, None)
    async with database.transaction(timeout=0.0):
        pass
    await database.close()

    with assert_raises(DatabaseClosedError):
        _ = database.transaction()

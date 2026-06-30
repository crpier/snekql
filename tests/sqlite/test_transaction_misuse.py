"""Transaction lifecycle misuse contract tests.

A ``Transaction`` is single-use: enter it once with ``async with``, run queries
while it is open, and let the block exit close it. These tests pin the documented
behavior for every off-path use -- querying before entering, querying after
closing, entering twice, closing twice, sharing one transaction across
concurrent tasks, and opening independent transactions from one ``Database``.
"""

from __future__ import annotations

from pathlib import Path
from sqlite3 import connect
from tempfile import TemporaryDirectory

import anyio
from snektest import assert_eq, assert_raises, test

from snekql.sqlite import (
    PENDING_GENERATION,
    Database,
    Fetched,
    Integer,
    Model,
    Pending,
    PoolTimeoutError,
    Text,
    TransactionClosedError,
    TransactionNotStartedError,
    TransactionReuseError,
    TransactionStateError,
    insert,
    select,
)
from tests.helpers import initialized_database


class MisuseUser[S = Pending](Model[S, "MisuseUser[Fetched]"]):
    """Table model used by transaction misuse tests."""

    id: MisuseUser.GenCol[int] = Integer(
        primary_key=True,
        auto_increment=True,
        default=PENDING_GENERATION,
    )
    email: MisuseUser.Col[str] = Text(nullable=False)


def _count_users(database_path: Path) -> int:
    connection = connect(database_path)
    try:
        cursor = connection.execute('SELECT COUNT(*) FROM "misuse_user"')
        value = cursor.fetchone()[0]
        assert isinstance(value, int)
        return value
    finally:
        connection.close()


@test(mark="fast")
def lifecycle_errors_share_a_catchable_base() -> None:
    """Every lifecycle misuse error is catchable as TransactionStateError."""

    assert issubclass(TransactionClosedError, TransactionStateError)
    assert issubclass(TransactionNotStartedError, TransactionStateError)
    assert issubclass(TransactionReuseError, TransactionStateError)


@test(mark="medium")
async def query_before_enter_raises_not_started() -> None:
    """Every query method rejects use before the transaction is entered."""

    database = await initialized_database(database=":memory:", models=[MisuseUser])
    try:
        tx = database.transaction()

        with assert_raises(TransactionNotStartedError) as caught:
            _ = await tx.fetch_all(select(MisuseUser).all())
        assert "not been started" in str(caught.exception)
        assert isinstance(caught.exception, TransactionStateError)

        with assert_raises(TransactionNotStartedError):
            _ = await tx.fetch_one(select(MisuseUser).all())

        with assert_raises(TransactionNotStartedError):
            await tx.execute(insert(MisuseUser(email="early@example.com")))

        with assert_raises(TransactionNotStartedError):
            async with tx.fetch_chunks(select(MisuseUser).all(), size=10):
                pass
    finally:
        await database.close()


@test(mark="medium")
async def query_after_exit_raises_closed() -> None:
    """A query run after the transaction has exited rejects use-after-close."""

    database = await initialized_database(database=":memory:", models=[MisuseUser])
    try:
        async with database.transaction() as tx:
            await tx.execute(insert(MisuseUser(email="alice@example.com")))

        with assert_raises(TransactionClosedError) as caught:
            _ = await tx.fetch_all(select(MisuseUser).all())
        assert "closed" in str(caught.exception)
        assert isinstance(caught.exception, TransactionStateError)
    finally:
        await database.close()


@test(mark="medium")
async def re_entering_open_transaction_raises_reuse() -> None:
    """Entering a transaction that is still open is rejected as reuse."""

    database = await initialized_database(database=":memory:", models=[MisuseUser])
    try:
        async with database.transaction() as tx:
            with assert_raises(TransactionReuseError) as caught:
                _ = await tx.__aenter__()
            assert "already in progress" in str(caught.exception)
            assert isinstance(caught.exception, TransactionStateError)
    finally:
        await database.close()


@test(mark="medium")
async def re_entering_closed_transaction_raises_reuse() -> None:
    """A used-and-closed transaction cannot be restarted by re-entering."""

    database = await initialized_database(database=":memory:", models=[MisuseUser])
    try:
        tx = database.transaction()
        async with tx:
            pass

        with assert_raises(TransactionReuseError) as caught:
            _ = await tx.__aenter__()
        assert "already been used" in str(caught.exception)
    finally:
        await database.close()


@test(mark="medium")
async def double_exit_raises_closed() -> None:
    """Closing a transaction a second time rejects the redundant close."""

    database = await initialized_database(database=":memory:", models=[MisuseUser])
    try:
        tx = database.transaction()
        _ = await tx.__aenter__()
        await tx.__aexit__(None, None, None)

        with assert_raises(TransactionClosedError):
            await tx.__aexit__(None, None, None)
    finally:
        await database.close()


@test(mark="medium")
async def concurrent_use_of_shared_transaction_serializes() -> None:
    """Sharing one transaction across tasks serializes work on its connection."""

    database = await initialized_database(database=":memory:", models=[MisuseUser])
    try:
        async with database.transaction() as tx:
            async with anyio.create_task_group() as task_group:
                for index in range(5):
                    task_group.start_soon(
                        tx.execute,
                        insert(MisuseUser(email=f"user{index}@example.com")),
                    )
            emails = await tx.fetch_all(select(MisuseUser.email).all())
    finally:
        await database.close()

    assert_eq(len(emails), 5)
    assert_eq(len(set(emails)), 5)


@test(mark="medium")
async def concurrent_use_after_close_raises_closed() -> None:
    """A task that touches a transaction after it closed is rejected."""

    database = await initialized_database(database=":memory:", models=[MisuseUser])
    try:
        tx = database.transaction()
        _ = await tx.__aenter__()
        await tx.__aexit__(None, None, None)

        with assert_raises(BaseExceptionGroup) as caught:
            async with anyio.create_task_group() as task_group:
                task_group.start_soon(
                    tx.execute,
                    insert(MisuseUser(email="late@example.com")),
                )
        matched, _rest = caught.exception.split(TransactionClosedError)
        assert matched is not None
    finally:
        await database.close()


@test(mark="medium")
async def transactions_from_one_database_are_independent() -> None:
    """A transaction opened inside another uses its own pooled connection."""

    with TemporaryDirectory() as directory:
        database_path = Path(directory) / "app.db"
        database = await initialized_database(
            database=database_path,
            models=[MisuseUser],
            pool_size=2,
        )
        try:
            async with database.transaction() as outer:
                async with database.transaction() as inner:
                    assert inner is not outer
                    await inner.execute(insert(MisuseUser(email="inner@example.com")))
                await outer.execute(insert(MisuseUser(email="outer@example.com")))
        finally:
            await database.close()

        assert_eq(_count_users(database_path), 2)


@test(mark="medium")
async def nested_transaction_competes_for_a_connection() -> None:
    """Nesting is not a savepoint: a second transaction needs its own connection."""

    database = await Database.initialize(
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

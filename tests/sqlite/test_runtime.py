"""SQLite Database runtime lifecycle behavior tests."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path
from sqlite3 import connect
from tempfile import TemporaryDirectory

import anyio
import anyio.lowlevel
from pydantic import PositiveInt
from snektest import assert_eq, assert_raises, test

from snekql.sqlite import (
    PENDING_GENERATION,
    Database,
    DatabaseClosedError,
    DatabaseCloseTimeoutError,
    DatabaseClosingError,
    DatabaseRuntimeError,
    Fetched,
    Integer,
    Model,
    ModelValidationError,
    Pending,
    PoolTimeoutError,
    Text,
    insert,
    select,
)
from tests.helpers import initialized_database


class RuntimeMoment[S = Pending](Model[S, "RuntimeMoment[Fetched]"]):
    """Table model whose datetime column is stored as ISO text (issue #212)."""

    id: RuntimeMoment.GenCol[int] = Integer(
        primary_key=True,
        auto_increment=True,
        default=PENDING_GENERATION,
    )
    label: RuntimeMoment.Col[str] = Text(nullable=False)
    ts: RuntimeMoment.Col[datetime] = Text(nullable=False)


class RuntimeUser[S = Pending](Model[S, "RuntimeUser[Fetched]"]):
    """Table model used by transaction runtime tests."""

    id: RuntimeUser.GenCol[int] = Integer(
        primary_key=True,
        auto_increment=True,
        default=PENDING_GENERATION,
    )
    email: RuntimeUser.Col[str] = Text(nullable=False)


class RuntimeReceipt[S = Pending](Model[S, "RuntimeReceipt[Fetched]"]):
    """Table model with a constrained column for read-side validation tests."""

    id: RuntimeReceipt.GenCol[int] = Integer(
        primary_key=True,
        auto_increment=True,
        default=PENDING_GENERATION,
    )
    amount: RuntimeReceipt.Col[PositiveInt] = Integer(nullable=False)


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
        database = await initialized_database(
            database=database_path, models=[RuntimeUser]
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
        database = await initialized_database(
            database=database_path, models=[RuntimeUser]
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
        _ = await Database.initialize(database=":memory:", pool_size=0)

    with assert_raises(DatabaseRuntimeError):
        _ = await Database.initialize(database=":memory:", acquire_timeout=-0.1)

    database = await Database.initialize(database=":memory:", pool_size=5)
    await database.close()


@test(mark="medium")
async def close_rejects_new_transactions_while_waiting_for_checkouts() -> None:
    """Closing temporarily rejects new transactions until checked-out work exits."""

    database = await Database.initialize(
        database=":memory:",
        pool_size=1,
        acquire_timeout=1.0,
    )
    async with anyio.create_task_group() as task_group, database.transaction():
        task_group.start_soon(database.close)
        with anyio.fail_after(1.0):
            while True:
                try:
                    _ = database.transaction()
                except DatabaseClosingError:
                    break
                await anyio.lowlevel.checkpoint()

    with assert_raises(DatabaseClosedError):
        _ = database.transaction()


@test(mark="medium")
async def timed_out_close_keeps_database_retryable() -> None:
    """A close timeout leaves the database open once checked-out work returns."""

    database = await Database.initialize(
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


@test(mark="medium")
async def fetch_validates_logical_types_and_can_skip_validation() -> None:
    """fetch_all validates rows by default and skips checks when validate=False."""

    database = await initialized_database(
        database=":memory:",
        models=[RuntimeReceipt],
    )
    try:
        async with database.transaction() as tx:
            # construct bypasses the write-side check, so an out-of-range value
            # reaches storage and only the read side can reject it.
            await tx.execute(insert(RuntimeReceipt.construct(amount=-5)))

            with assert_raises(ModelValidationError):
                _ = await tx.fetch_all(select(RuntimeReceipt).all())

            rows = await tx.fetch_all(select(RuntimeReceipt).all(), validate=False)
    finally:
        await database.close()

    assert_eq(len(rows), 1)
    assert_eq(rows[0].amount, -5)


@test(mark="medium")
async def datetime_text_column_orders_and_matches_by_instant() -> None:
    """Rows written from different-looking representations of the same or
    ordered instants sort and compare by instant, not by raw wall-clock text.

    Before #212 the ``+05:30`` row's text started ``...T17:30`` and would sort
    after a later UTC instant; canonicalizing to UTC on encode makes SQLite's
    lexical TEXT comparison coincide with instant comparison."""

    later_utc = datetime(2026, 7, 1, 13, 0, 0, tzinfo=UTC)
    # The same instant (12:00 UTC), expressed three ways.
    utc_second = datetime(2026, 7, 1, 12, 0, 0, tzinfo=UTC)
    # Sub-millisecond microseconds floor to .000Z, the same stored text as the
    # whole-second noon row -- so an equality probe still matches by instant.
    utc_micros = datetime(2026, 7, 1, 12, 0, 0, 400, tzinfo=UTC)
    offset_form = datetime(
        2026, 7, 1, 17, 30, 0, tzinfo=timezone(timedelta(hours=5, minutes=30))
    )

    database = await initialized_database(
        database=":memory:",
        models=[RuntimeMoment],
    )
    try:
        async with database.transaction() as tx:
            await tx.execute(insert(RuntimeMoment(label="later", ts=later_utc)))
            await tx.execute(insert(RuntimeMoment(label="noon_utc", ts=utc_second)))
            await tx.execute(insert(RuntimeMoment(label="noon_offset", ts=offset_form)))

            ordered = await tx.fetch_all(
                select(RuntimeMoment).all().order_by(RuntimeMoment.ts.asc()),
            )
            # The +05:30 row is the same instant as noon_utc, so it must sort
            # before the 13:00 UTC row -- not after it as its 17:30 text implies.
            noon_then_later = await tx.fetch_all(
                select(RuntimeMoment)
                .where(RuntimeMoment.ts.lt(later_utc))
                .order_by(RuntimeMoment.ts.asc()),
            )
            equal_to_noon = await tx.fetch_all(
                select(RuntimeMoment).where(RuntimeMoment.ts.eq(utc_micros)),
            )
    finally:
        await database.close()

    assert_eq([row.label for row in ordered], ["noon_utc", "noon_offset", "later"])
    assert_eq(sorted(row.label for row in noon_then_later), ["noon_offset", "noon_utc"])
    # utc_micros floors to 12:00:00.000Z, the same stored text as the noon rows.
    assert_eq(sorted(row.label for row in equal_to_noon), ["noon_offset", "noon_utc"])

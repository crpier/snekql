"""Bare timedelta storage behavior over MariaDB Integer and Text columns."""

from __future__ import annotations

from datetime import timedelta

from snektest import assert_eq, assert_raises, load_fixture, test

from snekql import mariadb
from snekql.mariadb import ExecutionError, Fetched, Pending, insert, select
from tests.helpers import initialized_database, provide_mariadb_server


class IntegerDurationRow[S = Pending](mariadb.Model[S, "IntegerDurationRow[Fetched]"]):
    """Table declaring a timedelta over an Integer storage class."""

    __tablename__ = "timedelta_integer_duration"

    id: IntegerDurationRow.Col[int] = mariadb.Integer(primary_key=True)
    elapsed: IntegerDurationRow.Col[timedelta] = mariadb.Integer(nullable=False)


class RoundTripRow[S = Pending](mariadb.Model[S, "RoundTripRow[Fetched]"]):
    """Text-stored timedelta table for round-trip checks."""

    __tablename__ = "timedelta_text_roundtrip"

    id: RoundTripRow.Col[int] = mariadb.Integer(primary_key=True)
    elapsed: RoundTripRow.Col[timedelta] = mariadb.Text(nullable=False)


class OrderedRow[S = Pending](mariadb.Model[S, "OrderedRow[Fetched]"]):
    """Text-stored timedelta table for ordering checks."""

    __tablename__ = "timedelta_text_order"

    id: OrderedRow.Col[int] = mariadb.Integer(primary_key=True)
    elapsed: OrderedRow.Col[timedelta] = mariadb.Text(nullable=False)


@test(mark="medium")
async def strict_bigint_column_rejects_duration_text_at_insert() -> None:
    """STRICT_ALL_TABLES refuses duration text bound to a BIGINT column.

    Without strict mode MariaDB would coerce the text to 0 with a warning;
    the connection settings force the mismatch to fail loudly at write time.
    """

    server = await load_fixture(provide_mariadb_server())
    database = await initialized_database(server.config(), models=[IntegerDurationRow])
    try:
        with assert_raises(ExecutionError):
            async with database.transaction() as tx:
                await tx.execute(
                    insert(IntegerDurationRow(id=1, elapsed=timedelta(seconds=9)))
                )
    finally:
        await database.close()


@test(mark="medium")
async def text_column_round_trips_timedelta_values() -> None:
    """Duration text stored over Text decodes back to equal timedeltas."""

    server = await load_fixture(provide_mariadb_server())
    database = await initialized_database(server.config(), models=[RoundTripRow])
    try:
        async with database.transaction() as tx:
            await tx.execute(insert(RoundTripRow(id=1, elapsed=timedelta(seconds=9))))
            await tx.execute(insert(RoundTripRow(id=2, elapsed=timedelta(seconds=-5))))
            fetched = await tx.fetch_all(
                select(RoundTripRow.elapsed).all().order_by(RoundTripRow.id.asc())
            )
    finally:
        await database.close()

    assert_eq(fetched, [timedelta(seconds=9), timedelta(seconds=-5)])


@test(mark="medium")
async def text_column_orders_durations_lexically_not_by_magnitude() -> None:
    """ORDER BY over duration text follows lexical, not logical, order.

    `'PT10S'` sorts before `'PT1H'`, which sorts before `'PT9M'` and `'PT9S'`,
    so ascending database order disagrees with the timedelta magnitudes.
    """

    server = await load_fixture(provide_mariadb_server())
    database = await initialized_database(server.config(), models=[OrderedRow])
    try:
        async with database.transaction() as tx:
            await tx.execute(insert(OrderedRow(id=1, elapsed=timedelta(seconds=9))))
            await tx.execute(insert(OrderedRow(id=2, elapsed=timedelta(seconds=10))))
            await tx.execute(insert(OrderedRow(id=3, elapsed=timedelta(minutes=9))))
            await tx.execute(insert(OrderedRow(id=4, elapsed=timedelta(hours=1))))
            ordered_ids = await tx.fetch_all(
                select(OrderedRow.id).all().order_by(OrderedRow.elapsed.asc())
            )
    finally:
        await database.close()

    magnitude_order = [1, 2, 3, 4]
    assert_eq(ordered_ids, [2, 4, 3, 1])
    assert ordered_ids != magnitude_order

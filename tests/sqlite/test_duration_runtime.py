"""Duration SQLite runtime behavior tests."""

from __future__ import annotations

from datetime import timedelta

from snektest import assert_eq, test

from snekql.sqlite import Duration, Fetched, Integer, Model, Pending, insert, select
from tests.helpers import initialized_database


class TimedSpan[S = Pending](Model[S, "TimedSpan[Fetched]"]):
    """Timed span table with integer duration storage."""

    id: TimedSpan.Col[TimedSpan, int] = Integer(primary_key=True)
    elapsed: TimedSpan.Col[TimedSpan, Duration] = Integer(nullable=False)


@test(mark="medium")
async def duration_integer_storage_round_trips() -> None:
    """Duration values round-trip through SQLite Integer storage."""

    database = await initialized_database(database=":memory:", models=[TimedSpan])
    try:
        async with database.transaction() as tx:
            await tx.execute(insert(TimedSpan(id=1, elapsed=timedelta(seconds=9))))
            fetched = await tx.fetch_one(select(TimedSpan.elapsed).all())
    finally:
        await database.close()

    assert_eq(fetched, timedelta(seconds=9))


@test(mark="medium")
async def duration_integer_storage_orders_by_magnitude() -> None:
    """Duration ordering follows timedelta magnitude in the database."""

    database = await initialized_database(database=":memory:", models=[TimedSpan])
    try:
        async with database.transaction() as tx:
            await tx.execute(insert(TimedSpan(id=1, elapsed=timedelta(seconds=9))))
            await tx.execute(insert(TimedSpan(id=2, elapsed=timedelta(seconds=10))))
            await tx.execute(insert(TimedSpan(id=3, elapsed=timedelta(minutes=9))))
            await tx.execute(insert(TimedSpan(id=4, elapsed=timedelta(hours=1))))
            await tx.execute(insert(TimedSpan(id=5, elapsed=timedelta(seconds=-5))))
            ordered_ids = await tx.fetch_all(
                select(TimedSpan.id).all().order_by(TimedSpan.elapsed.asc())
            )
    finally:
        await database.close()

    assert_eq(ordered_ids, [5, 1, 2, 3, 4])


@test(mark="medium")
async def duration_integer_storage_ranges_by_magnitude() -> None:
    """Duration range predicates compare timedelta magnitude in the database."""

    database = await initialized_database(database=":memory:", models=[TimedSpan])
    try:
        async with database.transaction() as tx:
            await tx.execute(insert(TimedSpan(id=1, elapsed=timedelta(seconds=9))))
            await tx.execute(insert(TimedSpan(id=2, elapsed=timedelta(seconds=10))))
            await tx.execute(insert(TimedSpan(id=3, elapsed=timedelta(minutes=9))))
            await tx.execute(insert(TimedSpan(id=4, elapsed=timedelta(hours=1))))
            await tx.execute(insert(TimedSpan(id=5, elapsed=timedelta(seconds=-5))))
            range_ids = await tx.fetch_all(
                select(TimedSpan.id)
                .where(TimedSpan.elapsed.gte(timedelta(seconds=10)))
                .order_by(TimedSpan.id.asc())
            )
    finally:
        await database.close()

    assert_eq(range_ids, [2, 3, 4])

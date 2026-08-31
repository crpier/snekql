"""UtcDatetime SQLite runtime behavior tests."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone

from snektest import assert_eq, test

from snekql.sqlite import (
    Fetched,
    Integer,
    Model,
    Pending,
    Text,
    UtcDatetime,
    insert,
    select,
)
from tests.helpers import initialized_database


class TimedEvent[S = Pending](Model[S, "TimedEvent[Fetched]"]):
    """Event table with canonical timestamp text storage."""

    id: TimedEvent.Col[int] = Integer(primary_key=True)
    happened_at: TimedEvent.Col[UtcDatetime] = Text(nullable=False)


@test(mark="medium")
async def utc_datetime_text_queries_compare_by_instant() -> None:
    """Equality, ordering, and ranges use instant-correct canonical text."""

    same_instant_utc = datetime(2026, 7, 1, 12, 0, 0, tzinfo=UTC)
    same_instant_offset = datetime(
        2026,
        7,
        1,
        17,
        30,
        0,
        tzinfo=timezone(timedelta(hours=5, minutes=30)),
    )
    later = datetime(2026, 7, 1, 13, 0, 0, tzinfo=UTC)
    database = await initialized_database(database=":memory:", models=[TimedEvent])
    try:
        async with database.transaction() as tx:
            await tx.execute(insert(TimedEvent(id=1, happened_at=same_instant_utc)))
            await tx.execute(insert(TimedEvent(id=2, happened_at=same_instant_offset)))
            await tx.execute(insert(TimedEvent(id=3, happened_at=same_instant_utc)))
            await tx.execute(insert(TimedEvent(id=4, happened_at=later)))
            equal_ids = await tx.fetch_all(
                select(TimedEvent.id)
                .where(TimedEvent.happened_at.eq(same_instant_utc))
                .order_by(TimedEvent.id.asc()),
            )
            ordered_ids = await tx.fetch_all(
                select(TimedEvent.id)
                .all()
                .order_by(
                    TimedEvent.happened_at.asc(),
                    TimedEvent.id.asc(),
                ),
            )
            range_ids = await tx.fetch_all(
                select(TimedEvent.id)
                .where(TimedEvent.happened_at.gte(later))
                .order_by(TimedEvent.id.asc()),
            )
    finally:
        await database.close()

    assert_eq(equal_ids, [1, 2, 3])
    assert_eq(ordered_ids, [1, 2, 3, 4])
    assert_eq(range_ids, [4])

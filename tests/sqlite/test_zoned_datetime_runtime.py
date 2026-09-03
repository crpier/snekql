"""ZonedDatetime SQLite runtime behavior tests."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from snektest import assert_eq, assert_raises, test

from snekql.sqlite import (
    Fetched,
    Integer,
    Model,
    Pending,
    QueryConstructionError,
    Text,
    ZonedDatetime,
    insert,
    select,
)
from tests.helpers import initialized_database


class ZonedEvent[S = Pending](Model[S, "ZonedEvent[Fetched]"]):
    """Event whose datetime retains its civil timezone."""

    id: ZonedEvent.Col[int] = Integer(primary_key=True)
    happened_at: ZonedEvent.Col[ZonedDatetime] = Text(nullable=False)


@test(mark="medium")
async def zoned_datetime_round_trips_through_sqlite_text() -> None:
    """Insert and fetch retain an IANA zone and its ambiguous-time fold."""

    source = ZonedDatetime(
        datetime(
            2026,
            11,
            1,
            1,
            30,
            fold=1,
            tzinfo=ZoneInfo("America/New_York"),
        )
    )
    database = await initialized_database(database=":memory:", models=[ZonedEvent])
    try:
        async with database.transaction() as transaction:
            await transaction.execute(insert(ZonedEvent(id=1, happened_at=source)))
            fetched = await transaction.fetch_one(select(ZonedEvent).all())
    finally:
        await database.close()

    assert_eq(fetched.happened_at, source)
    assert_eq(fetched.happened_at.datetime.tzinfo, ZoneInfo("America/New_York"))
    assert_eq(fetched.happened_at.datetime.fold, 1)


@test(mark="medium")
async def zoned_datetime_fixed_offset_round_trips_through_sqlite_text() -> None:
    """Insert and fetch retain a fixed offset without an IANA key."""

    source = ZonedDatetime(
        datetime(
            2026,
            7,
            1,
            8,
            30,
            tzinfo=timezone(timedelta(hours=5, minutes=30)),
        )
    )
    database = await initialized_database(database=":memory:", models=[ZonedEvent])
    try:
        async with database.transaction() as transaction:
            await transaction.execute(insert(ZonedEvent(id=1, happened_at=source)))
            fetched = await transaction.fetch_one(select(ZonedEvent).all())
    finally:
        await database.close()

    assert_eq(fetched.happened_at, source)
    assert_eq(fetched.happened_at.datetime.tzinfo, source.datetime.tzinfo)


@test(mark="medium")
async def zoned_datetime_equality_requires_the_same_instant_and_timezone() -> None:
    """SQL equality distinguishes zones that currently share one instant."""

    new_york = ZonedDatetime(
        datetime(2026, 7, 1, 8, tzinfo=ZoneInfo("America/New_York"))
    )
    los_angeles = ZonedDatetime(
        datetime(2026, 7, 1, 5, tzinfo=ZoneInfo("America/Los_Angeles"))
    )
    database = await initialized_database(database=":memory:", models=[ZonedEvent])
    try:
        async with database.transaction() as transaction:
            await transaction.execute(
                insert(
                    [
                        ZonedEvent(id=1, happened_at=new_york),
                        ZonedEvent(id=2, happened_at=los_angeles),
                    ]
                )
            )
            matching_ids = await transaction.fetch_all(
                select(ZonedEvent.id).where(ZonedEvent.happened_at.eq(new_york))
            )
    finally:
        await database.close()

    assert_eq(matching_ids, [1])


@test(mark="fast")
def zoned_datetime_rejects_range_predicates() -> None:
    """A canonical zoned wire value has no meaningful lexical instant order."""

    value = ZonedDatetime(datetime(2026, 7, 1, 8, tzinfo=ZoneInfo("America/New_York")))

    with assert_raises(QueryConstructionError):
        _ = ZonedEvent.happened_at.gt(value)
    with assert_raises(QueryConstructionError):
        _ = ZonedEvent.happened_at.gte(value)
    with assert_raises(QueryConstructionError):
        _ = ZonedEvent.happened_at.lt(value)
    with assert_raises(QueryConstructionError):
        _ = ZonedEvent.happened_at.lte(value)
    with assert_raises(QueryConstructionError):
        _ = ZonedEvent.happened_at.gt_col(ZonedEvent.happened_at)
    with assert_raises(QueryConstructionError):
        _ = ZonedEvent.happened_at.gte_col(ZonedEvent.happened_at)
    with assert_raises(QueryConstructionError):
        _ = ZonedEvent.happened_at.lt_col(ZonedEvent.happened_at)
    with assert_raises(QueryConstructionError):
        _ = ZonedEvent.happened_at.lte_col(ZonedEvent.happened_at)


@test(mark="fast")
def zoned_datetime_rejects_between_predicates() -> None:
    """A zoned datetime cannot define SQL range bounds over canonical text."""

    value = ZonedDatetime(datetime(2026, 7, 1, 8, tzinfo=ZoneInfo("America/New_York")))

    with assert_raises(QueryConstructionError):
        _ = ZonedEvent.happened_at.between(value, value)


@test(mark="fast")
def zoned_datetime_rejects_sql_ordering() -> None:
    """Zoned canonical text cannot be exposed as chronological SQL ordering."""

    with assert_raises(QueryConstructionError):
        _ = ZonedEvent.happened_at.asc()
    with assert_raises(QueryConstructionError):
        _ = ZonedEvent.happened_at.desc()
    with assert_raises(QueryConstructionError):
        _ = ZonedEvent.happened_at.min()
    with assert_raises(QueryConstructionError):
        _ = ZonedEvent.happened_at.max()

"""ZonedDatetime MariaDB runtime behavior tests."""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from snektest import assert_eq, load_fixture, test

from snekql import mariadb
from snekql.mariadb import Fetched, Pending, ZonedDatetime, insert, select
from tests.helpers import initialized_database, provide_mariadb_server


@test(mark="medium")
async def zoned_datetime_round_trips_through_mariadb_text() -> None:
    """Insert and fetch retain an IANA zone and its ambiguous-time fold."""

    server = await load_fixture(provide_mariadb_server())

    class ZonedEvent[S = Pending](mariadb.Model[S, "ZonedEvent[Fetched]"]):
        """Event whose datetime retains its civil timezone."""

        id: ZonedEvent.Col[int] = mariadb.Integer(primary_key=True)
        happened_at: ZonedEvent.Col[ZonedDatetime] = mariadb.Text(nullable=False)

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
    database = await initialized_database(server.config(), models=[ZonedEvent])
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
async def zoned_datetime_equality_requires_the_same_instant_and_timezone() -> None:
    """MariaDB text equality distinguishes zones sharing one instant."""

    server = await load_fixture(provide_mariadb_server())

    class ZonedEvent[S = Pending](mariadb.Model[S, "ZonedEvent[Fetched]"]):
        """Event whose datetime retains its civil timezone."""

        id: ZonedEvent.Col[int] = mariadb.Integer(primary_key=True)
        happened_at: ZonedEvent.Col[ZonedDatetime] = mariadb.Text(nullable=False)

    new_york = ZonedDatetime(
        datetime(2026, 7, 1, 8, tzinfo=ZoneInfo("America/New_York"))
    )
    los_angeles = ZonedDatetime(
        datetime(2026, 7, 1, 5, tzinfo=ZoneInfo("America/Los_Angeles"))
    )
    database = await initialized_database(server.config(), models=[ZonedEvent])
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

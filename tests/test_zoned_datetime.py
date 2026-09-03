"""Timezone-preserving datetime logical type tests."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone, tzinfo
from zoneinfo import ZoneInfo

from snektest import assert_eq, assert_raises, test

from snekql.sqlite import ZonedDatetime, ZonedDatetimeError


class _UnsupportedTimezone(tzinfo):
    """Aware timezone without a stable persistence identity."""

    def utcoffset(self, _value: datetime | None) -> timedelta:
        return timedelta(hours=2)


@test(mark="fast")
def zoned_datetime_preserves_an_iana_timezone() -> None:
    """Construction retains the datetime's exact IANA timezone identity."""

    source = datetime(2026, 7, 1, 8, 30, tzinfo=ZoneInfo("America/New_York"))

    value = ZonedDatetime(source)

    assert_eq(value.datetime, source)
    assert_eq(value.datetime.tzinfo, ZoneInfo("America/New_York"))


@test(mark="fast")
def zoned_datetime_preserves_a_fixed_offset_timezone() -> None:
    """Fixed offsets have a stable identity without an IANA database key."""

    source = datetime(
        2026,
        7,
        1,
        8,
        30,
        tzinfo=timezone(timedelta(hours=5, minutes=30)),
    )

    value = ZonedDatetime(source)

    assert_eq(value.datetime, source)
    assert_eq(value.datetime.tzinfo, source.tzinfo)


@test(mark="fast")
def zoned_datetime_equality_includes_the_iana_timezone() -> None:
    """Equal instants in different IANA zones remain distinct values."""

    new_york = ZonedDatetime(
        datetime(2026, 7, 1, 8, tzinfo=ZoneInfo("America/New_York"))
    )
    los_angeles = ZonedDatetime(
        datetime(2026, 7, 1, 5, tzinfo=ZoneInfo("America/Los_Angeles"))
    )

    assert_eq(new_york == los_angeles, False)


@test(mark="fast")
def zoned_datetime_equality_accepts_the_same_instant_and_timezone() -> None:
    """Equivalent values compare and hash equally."""

    left = ZonedDatetime(datetime(2026, 7, 1, 8, tzinfo=ZoneInfo("America/New_York")))
    right = ZonedDatetime(datetime(2026, 7, 1, 8, tzinfo=ZoneInfo("America/New_York")))

    assert_eq(left, right)
    assert_eq(hash(left), hash(right))


@test(mark="fast")
def zoned_datetime_equality_distinguishes_iana_from_fixed_offset() -> None:
    """A named zone differs from a matching fixed offset at the same instant."""

    named = ZonedDatetime(datetime(2026, 7, 1, 8, tzinfo=ZoneInfo("America/New_York")))
    fixed = ZonedDatetime(datetime(2026, 7, 1, 8, tzinfo=timezone(timedelta(hours=-4))))

    assert_eq(named == fixed, False)


@test(mark="fast")
def zoned_datetime_equality_distinguishes_iana_aliases() -> None:
    """Two database keys remain distinct even when their zone rules match."""

    canonical = ZonedDatetime(
        datetime(2026, 7, 1, 8, tzinfo=ZoneInfo("America/New_York"))
    )
    alias = ZonedDatetime(datetime(2026, 7, 1, 8, tzinfo=ZoneInfo("US/Eastern")))

    assert_eq(canonical == alias, False)


@test(mark="fast")
def zoned_datetime_equality_includes_the_ambiguous_instant() -> None:
    """DST folds in one IANA zone identify two distinct instants."""

    timezone_info = ZoneInfo("America/New_York")
    earlier = ZonedDatetime(datetime(2026, 11, 1, 1, 30, fold=0, tzinfo=timezone_info))
    later = ZonedDatetime(datetime(2026, 11, 1, 1, 30, fold=1, tzinfo=timezone_info))

    assert_eq(earlier == later, False)


@test(mark="fast")
def zoned_datetime_rejects_a_naive_datetime() -> None:
    """A datetime without an offset cannot identify an instant or timezone."""

    with assert_raises(ZonedDatetimeError):
        _ = ZonedDatetime(datetime(2026, 7, 1, 8, 30))  # noqa: DTZ001


@test(mark="fast")
def zoned_datetime_rejects_a_nonexistent_iana_local_time() -> None:
    """A DST gap cannot round-trip with the same civil fields and instant."""

    nonexistent = datetime(
        2026,
        3,
        8,
        2,
        30,
        tzinfo=ZoneInfo("America/New_York"),
    )

    with assert_raises(ZonedDatetimeError):
        _ = ZonedDatetime(nonexistent)


@test(mark="fast")
def zoned_datetime_rejects_a_timezone_without_a_stable_identity() -> None:
    """Custom tzinfo implementations cannot be reconstructed after fetching."""

    with assert_raises(ZonedDatetimeError):
        _ = ZonedDatetime(datetime(2026, 7, 1, 8, 30, tzinfo=_UnsupportedTimezone()))

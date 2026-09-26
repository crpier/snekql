"""Datetime storage rejects timezone objects that do not supply an offset."""

from datetime import datetime, tzinfo
from typing import ClassVar

from snektest import assert_raises, test

from snekql import mariadb, sqlite


class UnknownOffset(tzinfo):
    """A timezone object can describe a naive datetime by returning None."""

    def utcoffset(self, _dt: datetime | None) -> None:
        return None


@test()
def utc_datetime_rejects_unknown_offset() -> None:
    """An attached tzinfo is not proof that an instant is timezone-aware."""

    class Event[State = sqlite.Pending](sqlite.Model[State]):
        __row_type__: ClassVar[sqlite.ReadType[Event[sqlite.Row]]]
        happened_at: sqlite.Col[sqlite.UtcDatetime] = sqlite.Text()

    with assert_raises(sqlite.ModelValidationError):
        Event(happened_at=datetime(2026, 1, 1, tzinfo=UnknownOffset()))


@test()
def native_datetime_rejects_unknown_offset() -> None:
    """MariaDB DateTime must not assume the machine's local timezone."""

    class Event[State = mariadb.Pending](mariadb.Model[State]):
        __row_type__: ClassVar[mariadb.ReadType[Event[mariadb.Row]]]
        happened_at: mariadb.Col[datetime] = mariadb.DateTime()

    event = Event(happened_at=datetime(2026, 1, 1, tzinfo=UnknownOffset()))

    with assert_raises(mariadb.ModelValidationError):
        mariadb.insert(event).compile()

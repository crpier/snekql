"""Curated temporal values reject inputs outside their representable ranges."""

from datetime import UTC, datetime, timedelta, timezone
from typing import ClassVar

from pydantic import TypeAdapter
from snektest import Param, assert_eq, assert_raises, test

from snekql import sqlite


@test(
    [Param(-(2**63), name="negative"), Param(2**63 - 1, name="positive")],
    mark="fast",
)
def duration_overflow_is_a_validation_error(milliseconds: int) -> None:
    """A valid SQL integer can still exceed Python's timedelta domain."""

    class Elapsed[S = sqlite.Pending](sqlite.Model[S]):
        __row_type__: ClassVar[sqlite.ReadType[Elapsed[sqlite.Row]]]
        duration: sqlite.Col[sqlite.Duration] = sqlite.Integer()

    with assert_raises(sqlite.ModelValidationError):
        # Exercise invalid wire milliseconds outside the typed constructor input.
        Elapsed(duration=milliseconds)  # ty: ignore[invalid-argument-type]


@test(
    [
        Param(datetime(1, 1, 1, tzinfo=timezone(timedelta(hours=1))), name="underflow"),
        Param(
            datetime(9999, 12, 31, 23, 59, tzinfo=timezone(-timedelta(hours=1))),
            name="overflow",
        ),
    ],
    mark="fast",
)
def zoned_datetime_rejects_unrepresentable_instants(value: datetime) -> None:
    """Accepted civil datetimes must also have hashable, serializable UTC instants."""
    with assert_raises(sqlite.ZonedDatetimeError):
        sqlite.ZonedDatetime(value)


@test(
    [
        Param(datetime(1, 1, 1, tzinfo=UTC), name="minimum"),
        Param(datetime.max.replace(tzinfo=UTC), name="maximum"),
    ],
    mark="fast",
)
def zoned_datetime_boundary_round_trip(value: datetime) -> None:
    """Representable UTC endpoints keep their identity through canonical text."""
    original = sqlite.ZonedDatetime(value)
    adapter = TypeAdapter(sqlite.ZonedDatetime)

    restored = adapter.validate_json(adapter.dump_json(original))

    assert_eq(restored.datetime, value)
    assert_eq(hash(restored), hash(original))

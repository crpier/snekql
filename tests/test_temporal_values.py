"""Datetime meaning is established by concrete value construction."""

from datetime import UTC, datetime, timedelta, timezone
from io import BytesIO
from struct import pack
from zoneinfo import ZoneInfo

from pydantic import TypeAdapter, ValidationError
from snektest import Param, assert_eq, assert_raises, test

from snekql import sqlite


@test(mark="fast")
def utc_construction_preserves_microseconds() -> None:
    """An offset-bearing input becomes UTC without losing fractional seconds."""
    instant = sqlite.UtcDatetime(
        datetime(2026, 1, 2, 13, 30, 0, 123456, tzinfo=timezone(timedelta(hours=2)))
    )

    assert_eq(instant.datetime, datetime(2026, 1, 2, 11, 30, 0, 123456, tzinfo=UTC))


@test(mark="fast")
def utc_json_round_trip_uses_canonical_microseconds() -> None:
    """JSON and database text carry fixed-width UTC values, including early years."""
    instant = sqlite.UtcDatetime(datetime(1, 1, 2, 3, 4, 5, 6, tzinfo=UTC))
    adapter = TypeAdapter(sqlite.UtcDatetime)

    encoded = adapter.dump_json(instant)

    assert_eq(encoded, b'"0001-01-02T03:04:05.000006Z"')
    assert_eq(adapter.validate_json(encoded), instant)


@test(mark="fast")
def local_construction_preserves_civil_fields() -> None:
    """Local civil values keep microseconds without inventing a timezone."""
    civil = datetime(2026, 1, 2, 9, 30, 0, 123456)  # noqa: DTZ001

    value = sqlite.LocalDatetime(civil)

    assert_eq(value.datetime, civil)


@test(mark="fast")
def local_json_round_trip_is_canonical() -> None:
    """Civil values have one fixed-width text representation without a zone."""
    value = sqlite.LocalDatetime(datetime(1, 1, 2, 3, 4, 5, 6))  # noqa: DTZ001
    adapter = TypeAdapter(sqlite.LocalDatetime)

    encoded = adapter.dump_json(value)

    assert_eq(encoded, b'"0001-01-02T03:04:05.000006"')
    assert_eq(adapter.validate_json(encoded), value)


@test(mark="fast")
def zoned_constructor_rejects_an_unrepresentable_instant() -> None:
    """A valid local date cannot produce an unhashable UTC value."""
    with assert_raises(sqlite.ZonedDatetimeError):
        sqlite.ZonedDatetime(datetime(1, 1, 1, tzinfo=timezone(timedelta(hours=1))))


@test(mark="fast")
def zoned_constructor_rejects_an_anonymous_zone() -> None:
    """A ZoneInfo without a key cannot be restored from persistent text."""
    tzif = (
        b"TZif\0"
        + b"\0" * 15
        + pack(">6l", 0, 0, 0, 0, 1, 4)
        + pack(">lbb", 0, 0, 0)
        + b"UTC\0"
    )
    zone = ZoneInfo.from_file(BytesIO(tzif))

    with assert_raises(sqlite.ZonedDatetimeError):
        sqlite.ZonedDatetime(datetime(2026, 1, 1, tzinfo=zone))


@test(
    [
        Param(datetime(2026, 1, 1), name="naive"),  # noqa: DTZ001
        Param(datetime(1, 1, 1, tzinfo=timezone(timedelta(hours=1))), name="underflow"),
        Param(
            datetime(9999, 12, 31, 23, 59, tzinfo=timezone(-timedelta(hours=1))),
            name="overflow",
        ),
    ],
    mark="fast",
)
def utc_constructor_rejects_invalid_instants(value: datetime) -> None:
    """An invalid instant fails without involving a model or database."""
    with assert_raises(sqlite.DatetimeError):
        sqlite.UtcDatetime(value)


@test(
    [
        Param(datetime(2026, 1, 1, tzinfo=UTC), name="aware"),
        Param(datetime(2026, 1, 1, fold=1), name="fold"),  # noqa: DTZ001
    ],
    mark="fast",
)
def local_constructor_rejects_instant_metadata(value: datetime) -> None:
    """Civil fields neither discard a zone nor promise a resolved DST occurrence."""
    with assert_raises(sqlite.DatetimeError):
        sqlite.LocalDatetime(value)


@test(
    [
        Param("2026-01-01T00:00:00.123Z", name="old-milliseconds"),
        Param("2026-01-01T00:00:00.123456+00:00", name="alternate-utc"),
        Param("2026-01-01T01:00:00.123456+01:00", name="offset"),
    ],
    mark="fast",
)
def utc_wire_reader_rejects_alternate_representations(wire: str) -> None:
    """Readers must not hide stored strings with different SQL comparison behavior."""
    with assert_raises(ValidationError):
        TypeAdapter(sqlite.UtcDatetime).validate_python(wire)


@test(mark="fast")
def strict_python_validation_does_not_implicitly_wrap_datetime() -> None:
    """Explicit construction, rather than Pydantic coercion, establishes meaning."""
    with assert_raises(ValidationError):
        TypeAdapter(sqlite.UtcDatetime).validate_python(datetime.now(UTC), strict=True)


@test(mark="fast")
def instants_compare_by_utc_without_losing_fractional_seconds() -> None:
    """UTC equality/hash agree across offsets while microseconds retain ordering."""
    early = sqlite.UtcDatetime(
        datetime(2026, 1, 1, 1, 0, 0, 123456, tzinfo=timezone(timedelta(hours=1)))
    )
    same = sqlite.UtcDatetime(datetime(2026, 1, 1, 0, 0, 0, 123456, tzinfo=UTC))
    later = sqlite.UtcDatetime(datetime(2026, 1, 1, 0, 0, 0, 123457, tzinfo=UTC))

    assert_eq(early, same)
    assert_eq(hash(early), hash(same))
    assert_eq(early < later, True)


@test(mark="fast")
def strict_zoned_python_input_does_not_decode_wire_text() -> None:
    """Strict Python input uses a value instance; JSON decoding is a separate path."""
    adapter = TypeAdapter(sqlite.ZonedDatetime)
    value = sqlite.ZonedDatetime(datetime(2026, 1, 1, tzinfo=UTC))
    wire = adapter.dump_python(value, mode="json")

    with assert_raises(ValidationError):
        adapter.validate_python(wire, strict=True)

    assert_eq(adapter.validate_json(adapter.dump_json(value)), value)


@test(mark="fast")
def zoned_wire_reader_rejects_noncanonical_text() -> None:
    """Decoder tolerance cannot repair equality over differently formatted SQL text."""
    adapter = TypeAdapter(sqlite.ZonedDatetime)
    value = sqlite.ZonedDatetime(datetime(2026, 1, 1, tzinfo=UTC))
    wire = adapter.dump_python(value, mode="json")

    with assert_raises(ValidationError):
        adapter.validate_python(wire.replace(",", ", "))

    assert_eq(adapter.validate_python(wire), value)


@test(
    [
        Param(
            '[1,"0001-01-01T00:00:00.000000Z","offset",-3600000000]', name="underflow"
        ),
        Param('[1,"9999-12-31T23:59:59.999999Z","offset",3600000000]', name="overflow"),
    ],
    mark="fast",
)
def zoned_wire_bounds_use_the_pydantic_error_contract(wire: str) -> None:
    """An unrepresentable local rendering is invalid data, not an arithmetic leak."""
    with assert_raises(ValidationError):
        TypeAdapter(sqlite.ZonedDatetime).validate_python(wire)

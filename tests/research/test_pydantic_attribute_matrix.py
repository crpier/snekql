"""Synthetic driver-form acceptance at the public TypeAdapter seam (#596).

These are not executions of SQLite, MariaDB or snekql Materialization.
"""

from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Annotated, TypeForm
from uuid import UUID

from pydantic import (
    AwareDatetime,
    Field,
    Json,
    StrictBool,
    StrictInt,
    TypeAdapter,
    ValidationError,
)
from snektest import Param, assert_eq, assert_raises, test

from tests.research.attribute_contracts import CanonicalSqlDate, SqlBool01


@dataclass(frozen=True)
class Reject:
    code: str


@dataclass(frozen=True)
class Probe:
    name: str
    contract: TypeForm[object]
    raw: object
    declared: object
    strict: object


DAY = date(2024, 2, 29)
INSTANT = datetime(2026, 10, 31, 9, 30, tzinfo=UTC)
NAIVE_FIELDS = INSTANT.replace(tzinfo=None)
IDENTIFIER = UUID("12345678-1234-4234-8234-123456789abc")
Age = Annotated[int, Field(ge=0, le=130)]

PROBES = (
    Probe("int-native", int, 42, 42, 42),
    Probe("int-text", int, "42", 42, Reject("int_type")),
    Probe("int-bool", int, True, 1, Reject("int_type")),
    Probe("int-integral-float", int, 42.0, 42, Reject("int_type")),
    Probe("int-fraction", int, 42.5, Reject("int_from_float"), Reject("int_type")),
    Probe("int-decimal", int, Decimal(42), 42, Reject("int_type")),
    Probe(
        "int-fractional-decimal",
        int,
        Decimal("42.5"),
        Reject("int_from_float"),
        Reject("int_type"),
    ),
    Probe("int-null", int, None, Reject("int_type"), Reject("int_type")),
    Probe("strict-int-text", StrictInt, "42", Reject("int_type"), Reject("int_type")),
    Probe("age-range", Age, 200, Reject("less_than_equal"), Reject("less_than_equal")),
    Probe("age-text", Age, "42", 42, Reject("int_type")),
    Probe("bool-native", bool, True, True, True),
    Probe("bool-one", bool, 1, True, Reject("bool_type")),
    Probe("bool-zero", bool, 0, False, Reject("bool_type")),
    Probe("bool-yes", bool, "yes", True, Reject("bool_type")),
    Probe("bool-two", bool, 2, Reject("bool_parsing"), Reject("bool_type")),
    Probe("strict-bool-one", StrictBool, 1, Reject("bool_type"), Reject("bool_type")),
    Probe("sql-bool-zero", SqlBool01, 0, False, False),
    Probe("sql-bool-native", SqlBool01, True, True, True),
    Probe("sql-bool-two", SqlBool01, 2, Reject("bool_type"), Reject("bool_type")),
    Probe("sql-bool-text", SqlBool01, "yes", Reject("bool_type"), Reject("bool_type")),
    Probe(
        "sql-bool-string-one", SqlBool01, "1", Reject("bool_type"), Reject("bool_type")
    ),
    Probe("sql-bool-float", SqlBool01, 1.0, Reject("bool_type"), Reject("bool_type")),
    Probe("sql-bool-null", SqlBool01, None, Reject("bool_type"), Reject("bool_type")),
    Probe("date-native", date, DAY, DAY, DAY),
    Probe("date-text", date, "2024-02-29", DAY, Reject("date_type")),
    Probe("date-midnight-text", date, "2024-02-29T00:00:00", DAY, Reject("date_type")),
    Probe(
        "date-native-midnight",
        date,
        datetime(2024, 2, 29, tzinfo=UTC).replace(tzinfo=None),
        DAY,
        Reject("date_type"),
    ),
    Probe("sql-date-native", CanonicalSqlDate, DAY, DAY, DAY),
    Probe(
        "sql-date-compact",
        CanonicalSqlDate,
        "20240229",
        Reject("value_error"),
        Reject("value_error"),
    ),
    Probe(
        "sql-date-midnight",
        CanonicalSqlDate,
        "2024-02-29T00:00:00",
        Reject("value_error"),
        Reject("value_error"),
    ),
    Probe(
        "sql-date-native-datetime",
        CanonicalSqlDate,
        NAIVE_FIELDS,
        Reject("date_type"),
        Reject("date_type"),
    ),
    Probe(
        "sql-date-zero",
        CanonicalSqlDate,
        "0000-00-00",
        Reject("value_error"),
        Reject("value_error"),
    ),
    Probe(
        "datetime-text",
        datetime,
        "2026-10-31T09:30:00Z",
        INSTANT,
        Reject("datetime_type"),
    ),
    Probe("datetime-native", datetime, NAIVE_FIELDS, NAIVE_FIELDS, NAIVE_FIELDS),
    Probe(
        "aware-datetime-naive",
        AwareDatetime,
        NAIVE_FIELDS,
        Reject("timezone_aware"),
        Reject("timezone_aware"),
    ),
    Probe(
        "aware-datetime-text",
        AwareDatetime,
        "2026-10-31T09:30:00Z",
        INSTANT,
        Reject("datetime_type"),
    ),
    Probe("uuid-native", UUID, IDENTIFIER, IDENTIFIER, IDENTIFIER),
    Probe("uuid-text", UUID, str(IDENTIFIER), IDENTIFIER, Reject("is_instance_of")),
    Probe("uuid-hex", UUID, IDENTIFIER.hex, IDENTIFIER, Reject("is_instance_of")),
    Probe("uuid-bytes", UUID, IDENTIFIER.bytes, IDENTIFIER, Reject("is_instance_of")),
    Probe(
        "uuid-invalid",
        UUID,
        "not-a-uuid",
        Reject("uuid_parsing"),
        Reject("is_instance_of"),
    ),
    Probe("list-json-text", list[int], "[7]", Reject("list_type"), Reject("list_type")),
    Probe("list-python-text-item", list[int], ["7"], [7], Reject("int_type")),
    Probe("json-integers", Json[list[int]], "[7]", [7], [7]),
    Probe("json-text-item", Json[list[int]], '["7"]', [7], Reject("int_type")),
    Probe("json-bool-item", Json[list[int]], "[true]", [1], Reject("int_type")),
    Probe(
        "json-strict-item",
        Json[list[StrictInt]],
        '["7"]',
        Reject("int_type"),
        Reject("int_type"),
    ),
    Probe(
        "json-malformed",
        Json[list[int]],
        "[",
        Reject("json_invalid"),
        Reject("json_invalid"),
    ),
    Probe(
        "json-python-list",
        Json[list[int]],
        [7],
        Reject("json_type"),
        Reject("json_type"),
    ),
    Probe("json-bytes", Json[list[int]], b"[7]", [7], [7]),
    Probe("json-inner-null", Json[list[int] | None], "null", None, None),
    Probe(
        "json-inner-null-sql-null",
        Json[list[int] | None],
        None,
        Reject("json_type"),
        Reject("json_type"),
    ),
    Probe("json-outer-null", Json[list[int]] | None, None, None, None),
    Probe(
        "json-outer-null-json-null",
        Json[list[int]] | None,
        "null",
        Reject("list_type"),
        Reject("list_type"),
    ),
    Probe("json-date", Json[date], '"2024-02-29"', DAY, DAY),
    Probe(
        "json-uuid",
        Json[UUID],
        '"12345678-1234-4234-8234-123456789abc"',
        IDENTIFIER,
        IDENTIFIER,
    ),
)


@test(
    [Param(probe, name=probe.name) for probe in PROBES],
    [Param("declared", name="declared"), Param("strict", name="strict")],
    mark="fast",
)
def contract_acceptance_matches_explicit_examples(probe: Probe, mode: str) -> None:
    """Acceptance, output runtime type and fixed mismatch code are independently specified."""
    adapter = TypeAdapter(probe.contract)
    expected = probe.strict if mode == "strict" else probe.declared
    strict = True if mode == "strict" else None
    if isinstance(expected, Reject):
        with assert_raises(ValidationError) as raised:
            adapter.validate_python(probe.raw, strict=strict)
        errors = raised.exception.errors(include_input=False, include_context=False)
        assert_eq([error["type"] for error in errors], [expected.code])
        return

    actual = adapter.validate_python(probe.raw, strict=strict)
    assert_eq(actual, expected)
    assert_eq(type(actual), type(expected))
    if isinstance(actual, list) and isinstance(expected, list):
        assert_eq(tuple(map(type, actual)), tuple(map(type, expected)))

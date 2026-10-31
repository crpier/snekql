"""Construction versus read representation, without Table Models or SQL (#596)."""

from datetime import UTC, datetime, timedelta
from typing import Annotated

from pydantic import (
    AfterValidator,
    BeforeValidator,
    Field,
    Json,
    StrictBool,
    StrictInt,
    TypeAdapter,
    ValidationError,
)
from snektest import Param, assert_eq, assert_raises, test

from snekql.sqlite import LocalDatetime, UtcDatetime
from tests.research.input_contracts import (
    SQL_CELL_READ,
    civil_fields,
    contextual_bool01,
    sql_bool01,
    utc_fields,
    utc_text,
)

INSTANT = datetime(2026, 10, 31, 9, 30, 0, 123456, tzinfo=UTC)
FIELDS = INSTANT.replace(tzinfo=None)
WIRE = "2026-10-31T09:30:00.123456Z"


def _recent(value: UtcDatetime) -> UtcDatetime:
    if value.datetime.year < 2026:
        msg = "expected an instant in 2026 or later"
        raise ValueError(msg)
    return value


RecentUtc = Annotated[UtcDatetime, AfterValidator(_recent)]


@test([Param("declared", name="declared"), Param("strict", name="strict")], mark="fast")
def boolean_read_policy_does_not_broaden_application_input(mode: str) -> None:
    """A read-only representation rule composes with the unchanged logical type."""
    application = TypeAdapter(StrictBool)
    read = TypeAdapter(Annotated[StrictBool, BeforeValidator(sql_bool01)])

    value = read.validate_python(1, strict=True if mode == "strict" else None)

    assert_eq(value, True)
    assert_eq(type(value), bool)
    with assert_raises(ValidationError):
        application.validate_python(1, strict=True)


@test([Param("declared", name="declared"), Param("strict", name="strict")], mark="fast")
def utc_text_read_keeps_construction_nominal(mode: str) -> None:
    """Storage text is explicit; application validation still requires a value object."""
    application = TypeAdapter(RecentUtc)
    read = TypeAdapter(Annotated[RecentUtc, BeforeValidator(utc_text)])

    value = read.validate_python(WIRE, strict=True if mode == "strict" else None)

    assert_eq(type(value), UtcDatetime)
    assert_eq(value.datetime, INSTANT)
    assert_eq(application.validate_python(UtcDatetime(INSTANT), strict=True), value)
    with assert_raises(ValidationError):
        application.validate_python(WIRE, strict=True)


@test([Param("declared", name="declared"), Param("strict", name="strict")], mark="fast")
def native_fields_get_only_the_explicitly_selected_utc_meaning(mode: str) -> None:
    """Raw timezone-free fields are accepted only by this explicit UTC read policy."""
    application = TypeAdapter(RecentUtc)
    read = TypeAdapter(Annotated[RecentUtc, BeforeValidator(utc_fields)])

    value = read.validate_python(FIELDS, strict=True if mode == "strict" else None)

    assert_eq(type(value), UtcDatetime)
    assert_eq(value.datetime, INSTANT)
    with assert_raises(ValidationError):
        application.validate_python(FIELDS, strict=True)


@test([Param("declared", name="declared"), Param("strict", name="strict")], mark="fast")
def same_native_fields_can_explicitly_remain_civil(mode: str) -> None:
    """The storage primitive alone cannot select an instant rather than civil fields."""
    application = TypeAdapter(LocalDatetime)
    read = TypeAdapter(Annotated[LocalDatetime, BeforeValidator(civil_fields)])

    value = read.validate_python(FIELDS, strict=True if mode == "strict" else None)

    assert_eq(type(value), LocalDatetime)
    assert_eq(value.datetime, FIELDS)
    assert_eq(value.datetime.tzinfo, None)
    with assert_raises(ValidationError):
        application.validate_python(FIELDS, strict=True)


@test([Param("declared", name="declared"), Param("strict", name="strict")], mark="fast")
def context_selects_read_input_without_mutating_the_adapter(mode: str) -> None:
    """One adapter can distinguish phases when the caller explicitly supplies context."""
    adapter = TypeAdapter(Annotated[StrictBool, BeforeValidator(contextual_bool01)])
    strict = True if mode == "strict" else None
    with assert_raises(ValidationError):
        adapter.validate_python(1, strict=True)

    value = adapter.validate_python(1, strict=strict, context=SQL_CELL_READ)

    assert_eq(value, True)
    assert_eq(type(value), bool)
    with assert_raises(ValidationError):
        adapter.validate_python(1, strict=True)


@test([Param("declared", name="declared"), Param("strict", name="strict")], mark="fast")
def sharing_the_entire_read_annotation_also_broadens_application_input(
    mode: str,
) -> None:
    """A SQL-input validator cannot know it is constructing an application value."""
    shared = TypeAdapter(Annotated[StrictBool, BeforeValidator(sql_bool01)])

    value = shared.validate_python(1, strict=True if mode == "strict" else None)

    assert_eq(value, True)
    assert_eq(type(value), bool)


@test(
    [
        Param(value, name=name)
        for name, value in (
            ("two", 2),
            ("text-one", "1"),
            ("yes", "yes"),
            ("float", 1.0),
            ("null", None),
        )
    ],
    [Param("declared", name="declared"), Param("strict", name="strict")],
    mark="fast",
)
def boolean_read_policy_rejects_unselected_representations(
    value: object, mode: str
) -> None:
    read = TypeAdapter(Annotated[StrictBool, BeforeValidator(sql_bool01)])

    with assert_raises(ValidationError):
        read.validate_python(value, strict=True if mode == "strict" else None)


@test([Param("declared", name="declared"), Param("strict", name="strict")], mark="fast")
def logical_temporal_constraint_is_preserved_for_all_inputs(mode: str) -> None:
    """One application-owned rule still rejects old instants on both read routes."""
    application = TypeAdapter(RecentUtc)
    text = TypeAdapter(Annotated[RecentUtc, BeforeValidator(utc_text)])
    native = TypeAdapter(Annotated[RecentUtc, BeforeValidator(utc_fields)])
    strict = True if mode == "strict" else None
    old = datetime(2025, 1, 2, 9, 30, tzinfo=UTC)

    with assert_raises(ValidationError):
        application.validate_python(UtcDatetime(old), strict=True)
    with assert_raises(ValidationError):
        text.validate_python("2025-01-02T09:30:00.000000Z", strict=strict)
    with assert_raises(ValidationError):
        native.validate_python(old.replace(tzinfo=None), strict=strict)


@test(
    [
        Param(value, name=name)
        for name, value in (
            ("milliseconds", "2026-10-31T09:30:00.123Z"),
            ("alternate-utc", "2026-10-31T09:30:00.123456+00:00"),
            ("bare-fields", FIELDS),
            ("null", None),
        )
    ],
    [Param("declared", name="declared"), Param("strict", name="strict")],
    mark="fast",
)
def temporal_text_read_rejects_noncanonical_or_unselected_inputs(
    value: object, mode: str
) -> None:
    read = TypeAdapter(Annotated[RecentUtc, BeforeValidator(utc_text)])

    with assert_raises(ValidationError):
        read.validate_python(value, strict=True if mode == "strict" else None)


@test(
    [
        Param(value, name=name)
        for name, value in (
            ("aware", INSTANT),
            ("fold", FIELDS.replace(fold=1)),
            ("null", None),
        )
    ],
    [Param("declared", name="declared"), Param("strict", name="strict")],
    mark="fast",
)
def native_temporal_policies_do_not_discard_instant_or_fold_metadata(
    value: object, mode: str
) -> None:
    utc = TypeAdapter(Annotated[RecentUtc, BeforeValidator(utc_fields)])
    civil = TypeAdapter(Annotated[LocalDatetime, BeforeValidator(civil_fields)])
    strict = True if mode == "strict" else None

    with assert_raises(ValidationError):
        utc.validate_python(value, strict=strict)
    with assert_raises(ValidationError):
        civil.validate_python(value, strict=strict)


def _append_marker(value: list[int]) -> list[int]:
    return [*value, 99]


def _exclude_thirteen(value: list[int]) -> list[int]:
    if 13 in value:
        msg = "thirteen is excluded by the application contract"
        raise ValueError(msg)
    return value


Payload = Annotated[
    list[StrictInt],
    Field(min_length=1, max_length=2),
    AfterValidator(_exclude_thirteen),
]


@test([Param("declared", name="declared"), Param("strict", name="strict")], mark="fast")
def json_entry_points_share_the_complete_payload_contract(mode: str) -> None:
    """The grammar changes without replacing field/element/custom constraints."""
    adapter = TypeAdapter(Payload)
    strict = True if mode == "strict" else None

    assert_eq(adapter.validate_python([7], strict=True), [7])
    assert_eq(adapter.validate_json("[7]", strict=strict), [7])
    with assert_raises(ValidationError):
        adapter.validate_python("[7]", strict=True)
    with assert_raises(ValidationError):
        TypeAdapter(Json[Payload]).validate_python([7], strict=strict)


@test(
    [
        Param(pair, name=name)
        for name, pair in (
            ("empty", ([], "[]")),
            ("too-long", ([7, 8, 9], "[7,8,9]")),
            ("custom-rule", ([13], "[13]")),
            ("text-element", (["7"], '["7"]')),
            ("bool-element", ([True], "[true]")),
        )
    ],
    [Param("declared", name="declared"), Param("strict", name="strict")],
    mark="fast",
)
def both_json_entry_points_enforce_logical_constraints(
    pair: tuple[object, str], mode: str
) -> None:
    adapter = TypeAdapter(Payload)
    python_input, json_input = pair

    with assert_raises(ValidationError):
        adapter.validate_python(python_input, strict=True)
    with assert_raises(ValidationError):
        adapter.validate_json(json_input, strict=True if mode == "strict" else None)


@test([Param("declared", name="declared"), Param("strict", name="strict")], mark="fast")
def json_entry_points_do_not_revalidate_the_completed_logical_value(mode: str) -> None:
    """A deliberate non-idempotent validator makes accidental double parsing visible."""
    adapter = TypeAdapter(Annotated[list[StrictInt], AfterValidator(_append_marker)])

    assert_eq(adapter.validate_python([7], strict=True), [7, 99])
    assert_eq(
        adapter.validate_json("[7]", strict=True if mode == "strict" else None), [7, 99]
    )


def _next_second(value: UtcDatetime) -> UtcDatetime:
    return UtcDatetime(value.datetime + timedelta(seconds=1))


@test([Param("declared", name="declared"), Param("strict", name="strict")], mark="fast")
def composed_read_applies_the_logical_after_validator_once(mode: str) -> None:
    logical = Annotated[UtcDatetime, AfterValidator(_next_second)]
    application = TypeAdapter(logical)
    read = TypeAdapter(Annotated[logical, BeforeValidator(utc_text)])
    expected = datetime(2026, 10, 31, 9, 30, 1, 123456, tzinfo=UTC)

    assert_eq(
        application.validate_python(UtcDatetime(INSTANT), strict=True).datetime,
        expected,
    )
    assert_eq(
        read.validate_python(WIRE, strict=True if mode == "strict" else None).datetime,
        expected,
    )


@test([Param("declared", name="declared"), Param("strict", name="strict")], mark="fast")
def sql_read_context_also_reaches_reused_contracts_inside_json(mode: str) -> None:
    """A single phase token is not a selective top-level SQL-cell grammar."""
    contextual = Annotated[StrictBool, BeforeValidator(contextual_bool01)]
    adapter = TypeAdapter(list[contextual])
    strict = True if mode == "strict" else None
    with assert_raises(ValidationError):
        adapter.validate_json("[1]", strict=strict)

    assert_eq(
        adapter.validate_json("[1]", strict=strict, context=SQL_CELL_READ), [True]
    )

    # A read-only outer adapter leaves the reusable logical Boolean unchanged.
    with assert_raises(ValidationError):
        TypeAdapter(list[StrictBool]).validate_json("[1]", strict=strict)


@test(mark="fast")
def read_conversion_adds_to_rather_than_erases_the_base_declared_policy() -> None:
    """A native-field converter alone is not an exact storage-carrier whitelist."""
    read = TypeAdapter(Annotated[RecentUtc, BeforeValidator(utc_fields)])

    assert_eq(read.validate_python(WIRE, strict=None).datetime, INSTANT)
    with assert_raises(ValidationError):
        read.validate_python(WIRE, strict=True)

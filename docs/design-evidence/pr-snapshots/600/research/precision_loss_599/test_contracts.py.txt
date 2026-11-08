"""Isolated public Pydantic probes for #599; no database or model execution."""

from datetime import UTC, datetime
from decimal import Decimal, localcontext
from typing import Annotated

from pydantic import (
    AfterValidator,
    Field,
    PlainSerializer,
    TypeAdapter,
    ValidationError,
)
from snektest import (
    Param,
    assert_eq,
    assert_is,
    assert_isinstance,
    assert_ne,
    assert_raises,
    test,
)

from research.precision_loss_599.policies import (
    require_decimal_5_2,
    require_milliseconds,
)

Amount = Annotated[Decimal, Field(strict=True, max_digits=5, decimal_places=2)]
MillisecondDatetime = Annotated[
    datetime, Field(strict=True), AfterValidator(require_milliseconds)
]


@test(mark="fast")
def test_final_decimal_parameter_rejects_lossy_serializer_output() -> None:
    with assert_raises(ValueError):
        require_decimal_5_2("1.234")


@test(mark="fast")
def test_datetime_contract_rejects_fraction_that_would_be_lost() -> None:
    with assert_raises(ValidationError):
        TypeAdapter(MillisecondDatetime).validate_python(
            datetime(2026, 1, 1, microsecond=123456, tzinfo=UTC)
        )


@test(
    [
        Param(name=value, value=value)
        for value in ("1.23", "1.2300", "999.99", "0E-100")
    ],
    mark="fast",
)
def test_existing_decimal_constraints_accept_exact_fit(value: str) -> None:
    result = TypeAdapter(Amount).validate_python(Decimal(value))
    assert_eq(result, Decimal(value))


@test(
    [Param(name=value, value=value) for value in ("1.234", "1000", "NaN", "Infinity")],
    mark="fast",
)
def test_existing_decimal_constraints_reject_nonfit(value: str) -> None:
    with assert_raises(ValidationError):
        TypeAdapter(Amount).validate_python(Decimal(value))


@test(mark="fast")
def test_strict_decimal_rejects_float_before_it_can_hide_intent() -> None:
    with assert_raises(ValidationError):
        TypeAdapter(Amount).validate_python(1.23)


@test(mark="fast")
def test_validation_does_not_constrain_custom_serializer_output() -> None:
    serialized_amount = Annotated[
        Amount,
        PlainSerializer(lambda _: "1.234", return_type=str),
    ]
    adapter = TypeAdapter(serialized_amount)
    value = adapter.validate_python(Decimal("1.23"))
    assert_eq(adapter.dump_python(value, mode="json", warnings="error"), "1.234")


@test(mark="fast")
def test_datetime_contract_does_not_enforce_column_milliseconds() -> None:
    value = datetime(2026, 1, 1, microsecond=123456, tzinfo=UTC)
    assert_eq(TypeAdapter(datetime).validate_python(value, strict=True), value)


@test(mark="fast")
def test_decimal_text_dump_preserves_number_but_not_canonical_equality() -> None:
    adapter = TypeAdapter(Decimal)
    left = adapter.dump_python(Decimal("1.50"), mode="json")
    right = adapter.dump_python(Decimal("1.5"), mode="json")
    assert_eq(left, "1.50")
    assert_eq(right, "1.5")
    assert_eq(adapter.validate_python(left), adapter.validate_python(right))


@test(
    [Param(name=str(value), value=value) for value in (0, 123000, 999000)],
    mark="fast",
)
def test_millisecond_contract_keeps_valid_datetime_unchanged(value: int) -> None:
    original = datetime(2026, 1, 1, microsecond=value, tzinfo=UTC)
    result = TypeAdapter(MillisecondDatetime).validate_python(original)
    assert_is(result, original)


@test(mark="fast")
def test_millisecond_contract_rejects_application_text() -> None:
    with assert_raises(ValidationError):
        TypeAdapter(MillisecondDatetime).validate_python("2026-01-01T00:00:00.123Z")


@test(mark="fast")
def test_datetime_serializer_can_bypass_logical_precision_policy() -> None:
    serialized_datetime = Annotated[
        MillisecondDatetime,
        PlainSerializer(
            lambda _: datetime(2026, 1, 1, microsecond=123456, tzinfo=UTC),
            return_type=datetime,
        ),
    ]
    adapter = TypeAdapter(serialized_datetime)
    valid = adapter.validate_python(
        datetime(2026, 1, 1, microsecond=123000, tzinfo=UTC)
    )
    parameter = adapter.dump_python(valid, mode="python", warnings="error")
    assert_isinstance(parameter, datetime)
    with assert_raises(ValueError):
        require_milliseconds(
            TypeAdapter(datetime).validate_python(parameter, strict=True)
        )


@test(
    [Param(name=value, value=value) for value in ("1.2300", "-999.99", "0E-100")],
    mark="fast",
)
def test_final_decimal_parameter_check_preserves_text(value: str) -> None:
    assert_is(require_decimal_5_2(value), value)


@test(
    [Param(name=str(value), value=value) for value in (1.23, True, 123)],
    mark="fast",
)
def test_final_decimal_parameter_policy_rejects_unsupported_representations(
    value: object,
) -> None:
    with assert_raises(TypeError):
        require_decimal_5_2(value)


@test(mark="fast")
def test_decimal_float_conversion_already_loses_digits_before_validation() -> None:
    original = Decimal("0.12345678901234567890123456789")
    restored = TypeAdapter(Decimal).validate_python(float(original))
    assert_ne(restored, original)


@test(mark="fast")
def test_text_recipe_retains_more_than_binary_float_precision() -> None:
    adapter = TypeAdapter(Annotated[Decimal, Field(allow_inf_nan=False)])
    original = Decimal("0.12345678901234567890123456789")
    parameter = adapter.dump_python(original, mode="json", warnings="error")
    assert_eq(parameter, "0.12345678901234567890123456789")
    assert_eq(adapter.validate_python(parameter), original)


@test(mark="fast")
def test_text_recipe_does_not_provide_numeric_ordering() -> None:
    adapter = TypeAdapter(Decimal)
    ten = adapter.dump_python(Decimal(10), mode="json")
    nine = adapter.dump_python(Decimal(9), mode="json")
    assert_eq(ten, "10")
    assert_eq(nine, "9")
    assert_eq(sorted([ten, nine]), ["10", "9"])
    assert_eq(sorted([Decimal(10), Decimal(9)]), [Decimal(9), Decimal(10)])


@test(mark="fast")
def test_integer_minor_units_recipe_checks_signed_64_bit_range() -> None:
    minor_units = TypeAdapter(
        Annotated[int, Field(strict=True, ge=-(2**63), le=2**63 - 1)]
    )
    assert_eq(minor_units.validate_python(123), 123)
    with assert_raises(ValidationError):
        minor_units.validate_python(2**63)
    with assert_raises(ValidationError):
        minor_units.validate_python(1.23)


@test(mark="fast")
def test_decimal_constraints_under_low_context_precision() -> None:
    with localcontext() as context:
        context.prec = 2
        with assert_raises(ValidationError):
            TypeAdapter(Amount).validate_python(Decimal("1.234"))

"""Public TypeAdapter evidence for #596; synthetic inputs, not backend results."""

from datetime import date

from pydantic import TypeAdapter, ValidationError
from snektest import Param, assert_eq, assert_raises, test

from tests.research.attribute_contracts import CanonicalSqlDate, SqlBool01


@test([Param("declared", name="declared"), Param("strict", name="strict")], mark="fast")
def explicit_boolean_contract_accepts_integer_one(mode: str) -> None:
    """An explicitly permitted SQL representation survives strict validation."""
    value = TypeAdapter(SqlBool01).validate_python(
        1, strict=True if mode == "strict" else None
    )

    assert_eq(value, True)
    assert_eq(type(value), bool)


@test([Param("declared", name="declared"), Param("strict", name="strict")], mark="fast")
def explicit_date_contract_accepts_canonical_text(mode: str) -> None:
    """Storage representation is explicit, not inferred by strictness or backend."""
    value = TypeAdapter(CanonicalSqlDate).validate_python(
        "2024-02-29", strict=True if mode == "strict" else None
    )

    assert_eq(value, date(2024, 2, 29))
    assert_eq(type(value), date)


@test([Param("declared", name="declared"), Param("strict", name="strict")], mark="fast")
def one_payload_contract_validates_python_and_json_inputs(mode: str) -> None:
    """Different input grammars need not duplicate logical payload policy."""
    adapter = TypeAdapter(list[int])
    strict = True if mode == "strict" else None

    assert_eq(adapter.validate_python([7], strict=strict), [7])
    assert_eq(adapter.validate_json("[7]", strict=strict), [7])
    with assert_raises(ValidationError):
        adapter.validate_python("[7]", strict=strict)

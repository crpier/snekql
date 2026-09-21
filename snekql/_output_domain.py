"""Logical SQL output domains, independent of application result validators."""

from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

from snekql._value_expression import ValueExpression
from snekql.errors import QueryConstructionError
from snekql.expressions import _Aggregate
from snekql.storage import (
    Attr,
    _extract_logical_type,
    _resolve_model_hint,
    _strip_json_marker,
)


@dataclass(frozen=True, slots=True)
class OutputDomain:
    """Known logical values and SQL nullability; None means nullability is unknown."""

    logical: object = Any
    nullable: bool | None = None


@runtime_checkable
class DomainOutput(Protocol):
    """Readonly references retain their defining SQL expression's domain."""

    def __output_domain__(self) -> OutputDomain: ...


def output_domain(operand: object) -> OutputDomain:
    """Resolve known domains without running validators or assuming wire types."""
    if isinstance(operand, Attr):
        if operand.owner is None or operand.name is None:
            msg = "named projections require bound columns"
            raise QueryConstructionError(msg)
        logical = _strip_json_marker(
            _extract_logical_type(
                _resolve_model_hint(operand.owner, operand.name), operand.name
            )
        )
        return OutputDomain(logical, operand.nullable)
    if isinstance(operand, ValueExpression):
        return OutputDomain(operand.value_type, operand.nullable)
    if isinstance(operand, _Aggregate):
        return _aggregate_domain(operand)
    if isinstance(operand, DomainOutput):
        return operand.__output_domain__()
    return OutputDomain()


def _aggregate_domain(operand: _Aggregate[Any, Any]) -> OutputDomain:
    """COUNT is stable; other aggregates can return NULL on empty input."""
    if operand.func == "COUNT":
        return OutputDomain(int, nullable=False)
    if operand.func == "AVG":
        return OutputDomain(float, nullable=True)
    return OutputDomain(output_domain(operand.column).logical, nullable=True)

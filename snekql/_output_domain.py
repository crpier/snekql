"""Logical SQL output domains, independent of application result validators."""

lazy from dataclasses import dataclass
lazy from types import UnionType
lazy from typing import (
    Any,
    Protocol,
    TypeAliasType,
    Union,
    get_args,
    get_origin,
    runtime_checkable,
)

lazy from snekql._value_expression import ValueExpression
lazy from snekql.errors import QueryConstructionError
lazy from snekql.expressions import _Aggregate
lazy from snekql.storage import (
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


def _aggregate_domain(operand: _Aggregate[Any, Any]) -> OutputDomain:
    """COUNT is stable; other aggregates can return NULL on empty input."""
    if operand.func == "COUNT":
        return OutputDomain(int, nullable=False)
    if operand.func == "AVG":
        return OutputDomain(float, nullable=True)
    return OutputDomain(output_domain(operand.column).logical, nullable=True)


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


def nonnull_output_annotation(annotation: object, remaining: int = 64) -> object:
    """Remove only field-level optionality, never validators or JSON markers."""
    if remaining <= 0:
        msg = "UNION requires a resolvable output domain"
        raise QueryConstructionError(msg)
    if isinstance(annotation, TypeAliasType) and not annotation.__type_params__:
        return nonnull_output_annotation(annotation.__value__, remaining - 1)
    if get_origin(annotation) in (Union, UnionType):
        members = tuple(item for item in get_args(annotation) if item is not type(None))
        if len(members) == 1:
            return nonnull_output_annotation(members[0], remaining - 1)
    return annotation

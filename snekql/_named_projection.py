"""Named result contracts independent from table declarations."""

from dataclasses import dataclass
from types import UnionType
from typing import Any, Literal, TypeAliasType, Union, get_args, get_origin

from pydantic import BaseModel

from snekql.errors import ModelValidationError, QueryConstructionError
from snekql.expressions import _Aggregate
from snekql.storage import (
    Attr,
    _annotation_admits_none,
    _extract_logical_type,
    _resolve_model_hint,
    _strip_json_marker,
    _unwrap_annotated,
)


def _annotation_members(annotation: object) -> tuple[object, ...]:
    """Reduce unions and literal constraints to their possible logical domains."""
    if isinstance(annotation, TypeAliasType) and not annotation.__type_params__:
        return (annotation.__value__,)
    if get_origin(annotation) is Literal:
        return tuple(type(value) for value in get_args(annotation))
    if get_origin(annotation) in (Union, UnionType):
        return get_args(annotation)
    return ()


def _accepts_annotation(source: object, target: object, remaining: int = 64) -> bool:
    """Compare logical domains; value constraints remain runtime validation."""
    source, target = _unwrap_annotated(source), _unwrap_annotated(target)
    if remaining <= 0 or target is Any or source is Any or source == target:
        return True
    if members := _annotation_members(source):
        return all(
            _accepts_annotation(member, target, remaining - 1) for member in members
        )
    if members := _annotation_members(target):
        return any(
            _accepts_annotation(source, member, remaining - 1) for member in members
        )
    if get_origin(source) is not None and get_origin(source) == get_origin(target):
        source_args, target_args = get_args(source), get_args(target)
        return len(source_args) == len(target_args) and all(
            _accepts_annotation(left, right, remaining - 1)
            for left, right in zip(source_args, target_args, strict=True)
        )
    if source in (bool, int) and target in (int, float):
        return source is int
    source_class, target_class = (
        get_origin(source) or source,
        get_origin(target) or target,
    )
    # Opaque and specialized alias domains defer to strict result validation.
    return not (
        isinstance(source_class, type) and isinstance(target_class, type)
    ) or issubclass(source_class, target_class)


@dataclass(frozen=True)
class NamedProjection:
    """Bind ordered SQL output labels to one application result contract."""

    labels: tuple[str, ...]
    result_type: type[BaseModel]

    def check_binding(self, label: str, operand: object, *, nullable: bool) -> None:
        """Check known source domains; opaque expression values validate on fetch."""
        logical: object = Any
        if isinstance(operand, _Aggregate):
            nullable = nullable or operand.func != "COUNT"
            if operand.func == "COUNT":
                logical = int
            elif operand.func == "AVG":
                logical = float
            else:
                operand = operand.column
        if isinstance(operand, Attr):
            if operand.owner is None or operand.name is None:
                msg = "named projections require bound columns"
                raise QueryConstructionError(msg)
            logical = _strip_json_marker(
                _extract_logical_type(
                    _resolve_model_hint(operand.owner, operand.name), operand.name
                )
            )
            nullable = nullable or operand.nullable
        target = self.result_type.model_fields[label].annotation
        admits_none = (
            _annotation_admits_none(target) is not False
            if isinstance(get_origin(target), TypeAliasType)
            else _accepts_annotation(type(None), target)
        )
        if not _accepts_annotation(logical, target) or (nullable and not admits_none):
            msg = "projection binding is incompatible with its result field"
            raise QueryConstructionError(msg)

    def materialize(self, values: tuple[object, ...]) -> BaseModel:
        """Validate decoded logical values without implicit type coercion."""
        if len(values) != len(self.labels):
            msg = "named result width does not match its contract"
            raise ModelValidationError(msg)
        try:
            row = self.result_type.model_validate(
                dict(zip(self.labels, values, strict=True)),
                strict=True,
                by_alias=False,
                by_name=True,
            )
        except Exception:
            msg = "named result failed contract validation"
            raise ModelValidationError(msg) from None
        if not isinstance(row, self.result_type):
            msg = "named result validator did not return its declared model"
            raise ModelValidationError(msg)
        return row

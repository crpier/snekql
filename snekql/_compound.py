"""Named set contracts and immutable binary query construction."""

from dataclasses import replace
from types import UnionType
from typing import Any, Literal, Protocol, TypeAliasType, Union, get_args, get_origin

from snekql._cte import _CompoundRelation, _CteDefinition, _CteOutput
from snekql._output_layout import (
    LayoutOutput,
    OutputLayout,
    WireEncoding,
    build_output_layout,
)
from snekql._query_state import (
    CompoundSpec,
    SelectState,
    require_single_column_subquery,
)
from snekql._value_expression import ValueExpression
from snekql.errors import QueryConstructionError
from snekql.expressions import _Aggregate, _Scalar
from snekql.model import require_model_backend
from snekql.storage import Attr, _extract_logical_type, _resolve_model_hint


class _CompoundRole:
    """Private static owner for combined output references."""


class _NamedSetOperand[  # noqa: PYI046 - consumed by query builders
    FamilyT,
    ResultT,
    ReadinessT,
](Protocol):
    """Invariant backend/result witnesses exclude widening at composition."""

    @property
    def state(self) -> SelectState: ...

    def _set_family(self, family: FamilyT) -> FamilyT: ...

    def _set_result(self, result: ResultT) -> ResultT: ...

    def _readiness_type(self) -> ReadinessT: ...


def _nonnull_annotation(annotation: object, remaining: int = 64) -> object:
    """Remove only field-level optionality, never validators or JSON markers."""
    if remaining <= 0:
        msg = "UNION requires a resolvable output domain"
        raise QueryConstructionError(msg)
    if isinstance(annotation, TypeAliasType) and not annotation.__type_params__:
        return _nonnull_annotation(annotation.__value__, remaining - 1)
    if get_origin(annotation) in (Union, UnionType):
        members = tuple(item for item in get_args(annotation) if item is not type(None))
        if len(members) == 1:
            return _nonnull_annotation(members[0], remaining - 1)
    return annotation


def _decode_policy(source: object) -> tuple[object, ...]:
    """Compare decoding facts rather than descriptor identity or final models."""
    while True:
        if isinstance(source, LayoutOutput):
            source = source.__output_slot__().source
        elif isinstance(source, _Scalar):
            source = require_single_column_subquery(source.subquery).fields[0]
        elif isinstance(source, _Aggregate) and source.func in {"MIN", "MAX"}:
            source = source.column
        else:
            break
    if (
        isinstance(source, Attr)
        and source.owner is not None
        and source.name is not None
    ):
        annotation = _extract_logical_type(
            _resolve_model_hint(source.owner, source.name), source.name
        )
        return (
            "column",
            source.storage_class,
            source.storage_type_name,
            source.decimal_precision,
            source.decimal_scale,
            source.text_length,
            source.text_collation,
            _nonnull_annotation(annotation),
        )
    if isinstance(source, ValueExpression):
        return ("native", source.value_type)
    if isinstance(source, _Aggregate):
        if source.func == "COUNT":
            return ("COUNT",)
        return (source.func, _decode_policy(source.column))
    msg = "UNION requires a known output decode policy"
    raise QueryConstructionError(msg)


def _wire_policy(wire: WireEncoding) -> WireEncoding:
    """Extrema select an existing SQL value; unlike SUM/AVG they do not widen it."""
    while wire.operation in {"MIN", "MAX"} and len(wire.inputs) == 1:
        wire = wire.inputs[0]
    return wire


def _canonical_state(state: SelectState) -> SelectState:
    """Reorder named bindings and their token identities together."""
    projection = state.named_projection
    if projection is None:
        msg = "UNION requires named projections"
        raise QueryConstructionError(msg)
    labels = tuple(projection.result_type.model_fields)
    if set(labels) != set(projection.labels):
        msg = "UNION requires complete named bindings"
        raise QueryConstructionError(msg)
    positions = tuple(projection.labels.index(label) for label in labels)
    tokens = projection.output_tokens or (None,) * len(labels)
    return replace(
        state,
        fields=tuple(state.fields[position] for position in positions),
        named_projection=replace(
            projection,
            labels=labels,
            output_tokens=tuple(tokens[position] for position in positions),
        ),
    )


def _require_compatible_outputs(
    left_layout: OutputLayout, right_layout: OutputLayout
) -> None:
    """The left decoder is safe only when every right binding proves compatible."""
    if len(left_layout.slots) != len(right_layout.slots):
        msg = "UNION requires matching output fields"
        raise QueryConstructionError(msg)
    for first, second in zip(left_layout.slots, right_layout.slots, strict=True):
        if first.domain.nullable is None or second.domain.nullable is None:
            msg = "UNION requires known output nullability"
            raise QueryConstructionError(msg)
        if second.domain.nullable and not first.domain.nullable:
            msg = "UNION right output cannot widen the left output's nullability"
            raise QueryConstructionError(msg)
        left_domain = _nonnull_annotation(first.domain.logical)
        right_domain = _nonnull_annotation(second.domain.logical)
        if (
            left_domain is Any
            or right_domain is Any
            or left_domain != right_domain
            or _wire_policy(first.wire) != _wire_policy(second.wire)
            or _decode_policy(first.source) != _decode_policy(second.source)
        ):
            msg = "UNION requires compatible logical domains, wire encodings and decode policies"
            raise QueryConstructionError(msg)


def build_compound(
    left: SelectState,
    right: object,
    operator: Literal["UNION", "UNION ALL"],
) -> SelectState:
    """Freeze operand scopes and bind only the left contract's output tokens."""
    other = getattr(right, "state", None)
    if not isinstance(other, SelectState):
        msg = "UNION requires completed named SELECT operands"
        raise QueryConstructionError(msg)
    for operand in (left, other):
        if operand.named_projection is None or (
            not operand.explicit_all and not operand.predicates
        ):
            msg = "UNION requires completed named SELECT operands"
            raise QueryConstructionError(msg)
        if (
            operand.orderings
            or operand.limit_value is not None
            or operand.offset_value is not None
        ):
            msg = "UNION operands cannot have local ordering or pagination; use a CTE"
            raise QueryConstructionError(msg)
        if operand.lock_wait is not None:
            msg = "UNION operands cannot contain a locking SELECT"
            raise QueryConstructionError(msg)
    if require_model_backend(left.model) != require_model_backend(other.model):
        msg = "UNION operands must use the same backend"
        raise QueryConstructionError(msg)
    if left.named_projection is None or other.named_projection is None:
        msg = "UNION requires named projections"
        raise QueryConstructionError(msg)
    if left.named_projection.result_type is not other.named_projection.result_type:
        msg = "UNION operands require the exact same result-model class"
        raise QueryConstructionError(msg)
    left, other = _canonical_state(left), _canonical_state(other)
    left_layout = build_output_layout(left)
    right_layout = build_output_layout(other)
    _require_compatible_outputs(left_layout, right_layout)
    source = type(
        "__snekql_union",
        (_CompoundRelation,),
        {
            "definition": _CteDefinition(name="__snekql_union", state=left),
            "role": _CompoundRole,
            "__tablename__": "__snekql_union",
            "__snekql_backend__": require_model_backend(left.model),
        },
    )
    return SelectState(
        model=source,
        fields=tuple(
            _CteOutput[Any, Any, Any](position=index, relation=source)
            for index in range(len(left.fields))
        ),
        named_projection=left.named_projection,
        explicit_all=True,
        compound=CompoundSpec(left=left, right=other, operator=operator),
    )

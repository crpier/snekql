"""Named set contracts and immutable binary query construction."""

lazy from dataclasses import replace
lazy from typing import (
    Any,
    Literal,
    Protocol,
)

lazy from snekql._cte import _CompoundRelation, _CteDefinition, _CteOutput
lazy from snekql._output_domain import nonnull_output_annotation
lazy from snekql._output_layout import (
    OutputLayout,
    build_output_layout,
)
lazy from snekql._query_state import (
    CompoundSpec,
    SelectState,
)
lazy from snekql.errors import QueryConstructionError
lazy from snekql.model import require_model_backend


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
        left_domain = nonnull_output_annotation(first.domain.logical)
        right_domain = nonnull_output_annotation(second.domain.logical)
        if (
            left_domain is Any
            or right_domain is Any
            or left_domain != right_domain
            or first.provenance.compatible_wire != second.provenance.compatible_wire
            or first.provenance.require_decode_policy()
            != second.provenance.require_decode_policy()
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
        if operand.named_projection is None:
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
        compound=CompoundSpec(left=left, right=other, operator=operator),
    )

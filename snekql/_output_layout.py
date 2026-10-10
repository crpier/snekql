"""Ordered SQL output slots retaining source wire and validation policies."""

lazy from dataclasses import dataclass
lazy from typing import Any, Protocol, runtime_checkable

lazy from snekql._dialect_expr import SqlCompilable
lazy from snekql._output_domain import OutputDomain, output_domain
lazy from snekql._output_label import _OutputLabel
lazy from snekql._output_provenance import OutputProvenance
lazy from snekql._query_state import (
    Selectable,
    SelectState,
    require_single_column_subquery,
    selectable_owner_model,
)
lazy from snekql._value_decode import _decode_projection_field
lazy from snekql._value_expression import ValueExpression
lazy from snekql.errors import QueryConstructionError
lazy from snekql.expressions import _Scalar
lazy from snekql.model import BackendFamily, require_model_backend
lazy from snekql.storage import Attr


@dataclass(frozen=True, slots=True, repr=False)
class OutputSlot:
    """One visible output and its original, policy-aware SQL value source."""

    label: str
    token: _OutputLabel[Any, Any, Any] | None
    source: Selectable
    domain: OutputDomain
    provenance: OutputProvenance
    backend: BackendFamily
    nullable_models: frozenset[type[object]]

    def decode(self, raw: object, *, validate: bool) -> object:
        """Decode source values, never intermediate application result models."""
        return _decode_projection_field(
            self.source,
            raw,
            nullable_models=self.nullable_models,
            backend=self.backend,
            validate=validate,
        )

    def encode_comparison(self, value: object) -> object:
        return self.provenance.encode_comparison(value, backend=self.backend)


@runtime_checkable
class LayoutOutput(SqlCompilable, Protocol):
    """A derived reference retains the slot it reads rather than copying a codec."""

    def __output_slot__(self) -> OutputSlot: ...


@dataclass(frozen=True, slots=True, repr=False)
class OutputLayout:
    """Visible slots in SQL order; the presence field is private and separate."""

    slots: tuple[OutputSlot, ...]
    presence_name: str


def build_output_layout(state: SelectState) -> OutputLayout:
    projection = state.named_projection
    if projection is None or len(projection.labels) != len(state.fields):
        msg = "CTE layout requires a complete named projection"
        raise QueryConstructionError(msg)
    backend = require_model_backend(state.model)
    nullable_models = frozenset(
        join.model for join in state.joins if join.join_type == "LEFT"
    )
    tokens = projection.output_tokens or (None,) * len(state.fields)
    slots = tuple(
        OutputSlot(
            label=label,
            token=token,
            source=source,
            domain=definition_output_domain(state, source),
            provenance=OutputProvenance.for_source(
                source, nullable_models=nullable_models
            ),
            backend=backend,
            nullable_models=nullable_models,
        )
        for label, token, source in zip(
            projection.labels, tokens, state.fields, strict=True
        )
    )
    names = {slot.label.casefold() for slot in slots}
    presence_name = "__snekql_present"
    while presence_name.casefold() in names:
        presence_name += "_"
    return OutputLayout(slots, presence_name)


def definition_output_domain(state: SelectState, source: object) -> OutputDomain:
    """Keep definition-local NULL extension separate from result annotations."""
    if isinstance(source, _Scalar):
        inner = require_single_column_subquery(source.subquery)
        domain = definition_output_domain(inner, inner.fields[0])
        return OutputDomain(domain.logical, nullable=True)
    domain = output_domain(source)
    if isinstance(source, (Attr, ValueExpression, LayoutOutput)):
        nullable_owners = {
            join.model for join in state.joins if join.join_type == "LEFT"
        }
        if selectable_owner_model(source) in nullable_owners and (
            not isinstance(source, ValueExpression)
            or source.__nullable_when_extended__()
        ):
            return OutputDomain(domain.logical, nullable=True)
    return domain

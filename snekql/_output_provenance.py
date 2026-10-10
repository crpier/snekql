"""Retained source proofs for derived SQL values, separate from result models."""

lazy from dataclasses import dataclass, replace
lazy from typing import Any, cast

lazy from snekql._literal import _IntegerLiteral
lazy from snekql._output_domain import nonnull_output_annotation
lazy from snekql._output_layout import LayoutOutput
lazy from snekql._query_dialect import query_dialect_for_backend
lazy from snekql._query_state import (
    require_selectable,
    require_single_column_subquery,
    selectable_owner_model,
)
lazy from snekql._value_decode import _normalize_sum
lazy from snekql._value_encode import _predicate_value_encoder
lazy from snekql._value_expression import ValueExpression
lazy from snekql.errors import QueryConstructionError
lazy from snekql.expressions import _Aggregate, _Scalar
lazy from snekql.model import BackendFamily
lazy from snekql.storage import Attr, _extract_logical_type, _resolve_model_hint


@dataclass(frozen=True, slots=True)
class WireEncoding:
    """SQL provenance does not equate logical types with driver values."""

    operation: str
    storage_class: str | None = None
    storage_type: str | None = None
    native_type: type | None = None
    inputs: tuple[WireEncoding, ...] = ()


@dataclass(frozen=True, slots=True, repr=False)
class OutputProvenance:
    """Independent source proofs; missing capabilities do not invalidate a SELECT.

    Wire and decode policies establish compatibility, not arithmetic eligibility.
    Capability sources retain the leaf's own gates rather than duplicating them.
    """

    # Compatibility facts remain separate from operation-specific leaf witnesses.
    wire: WireEncoding
    compatible_wire: WireEncoding
    decode_policy: tuple[object, ...] | None
    decode_error: str | None
    comparison_source: object
    native_source: (
        Attr[Any, Any, Any, Any, Any]
        | ValueExpression[Any, Any, Any, Any]
        | type[int]
        | None
    )
    native_nullable: bool
    numeric_source: Attr[Any, Any, Any, Any, Any] | type[int | float] | None
    ordering_source: Attr[Any, Any, Any, Any, Any] | None

    @classmethod
    def for_source(
        cls, source: object, *, nullable_models: frozenset[type[object]] = frozenset()
    ) -> OutputProvenance:
        """Interpret a definition once; references reuse its retained source proofs."""
        if isinstance(source, LayoutOutput):
            provenance = source.__output_slot__().provenance
        elif isinstance(source, _Scalar):
            inner = require_single_column_subquery(source.subquery)
            provenance = replace(
                cls.for_source(
                    inner.fields[0],
                    nullable_models=frozenset(
                        join.model for join in inner.joins if join.join_type == "LEFT"
                    ),
                ),
                native_nullable=True,
            )
        elif isinstance(source, Attr):
            provenance = cls._column(source)
        elif isinstance(source, (ValueExpression, _IntegerLiteral)):
            wire = WireEncoding("native", native_type=source.value_type)
            provenance = cls(
                wire=wire,
                compatible_wire=wire,
                decode_policy=("native", source.value_type),
                decode_error=None,
                comparison_source=source,
                native_source=source if isinstance(source, ValueExpression) else int,
                native_nullable=source.nullable
                if isinstance(source, ValueExpression)
                else False,
                numeric_source=int
                if source.value_type is int
                else float
                if source.value_type is float
                else None,
                ordering_source=None,
            )
        elif isinstance(source, _Aggregate):
            provenance = cls._aggregate(source)
        else:
            wire = WireEncoding("unknown")
            provenance = cls(
                wire=wire,
                compatible_wire=wire,
                decode_policy=None,
                decode_error=None,
                comparison_source=source,
                native_source=None,
                native_nullable=False,
                numeric_source=None,
                ordering_source=None,
            )
        if isinstance(source, (Attr, ValueExpression, LayoutOutput)) and (
            selectable_owner_model(source) in nullable_models
            and (
                not isinstance(source, ValueExpression)
                or source.__nullable_when_extended__()
            )
        ):
            provenance = replace(provenance, native_nullable=True)
        return provenance

    def require_decode_policy(self) -> tuple[object, ...]:
        """An opaque or unresolved source is not evidence of UNION compatibility."""
        if self.decode_policy is None:
            msg = self.decode_error or "UNION requires a known output decode policy"
            raise QueryConstructionError(msg)
        return self.decode_policy

    def encode_comparison(self, value: object, *, backend: BackendFamily) -> object:
        """Bindings reach the retained source codec without rediscovering scalars."""
        return _predicate_value_encoder(
            require_selectable(self.comparison_source),
            query_dialect_for_backend(backend),
        )(value)

    def native_profile(self) -> tuple[type[int | float | str], bool]:
        """Only a native leaf or COUNT proves SQL value-operation compatibility."""
        if self.native_source is int:
            return int, self.native_nullable
        if isinstance(self.native_source, (Attr, ValueExpression)):
            operand = self.native_source.__value_operand__()
            return operand.value_type, self.native_nullable
        msg = "CTE arithmetic requires a known native wire-compatible output"
        raise QueryConstructionError(msg)

    def require_numeric_source(
        self,
    ) -> Attr[Any, Any, Any, Any, Any] | type[int | float]:
        """Numeric aggregates need a separate proof from native arithmetic."""
        if isinstance(self.numeric_source, Attr):
            self.numeric_source.sum()
            return self.numeric_source
        if self.numeric_source in (int, float):
            return self.numeric_source
        msg = "sum()/avg() require a known numeric CTE output domain"
        raise QueryConstructionError(msg)

    def require_ordering(self) -> None:
        """Extrema retain leaf ordering restrictions; other aggregates do not."""
        if self.ordering_source is not None:
            self.ordering_source.asc()

    def decode_sum(self, raw: object) -> object:
        """Totals follow their numeric source, not an intermediate result model."""
        source = self.require_numeric_source()
        if isinstance(source, Attr):
            return _normalize_sum(source, raw)
        # The retained witness has passed the numeric gate; drivers supply numbers.
        return source(cast("int | float", raw))

    def encode_sum_comparison(self, value: object, *, backend: BackendFamily) -> object:
        """SUM bounds use the result domain, not the input column's size limits."""
        source = self.require_numeric_source()
        if isinstance(source, Attr):
            return query_dialect_for_backend(backend).encode_sum_value(source, value)
        return value

    @classmethod
    def _column(cls, source: Attr[Any, Any, Any, Any, Any]) -> OutputProvenance:
        wire = WireEncoding(
            "column",
            storage_class=source.storage_class,
            storage_type=source.storage_type_name,
        )
        decode_policy = None
        decode_error = None
        if source.owner is not None and source.name is not None:
            annotation = _extract_logical_type(
                _resolve_model_hint(source.owner, source.name), source.name
            )
            try:
                annotation = nonnull_output_annotation(annotation)
            except QueryConstructionError as e:
                # Only composition requires this proof; definition remains usable.
                decode_error = str(e)
            else:
                decode_policy = (
                    "column",
                    source.storage_class,
                    source.storage_type_name,
                    source.decimal_precision,
                    source.decimal_scale,
                    source.text_length,
                    source.text_collation,
                    annotation,
                )
        return cls(
            wire=wire,
            compatible_wire=wire,
            decode_policy=decode_policy,
            decode_error=decode_error,
            comparison_source=source,
            native_source=source,
            native_nullable=source.nullable,
            numeric_source=source,
            ordering_source=source,
        )

    @classmethod
    def _aggregate(cls, source: _Aggregate[Any, Any]) -> OutputProvenance:
        if source.func == "COUNT":
            wire = WireEncoding("COUNT", native_type=int)
            return cls(
                wire=wire,
                compatible_wire=wire,
                decode_policy=("COUNT",),
                decode_error=None,
                comparison_source=source,
                native_source=int,
                native_nullable=False,
                numeric_source=int,
                ordering_source=None,
            )
        wrapped = cls.for_source(source.column)
        wire = WireEncoding(source.func, inputs=(wrapped.wire,))
        extrema = source.func in {"MIN", "MAX"}
        return cls(
            wire=wire,
            compatible_wire=wrapped.compatible_wire if extrema else wire,
            decode_policy=wrapped.decode_policy
            if extrema
            else (
                (source.func, wrapped.decode_policy)
                if wrapped.decode_policy is not None
                else None
            ),
            decode_error=wrapped.decode_error,
            comparison_source=source,
            native_source=None,
            native_nullable=False,
            numeric_source=float if source.func == "AVG" else wrapped.numeric_source,
            ordering_source=wrapped.ordering_source if extrema else None,
        )

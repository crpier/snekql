"""Decode SQL output values without constructing intermediate result models."""

lazy from collections.abc import Callable
lazy from functools import partial
lazy from typing import Any, cast

lazy from snekql._column_protocols import is_dialect_selectable, is_policy_selectable
lazy from snekql._cte import _CteOutput
lazy from snekql._dialect_expr import (
    DialectSelectable,
    NullExtendedSelectable,
    NumericAggregatePolicy,
    PolicySelectable,
)
lazy from snekql._query_state import (
    Selectable,
    require_column_model,
    require_field,
    require_single_column_subquery,
)
lazy from snekql.errors import QueryCompilationError
lazy from snekql.expressions import _Aggregate, _Scalar
lazy from snekql.storage import Attr, StorageBackend


def _normalize_sum(column: Attr[Any, Any, Any, Any, Any], value: object) -> object:
    """Normalize ``SUM`` to the wrapped column's logical type across backends.

    SQLite returns an integer for an integer-column sum; MariaDB returns
    ``DECIMAL``. Mirroring the column's storage type makes both agree.
    """

    if column.storage_type_name == "Integer":
        return int(cast("int", value))
    if column.storage_type_name == "Real":
        return float(cast("float", value))
    return value


def _decode_aggregate(
    aggregate: _Aggregate[Any, Any],
    value: object,
    *,
    backend: StorageBackend,
    validate: bool,
) -> object:
    """Decode an aggregate value, normalizing across backends.

    COUNT is always an int; AVG is a float; SUM normalizes native numeric
    results. MIN/MAX use the wrapped column's codec and the caller's validation
    policy. NULL over an empty set decodes to None for everything but COUNT.
    """

    if value is None:
        return None
    if aggregate.func == "COUNT":
        return int(cast("int", value))
    if aggregate.func == "AVG":
        return float(cast("float", value))
    if aggregate.func == "SUM":
        return _decode_sum(aggregate.column, value)
    if isinstance(aggregate.column, PolicySelectable):
        return aggregate.column.__decode_with_policy__(
            value, backend=backend, validate=validate
        )
    # Extrema retain the source column's validation policy.
    return require_field(aggregate.column).decode(
        value, backend=backend, validate=validate
    )


def _decode_sum(column: object, value: object) -> object:
    """Normalize totals according to their physical or derived output domain."""
    if isinstance(column, NumericAggregatePolicy):
        return column.__decode_sum__(value)
    return _normalize_sum(require_field(column), value)


def _decode_selectable(
    field: Selectable,
    value: object,
    *,
    backend: StorageBackend,
    validate: bool,
) -> object:
    if isinstance(field, _Scalar):
        # A scalar subquery evaluates to SQL NULL on an empty/no-match result
        # set, even over a NOT NULL inner column, so a NULL decodes to None
        # rather than through the inner column's null rejection (#203 F10).
        if value is None:
            return None
        # Otherwise decode through its single projected selectable, so an inner
        # SUM/COUNT/column normalizes exactly as it would standalone.
        inner = require_single_column_subquery(field.subquery)
        return _decode_selectable(
            inner.fields[0],
            value,
            backend=backend,
            validate=validate,
        )
    if isinstance(field, _Aggregate):
        return _decode_aggregate(field, value, backend=backend, validate=validate)
    if isinstance(field, PolicySelectable):
        return field.__decode_with_policy__(value, backend=backend, validate=validate)
    if isinstance(field, DialectSelectable):
        # Open-AST dialect expression: decode through the leaf's own seam, so the
        # raw driver value becomes the typed value the projection promised without
        # the core knowing the leaf. The decoded type is the leaf's `T`; this seam
        # is type-erased (the result shape flows through the `select` overloads).
        return cast("object", field.__decode__(value))
    if isinstance(field, Attr):
        return field.decode(value, backend=backend, validate=validate)
    msg = "a non-projectable operand cannot be materialized"
    raise QueryCompilationError(msg)


def _decode_projection_field(
    column: Selectable,
    value: object,
    *,
    nullable_models: frozenset[type[object]],
    backend: StorageBackend,
    validate: bool,
) -> object:
    """Decode one projected column, tolerating a left-join's unmatched NULLs.

    A column projected from the nullable side of a LEFT join is ``None`` for an
    unmatched row even when the column is itself ``NOT NULL``; decoding that
    through the column's codec would wrongly enforce its NOT NULL constraint and
    raise. Such a ``None`` is yielded as ``None`` (the documented projection
    nullability gap) rather than crashing the fetch.
    """

    if (
        value is None
        and isinstance(column, Attr)
        and require_column_model(column) in nullable_models
    ):
        return None
    if (
        value is None
        and isinstance(column, NullExtendedSelectable)
        and column.__owner_model__() in nullable_models
        and column.__nullable_when_extended__()
    ):
        return None
    return _decode_selectable(column, value, backend=backend, validate=validate)


def resolve_projection_decoder(
    column: Selectable,
    *,
    nullable_models: frozenset[type[object]],
    backend: StorageBackend,
    validate: bool,
) -> Callable[[object], object]:
    """Resolve ordinary columns and built-in derived chains for this execution.

    Structural extension seams take precedence even on Attr subclasses. Keep
    those and non-column expressions on the general decoder; never cache by
    class or globally, since ownership and validation belong to the execution.
    """
    # Built-in derived references only forward to their definition's wire
    # source. Resolve that chain with each definition's own NULL-extension
    # context; never validate its intermediate application result model.
    if type(cast("object", column)) is _CteOutput:
        reference = cast("_CteOutput[Any, Any, Any]", column)
        slot = reference.__output_slot__()
        if backend == slot.backend:
            decode = resolve_projection_decoder(
                slot.source,
                nullable_models=slot.nullable_models,
                backend=slot.backend,
                validate=validate,
            )
            if reference.relation in nullable_models:

                def decode_derived_nullable(raw: object) -> object:
                    return None if raw is None else decode(raw)

                return decode_derived_nullable
            return decode
        # Preserve the existing error boundary: an incompatible slot fails
        # when decoded, not while resolving an empty or NULL-extended read.
    if (
        isinstance(column, Attr)
        and not is_policy_selectable(column)
        and not is_dialect_selectable(column)
    ):
        decode = partial(column.decode, backend=backend, validate=validate)
        if nullable_models and require_column_model(column) in nullable_models:

            def decode_nullable(raw: object) -> object:
                return None if raw is None else decode(raw)

            return decode_nullable
        return decode
    return _resolve_expression_decoder(
        column, nullable_models=nullable_models, backend=backend, validate=validate
    )


def _resolve_expression_decoder(
    column: Selectable,
    *,
    nullable_models: frozenset[type[object]],
    backend: StorageBackend,
    validate: bool,
) -> Callable[[object], object]:
    """Resolve built-in expressions off the ordinary-column dispatch path."""
    if type(column) is _Scalar:
        inner = require_single_column_subquery(column.subquery)
        decode = resolve_projection_decoder(
            inner.fields[0],
            nullable_models=frozenset(),
            backend=backend,
            validate=validate,
        )

        def decode_scalar(raw: object) -> object:
            # SQL NULL from an empty scalar bypasses even a NOT NULL source
            # codec, just as it does on the general selectable path.
            return None if raw is None else decode(raw)

        return decode_scalar
    if type(column) is _Aggregate:
        aggregate_decoder = _resolve_column_aggregate_decoder(
            column, backend=backend, validate=validate
        )
        if aggregate_decoder is not None:
            return aggregate_decoder
    return partial(
        _decode_projection_field,
        column,
        nullable_models=nullable_models,
        backend=backend,
        validate=validate,
    )


def _resolve_column_aggregate_decoder(
    aggregate: _Aggregate[Any, Any], *, backend: StorageBackend, validate: bool
) -> Callable[[object], object] | None:
    """Bind aggregate codecs, retaining distinct fixed and source-policy domains."""
    if aggregate.func == "COUNT":
        return _decode_count
    if aggregate.func == "AVG":
        return _decode_average
    source = aggregate.column
    if aggregate.func == "SUM" and type(source) is _CteOutput:
        # Bind the existing numeric provenance path, not its original codec.
        # Keep the numeric gate per value to preserve errors and source behavior.
        decode = source.__output_slot__().provenance.decode_sum
    elif aggregate.func in ("MIN", "MAX") and type(source) is _CteOutput:
        # Derived extrema adopt the definition's projection policy (including
        # dialect hooks), unlike extrema directly over a physical column.
        # Resolve through the reference to retain deferred backend failures.
        decode = resolve_projection_decoder(
            source, nullable_models=frozenset(), backend=backend, validate=validate
        )
    elif not isinstance(source, Attr):
        return None
    elif aggregate.func in ("MIN", "MAX") and not is_policy_selectable(source):
        # Extrema do not adopt dialect-only projection hooks.
        decode = partial(source.decode, backend=backend, validate=validate)
    elif aggregate.func == "SUM" and not isinstance(source, NumericAggregatePolicy):
        # SUM normalizes its SQL numeric domain, not the column's logical type.
        decode = partial(_normalize_sum, source)
    else:
        return None

    def decode_nullable(raw: object) -> object:
        return None if raw is None else decode(raw)

    return decode_nullable


def _decode_count(value: object) -> object:
    """Keep SQL NULLs distinct from COUNT's ordinary zero result."""
    return None if value is None else int(cast("int", value))


def _decode_average(value: object) -> object:
    """AVG uses a nullable float domain, not the source column's codec."""
    return None if value is None else float(cast("float", value))

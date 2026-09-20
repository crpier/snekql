"""Decode SQL output values without constructing intermediate result models."""

from __future__ import annotations

from typing import Any, cast

from snekql._dialect_expr import DialectSelectable, PolicySelectable
from snekql._query_state import (
    Selectable,
    require_column_model,
    require_field,
    require_single_column_subquery,
)
from snekql._value_expression import ValueExpression
from snekql.errors import QueryCompilationError
from snekql.expressions import _Aggregate, _Scalar
from snekql.storage import Attr, StorageBackend


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
    if aggregate.func != "SUM" and isinstance(aggregate.column, PolicySelectable):
        return aggregate.column.__decode_with_policy__(
            value, backend=backend, validate=validate
        )
    column = require_field(aggregate.column)
    if aggregate.func == "SUM":
        return _normalize_sum(column, value)
    # Stored values may violate logical constraints after unchecked/external
    # writes. MIN/MAX use the same validation policy as a direct column read.
    return column.decode(value, backend=backend, validate=validate)


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
        and isinstance(column, ValueExpression)
        and column.__owner_model__() in nullable_models
        and column.__nullable_when_extended__()
    ):
        return None
    return _decode_selectable(column, value, backend=backend, validate=validate)

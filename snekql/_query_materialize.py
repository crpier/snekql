"""Materialization: decode database rows into a select query's result shape.

The read-side counterpart to Query Compilation. Every function here operates on
query state plus a backend tag; like compilation, it depends only on the shared
query state, never on the Query Builder classes.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, cast

from snekql._dialect_expr import DialectSelectable
from snekql._model_materialization import decode_model_row
from snekql._query_state import (
    InsertState,
    Selectable,
    SelectState,
    require_column_name,
    require_field,
    require_single_column_subquery,
)
from snekql.errors import QueryCompilationError
from snekql.expressions import Aggregate, Scalar
from snekql.model import require_model_columns
from snekql.storage import Attr, StorageBackend


def _decode_aggregate(
    aggregate: Aggregate[Any, Any],
    value: object,
    *,
    backend: StorageBackend,
) -> object:
    """Decode an aggregate value, normalizing across backends.

    Aggregates are not real columns: ``COUNT`` is always an ``int``; ``AVG`` is a
    ``float``; ``SUM`` mirrors the wrapped column's logical type (so MariaDB's
    ``DECIMAL`` and SQLite's integer agree); ``MIN``/``MAX`` reuse the column's
    wire decode but skip per-row logical validation, since an aggregate value
    need not satisfy the column's declared constraints. ``NULL`` over an empty
    set decodes to ``None`` for everything but ``COUNT``.
    """

    if value is None:
        return None
    if aggregate.func == "COUNT":
        return int(cast("int", value))
    if aggregate.func == "AVG":
        return float(cast("float", value))
    column = require_field(aggregate.column)
    if aggregate.func == "SUM":
        return _normalize_sum(column, value)
    return column.decode(value, backend=backend, validate=False)


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


def _decode_selectable(
    field: Selectable,
    value: object,
    *,
    backend: StorageBackend,
    validate: bool,
) -> object:
    if isinstance(field, Scalar):
        # A scalar subquery decodes through its single projected selectable, so
        # an inner SUM/COUNT/column normalizes exactly as it would standalone.
        inner = require_single_column_subquery(field.subquery)
        return _decode_selectable(
            inner.fields[0],
            value,
            backend=backend,
            validate=validate,
        )
    if isinstance(field, Aggregate):
        return _decode_aggregate(field, value, backend=backend)
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


def _materialize_join_row(
    state: SelectState,
    row: Sequence[object],
    *,
    backend: StorageBackend,
    validate: bool,
) -> tuple[object, ...]:
    """Split one joined row into a Fetched model per table, in join order.

    A left-joined table whose columns are all NULL produced no matching row, so
    its tuple slot is materialized as None rather than a model.
    """

    elements: list[object] = []
    offset = 0
    for index, model in enumerate(state.result_models()):
        columns = require_model_columns(model)
        width = len(columns)
        chunk = row[offset : offset + width]
        offset += width
        is_left_join = index > 0 and state.joins[index - 1].join_type == "LEFT"
        if is_left_join and all(value is None for value in chunk):
            elements.append(None)
            continue
        values = {name: chunk[position] for position, name in enumerate(columns)}
        elements.append(
            decode_model_row(model, values, backend=backend, validate=validate),
        )
    return tuple(elements)


def materialize_select_row_for_backend(
    state: SelectState,
    row: Sequence[object],
    *,
    backend: StorageBackend,
    validate: bool = True,
) -> object:
    """Materialize one database row into the select query's result shape.

    Shared by every backend: a join select decodes the row into a tuple of
    Fetched models (one per joined table), a model select decodes the whole row
    into a Fetched Model, a single-column select returns one decoded scalar, and
    a multi-column select returns a tuple of decoded scalars in order.
    """

    assert len(row) == len(state.fields), (  # noqa: S101
        "database row shape did not match select query"
    )
    if state.joins and state.returns_model:
        return _materialize_join_row(state, row, backend=backend, validate=validate)
    if state.returns_model:
        # Model selects only ever project real columns, never aggregates.
        values = {
            require_column_name(require_field(column)): row[index]
            for index, column in enumerate(state.fields)
        }
        return decode_model_row(state.model, values, backend=backend, validate=validate)
    decoded_values = tuple(
        _decode_selectable(column, row[index], backend=backend, validate=validate)
        for index, column in enumerate(state.fields)
    )
    if len(decoded_values) == 1:
        return decoded_values[0]
    return decoded_values


def materialize_insert_returning_rows_for_backend(
    query: object,
    rows: Sequence[Sequence[object]],
    *,
    backend: StorageBackend,
    validate: bool = True,
) -> list[object]:
    """Materialize ``RETURNING`` rows from an insert into Fetched models.

    The ``RETURNING`` clause projects every column in model declaration order
    (see ``_insert_returning_clause``), so each database row decodes through the
    full model exactly like a model select, yielding generated values
    (auto-increment keys, server defaults) as a Fetched Model.

    Insert queries are typed as ``object`` in the Query Runtime, so this seam
    narrows from the query object to its state rather than importing the Query
    Builder classes.
    """

    state = getattr(query, "state", None)
    if not isinstance(state, InsertState):
        msg = "materialize requires an insert query"
        raise QueryCompilationError(msg)
    model_class = state.model()
    if model_class is None:
        return []
    columns = require_model_columns(model_class)
    names = tuple(columns)
    materialized: list[object] = []
    for row in rows:
        assert len(row) == len(names), (  # noqa: S101
            "returning row shape did not match the inserted model"
        )
        values = {name: row[index] for index, name in enumerate(names)}
        materialized.append(
            decode_model_row(model_class, values, backend=backend, validate=validate),
        )
    return materialized

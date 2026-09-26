"""Materialization: decode database rows into a select query's result shape.

The read-side counterpart to Query Compilation. Every function here operates on
query state plus a backend tag; like compilation, it depends only on the shared
query state, never on the Query Builder classes.
"""

from __future__ import annotations

from collections.abc import Sequence

from snekql._aliases import _AliasRelation
from snekql._cte import _CteRelation
from snekql._model_materialization import decode_model_row
from snekql._named_projection import NamedProjection
from snekql._query_sources import query_fields
from snekql._query_state import (
    InsertState,
    Selectable,
    SelectState,
    WriteState,
    require_column_name,
    require_field,
)
from snekql._value_decode import _decode_projection_field, _decode_selectable
from snekql.errors import QueryCompilationError
from snekql.model import require_model_columns
from snekql.storage import StorageBackend


def _materialize_join_row(
    state: SelectState,
    row: Sequence[object],
    *,
    backend: StorageBackend,
    validate: bool,
) -> tuple[object, ...]:
    """Split one joined row into a Row model per table, in join order.

    A left-joined table whose columns are all NULL produced no matching row, so
    its tuple slot is materialized as None rather than a model.
    """

    elements: list[object] = []
    offset = 0
    for index, model in enumerate(state.result_models()):
        fields = query_fields(model)
        cte_source = issubclass(model, _CteRelation)
        width = len(fields) + int(cte_source)
        chunk = row[offset : offset + width]
        offset += width
        is_left_join = index > 0 and state.joins[index - 1].join_type == "LEFT"
        absent = (
            chunk[-1] is None if cte_source else all(value is None for value in chunk)
        )
        if is_left_join and absent:
            elements.append(None)
            continue
        if issubclass(model, _CteRelation):
            projection = model.definition.state.named_projection
            if projection is None:
                msg = "CTE row requires a named result contract"
                raise QueryCompilationError(msg)
            elements.append(
                projection.materialize(
                    tuple(
                        _decode_selectable(
                            field, value, backend=backend, validate=validate
                        )
                        for field, value in zip(fields, chunk[:-1], strict=True)
                    )
                )
            )
            continue
        columns = require_model_columns(model)
        values = {name: chunk[position] for position, name in enumerate(columns)}
        elements.append(
            decode_model_row(
                model.source_model if issubclass(model, _AliasRelation) else model,
                values,
                backend=backend,
                validate=validate,
            ),
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
    Row models (one per joined table), a model select decodes the whole row
    into a Row Model, a single-column select returns one decoded scalar, and
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
        model = (
            state.model.source_model
            if issubclass(state.model, _AliasRelation)
            else state.model
        )
        return decode_model_row(model, values, backend=backend, validate=validate)
    nullable_models = _left_joined_models(state)
    decoded_values = tuple(
        _decode_projection_field(
            column,
            row[index],
            nullable_models=nullable_models,
            backend=backend,
            validate=validate,
        )
        for index, column in enumerate(state.fields)
    )
    if state.named_projection is not None:
        return state.named_projection.materialize(decoded_values)
    if len(decoded_values) == 1:
        return decoded_values[0]
    return decoded_values


def _left_joined_models(state: SelectState) -> frozenset[type[object]]:
    """Models projected from the nullable side of a LEFT join, by identity."""

    return frozenset(join.model for join in state.joins if join.join_type == "LEFT")


def _materialize_insert_returning_fields(
    fields: tuple[Selectable, ...],
    rows: Sequence[Sequence[object]],
    *,
    backend: StorageBackend,
    validate: bool,
    projection: NamedProjection | None = None,
) -> list[object]:
    """Decode RETURNING rows for an explicit column projection.

    Mirrors a projection select: one projected column yields a decoded scalar per
    row, several yield a tuple per row, both through the shared selectable decode.
    """

    materialized: list[object] = []
    for row in rows:
        assert len(row) == len(fields), (  # noqa: S101
            "returning row shape did not match the projection"
        )
        decoded = tuple(
            _decode_selectable(field, row[index], backend=backend, validate=validate)
            for index, field in enumerate(fields)
        )
        materialized.append(
            projection.materialize(decoded)
            if projection is not None
            else decoded[0]
            if len(decoded) == 1
            else decoded
        )
    return materialized


def materialize_write_returning_rows_for_backend(
    state: WriteState,
    rows: Sequence[Sequence[object]],
    *,
    backend: StorageBackend,
    validate: bool = True,
) -> list[object]:
    """Materialize ``RETURNING`` rows from a write into the query result shape.

    A whole-row ``returning()`` projects every column in model declaration order,
    so each database row decodes through the full model exactly like a model
    select. An explicit projection mirrors a projection select.
    """

    model_class = state.model() if isinstance(state, InsertState) else state.model
    returning_fields = state.returning_fields
    if returning_fields:
        return _materialize_insert_returning_fields(
            returning_fields,
            rows,
            backend=backend,
            validate=validate,
            projection=state.named_projection,
        )
    if model_class is None:
        return []
    columns = require_model_columns(model_class)
    names = tuple(columns)
    materialized: list[object] = []
    for row in rows:
        assert len(row) == len(names), (  # noqa: S101
            "returning row shape did not match the written model"
        )
        values = {name: row[index] for index, name in enumerate(names)}
        materialized.append(
            decode_model_row(model_class, values, backend=backend, validate=validate),
        )
    return materialized

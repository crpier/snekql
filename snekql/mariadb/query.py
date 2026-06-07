"""MariaDB SQL compilation and row materialization."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, cast

from snekql._model_materialization import (
    decode_column_value,
    decode_model_row,
    encode_column_value,
    encode_model_row,
)
from snekql.errors import QueryCompilationError
from snekql.expressions import Predicate
from snekql.query import (
    AnySelectQuery,
    DeleteQuery,
    InsertQuery,
    UpdateQuery,
    compile_select_sql,
    compile_write_sql,
)
from snekql.storage import Attr


def _translate_sqlite_sql(sql: str) -> str:
    """Translate the shared v1 SQL shape to MariaDB quoting and placeholders."""

    translated_sql = sql.replace('"', "`").replace("?", "%s")
    if translated_sql.endswith(" DEFAULT VALUES"):
        return translated_sql.removesuffix(" DEFAULT VALUES") + " () VALUES ()"
    return translated_sql


def _encode_column_value(
    column: Attr[Any, Any, Any, Any, Any],
    value: object,
) -> object:
    return encode_column_value(column, value, backend="mariadb")


def _predicate_params(predicate: Predicate[Any]) -> tuple[object, ...]:
    if predicate.kind in {"and", "or"}:
        return tuple(
            param for child in predicate.children for param in _predicate_params(child)
        )
    if predicate.kind == "not":
        return _predicate_params(predicate.children[0])
    column = cast("Attr[Any, Any, Any, Any, Any]", predicate.column)
    if predicate.kind in {"eq", "ne", "like", "not_like"}:
        return (_encode_column_value(column, predicate.value),)
    if predicate.kind in {"in", "not_in"}:
        return tuple(_encode_column_value(column, value) for value in predicate.values)
    return ()


def _select_params(query: AnySelectQuery) -> tuple[object, ...]:
    state = query.state
    params = tuple(
        param
        for predicate in state.predicates
        for param in _predicate_params(predicate)
    )
    if state.limit_value is not None:
        params = (*params, state.limit_value)
    if state.offset_value is not None:
        params = (*params, state.offset_value)
    return params


def _insert_params(query: InsertQuery[Any]) -> tuple[object, ...]:
    _, row_values = encode_model_row(query.row, backend="mariadb")
    return tuple(row_values.values())


def _update_params(query: UpdateQuery[Any]) -> tuple[object, ...]:
    params: tuple[object, ...] = tuple(
        _encode_column_value(
            cast("Attr[Any, Any, Any, Any, Any]", assignment.column), assignment.value
        )
        for assignment in query.state.assignments
    )
    for predicate in query.state.predicates:
        params = (*params, *_predicate_params(predicate))
    return params


def _delete_params(query: DeleteQuery[Any]) -> tuple[object, ...]:
    return tuple(
        param
        for predicate in query.state.predicates
        for param in _predicate_params(predicate)
    )


def compile_mariadb_select_sql(
    query: AnySelectQuery,
) -> tuple[str, tuple[object, ...]]:
    """Compile a select query into parameterized MariaDB SQL."""

    sql, _ = compile_select_sql(query)
    return _translate_sqlite_sql(sql), _select_params(query)


def compile_mariadb_write_sql(query: object) -> tuple[str, tuple[object, ...]]:
    """Compile a write query into parameterized MariaDB SQL."""

    sql, _ = compile_write_sql(query)
    if isinstance(query, InsertQuery):
        params = _insert_params(cast("InsertQuery[Any]", query))
    elif isinstance(query, UpdateQuery):
        params = _update_params(cast("UpdateQuery[Any]", query))
    elif isinstance(query, DeleteQuery):
        params = _delete_params(cast("DeleteQuery[Any]", query))
    else:
        params = ()
    return _translate_sqlite_sql(sql), params


def materialize_mariadb_select_row(
    query: AnySelectQuery,
    row: Sequence[object],
) -> object:
    """Decode one MariaDB result row according to a select query."""

    state = query.state
    if len(row) != len(state.fields):
        msg = "database row shape did not match select query"
        raise QueryCompilationError(msg)
    if state.returns_model:
        values = {
            column.name or "": row[index] for index, column in enumerate(state.fields)
        }
        return decode_model_row(state.model, values, backend="mariadb")
    decoded_values = tuple(
        decode_column_value(column, row[index], backend="mariadb")
        for index, column in enumerate(state.fields)
    )
    if len(decoded_values) == 1:
        return decoded_values[0]
    return decoded_values

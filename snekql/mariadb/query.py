"""MariaDB SQL compilation and row materialization."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, cast

from snekql.expressions import Predicate
from snekql.model import Table, require_model_columns
from snekql.query import (
    AnySelectQuery,
    DeleteQuery,
    InsertQuery,
    UpdateQuery,
    compile_select_sql,
    compile_write_sql,
)
from snekql.storage import MISSING, Attr


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
    return column.encode_mariadb(value)


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
    row = query.row
    columns = require_model_columns(cast("type[Table[Any]]", type(row)))
    params: list[object] = []
    for name, column in columns.items():
        value = getattr(row, name)
        if value is MISSING:
            continue
        params.append(_encode_column_value(column, value))
    return tuple(params)


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


def _decode_model_row(
    model: type[Table[Any]],
    row: Mapping[str, object],
) -> Table[Any]:
    remaining_values = dict(row)
    from_row = type.__getattribute__(model, "_snekql_from_row")
    model_instance = object.__new__(model)
    storage = cast(
        "dict[str, object]",
        object.__getattribute__(model_instance, "__dict__"),
    )
    storage["_snekql_frozen"] = False
    storage["_snekql_state"] = "Fetched"
    for name, column in require_model_columns(model).items():
        value = column.decode_mariadb(remaining_values.pop(name))
        setattr(model_instance, name, value)
    if remaining_values:
        return cast("Table[Any]", from_row(row))
    storage["_snekql_frozen"] = True
    return model_instance


def materialize_mariadb_select_row(
    query: AnySelectQuery,
    row: Sequence[object],
) -> object:
    """Decode one MariaDB result row according to a select query."""

    state = query.state
    if state.returns_model:
        values = {
            column.name or "": row[index] for index, column in enumerate(state.fields)
        }
        return _decode_model_row(state.model, values)
    decoded_values = tuple(
        column.decode_mariadb(row[index]) for index, column in enumerate(state.fields)
    )
    if len(decoded_values) == 1:
        return decoded_values[0]
    return decoded_values

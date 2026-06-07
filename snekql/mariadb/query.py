"""MariaDB SQL compilation and row materialization."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, cast

from snekql._query_dialect import QueryDialect
from snekql.mariadb.identifiers import quote_identifier as quote_mariadb_identifier
from snekql.model import Table, require_model_columns
from snekql.query import (
    AnySelectQuery,
    compile_select_sql_for_dialect,
    compile_write_sql_for_dialect,
)
from snekql.storage import Attr


def _mariadb_empty_insert_sql(quoted_table: str) -> str:
    return f"INSERT INTO {quoted_table} () VALUES ()"  # noqa: S608


def _encode_mariadb_column_value(
    column: Attr[Any, Any, Any, Any, Any],
    value: object,
) -> object:
    return column.encode_mariadb(value)


_MARIADB_QUERY_DIALECT = QueryDialect(
    empty_insert_sql=_mariadb_empty_insert_sql,
    encode_column_value=_encode_mariadb_column_value,
    placeholder="%s",
    quote_identifier=quote_mariadb_identifier,
)


def compile_mariadb_select_sql(
    query: AnySelectQuery,
) -> tuple[str, tuple[object, ...]]:
    """Compile a select query into parameterized MariaDB SQL."""

    return compile_select_sql_for_dialect(query, _MARIADB_QUERY_DIALECT)


def compile_mariadb_write_sql(query: object) -> tuple[str, tuple[object, ...]]:
    """Compile a write query into parameterized MariaDB SQL."""

    return compile_write_sql_for_dialect(query, _MARIADB_QUERY_DIALECT)


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

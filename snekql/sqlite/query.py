"""SQLite SQL compilation and row materialization."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from snekql._model_materialization import (
    decode_column_value,
    decode_model_row,
    encode_column_value,
)
from snekql._query_dialect import QueryDialect
from snekql.errors import QueryCompilationError
from snekql.query import (
    AnySelectQuery,
    compile_select_sql_for_dialect,
    compile_write_sql_for_dialect,
)
from snekql.sqlite.identifiers import quote_identifier as quote_sqlite_identifier
from snekql.storage import Attr


def _sqlite_empty_insert_sql(quoted_table: str) -> str:
    return "INSERT INTO " + quoted_table + " DEFAULT VALUES"


def _encode_sqlite_column_value(
    column: Attr[Any, Any, Any, Any, Any],
    value: object,
) -> object:
    return encode_column_value(column, value, backend="sqlite")


_SQLITE_QUERY_DIALECT = QueryDialect(
    empty_insert_sql=_sqlite_empty_insert_sql,
    encode_column_value=_encode_sqlite_column_value,
    placeholder="?",
    quote_identifier=quote_sqlite_identifier,
)


def compile_sqlite_select_sql(
    query: AnySelectQuery,
) -> tuple[str, tuple[object, ...]]:
    """Compile a select query into parameterized SQLite SQL."""

    return compile_select_sql_for_dialect(query, _SQLITE_QUERY_DIALECT)


def compile_sqlite_write_sql(query: object) -> tuple[str, tuple[object, ...]]:
    """Compile a write query into parameterized SQLite SQL."""

    return compile_write_sql_for_dialect(query, _SQLITE_QUERY_DIALECT)


def materialize_sqlite_select_row(
    query: AnySelectQuery,
    row: Sequence[object],
) -> object:
    """Decode one SQLite result row according to a select query."""

    state = query.state
    if len(row) != len(state.fields):
        msg = "database row shape did not match select query"
        raise QueryCompilationError(msg)
    if state.returns_model:
        values = {
            column.name or "": row[index] for index, column in enumerate(state.fields)
        }
        return decode_model_row(state.model, values, backend="sqlite")
    decoded_values = tuple(
        decode_column_value(column, row[index], backend="sqlite")
        for index, column in enumerate(state.fields)
    )
    if len(decoded_values) == 1:
        return decoded_values[0]
    return decoded_values

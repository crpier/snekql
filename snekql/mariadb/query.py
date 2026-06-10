"""MariaDB SQL compilation and row materialization."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from snekql._model_materialization import decode_model_row
from snekql._query_dialect import QueryDialect
from snekql.mariadb.identifiers import quote_identifier as quote_mariadb_identifier
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
    return column.encode(value, backend="mariadb")


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


def materialize_mariadb_select_row(
    query: AnySelectQuery,
    row: Sequence[object],
) -> object:
    """Decode one MariaDB result row according to a select query."""

    state = query.state
    assert len(row) == len(state.fields), (  # noqa: S101
        "database row shape did not match select query"
    )
    if state.returns_model:
        values = {
            column.name or "": row[index] for index, column in enumerate(state.fields)
        }
        return decode_model_row(state.model, values, backend="mariadb")
    decoded_values = tuple(
        column.decode(row[index], backend="mariadb")
        for index, column in enumerate(state.fields)
    )
    if len(decoded_values) == 1:
        return decoded_values[0]
    return decoded_values

"""SQLite SQL compilation and row materialization."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from snekql._query_compile import (
    compile_select_sql_for_dialect,
    compile_write_sql_for_dialect,
)
from snekql._query_dialect import QueryDialect, register_query_dialect
from snekql._query_materialize import (
    materialize_insert_returning_rows_for_backend,
    materialize_select_row_for_backend,
)
from snekql.query import AnySelectQuery
from snekql.sqlite._dialect_sql import CURRENT_TIMESTAMP_SQL
from snekql.sqlite.identifiers import quote_identifier as quote_sqlite_identifier
from snekql.storage import Attr


def _sqlite_empty_insert_sql(quoted_table: str) -> str:
    return "INSERT INTO " + quoted_table + " DEFAULT VALUES"


def _encode_sqlite_column_value(
    column: Attr[Any, Any, Any, Any, Any],
    value: object,
) -> object:
    return column.encode(value, backend="sqlite")


_SQLITE_QUERY_DIALECT = QueryDialect(
    current_timestamp_sql=CURRENT_TIMESTAMP_SQL,
    empty_insert_sql=_sqlite_empty_insert_sql,
    encode_column_value=_encode_sqlite_column_value,
    placeholder="?",
    quote_identifier=quote_sqlite_identifier,
)

register_query_dialect("sqlite", _SQLITE_QUERY_DIALECT)


def compile_sqlite_select_sql(
    query: AnySelectQuery,
) -> tuple[str, tuple[object, ...]]:
    """Compile a select query into parameterized SQLite SQL."""

    return compile_select_sql_for_dialect(query.state, _SQLITE_QUERY_DIALECT)


def compile_sqlite_write_sql(query: object) -> tuple[str, tuple[object, ...]]:
    """Compile a write query into parameterized SQLite SQL."""

    return compile_write_sql_for_dialect(query, _SQLITE_QUERY_DIALECT)


def materialize_sqlite_select_row(
    query: AnySelectQuery,
    row: Sequence[object],
    *,
    validate: bool = True,
) -> object:
    """Decode one SQLite result row according to a select query."""

    return materialize_select_row_for_backend(
        query.state,
        row,
        backend="sqlite",
        validate=validate,
    )


def materialize_sqlite_write_rows(
    query: object,
    rows: Sequence[Sequence[object]],
    *,
    validate: bool = True,
) -> list[object]:
    """Decode SQLite ``RETURNING`` rows from an insert into Fetched models."""

    return materialize_insert_returning_rows_for_backend(
        query,
        rows,
        backend="sqlite",
        validate=validate,
    )

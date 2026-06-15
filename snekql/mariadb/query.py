"""MariaDB SQL compilation and row materialization."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from snekql._query_dialect import QueryDialect
from snekql.mariadb.identifiers import quote_identifier as quote_mariadb_identifier
from snekql.query import (
    AnySelectQuery,
    compile_select_sql_for_dialect,
    compile_write_sql_for_dialect,
    materialize_insert_returning_rows_for_backend,
    materialize_select_row_for_backend,
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
    *,
    validate: bool = True,
) -> object:
    """Decode one MariaDB result row according to a select query."""

    return materialize_select_row_for_backend(
        query,
        row,
        backend="mariadb",
        validate=validate,
    )


def materialize_mariadb_write_rows(
    query: object,
    rows: Sequence[Sequence[object]],
    *,
    validate: bool = True,
) -> list[object]:
    """Decode MariaDB ``RETURNING`` rows from an insert into Fetched models."""

    return materialize_insert_returning_rows_for_backend(
        query,
        rows,
        backend="mariadb",
        validate=validate,
    )

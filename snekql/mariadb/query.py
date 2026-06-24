"""MariaDB SQL compilation and row materialization."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from snekql._query_compile import (
    compile_select_sql_for_dialect,
    compile_write_sql_for_dialect,
)
from snekql._query_dialect import QueryDialect, register_query_dialect
from snekql._query_materialize import (
    materialize_select_row_for_backend,
    materialize_write_returning_rows_for_backend,
)
from snekql.mariadb._dialect_sql import CURRENT_TIMESTAMP_SQL
from snekql.mariadb.identifiers import quote_identifier as quote_mariadb_identifier
from snekql.query import AnySelectQuery
from snekql.storage import Attr


def _mariadb_empty_insert_sql(quoted_table: str) -> str:
    return f"INSERT INTO {quoted_table} () VALUES ()"  # noqa: S608


def _encode_mariadb_column_value(
    column: Attr[Any, Any, Any, Any, Any],
    value: object,
) -> object:
    return column.encode(value, backend="mariadb")


_MARIADB_QUERY_DIALECT = QueryDialect(
    current_timestamp_sql=CURRENT_TIMESTAMP_SQL,
    empty_insert_sql=_mariadb_empty_insert_sql,
    encode_column_value=_encode_mariadb_column_value,
    placeholder="%s",
    quote_identifier=quote_mariadb_identifier,
)

register_query_dialect("mariadb", _MARIADB_QUERY_DIALECT)


def compile_mariadb_select_sql(
    query: AnySelectQuery,
) -> tuple[str, tuple[object, ...]]:
    """Compile a select query into parameterized MariaDB SQL."""

    return compile_select_sql_for_dialect(query.state, _MARIADB_QUERY_DIALECT)


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
        query.state,
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
    """Decode MariaDB ``RETURNING`` rows from a write query."""

    return materialize_write_returning_rows_for_backend(
        query,
        rows,
        backend="mariadb",
        validate=validate,
    )

"""MariaDB SQL compilation and row materialization."""

from __future__ import annotations

from collections.abc import Sequence

from snekql.query import AnySelectQuery, compile_select_sql, compile_write_sql
from snekql.query import materialize_select_row as materialize_sqlite_select_row


def _translate_sqlite_sql(sql: str) -> str:
    """Translate the shared v1 SQL shape to MariaDB quoting and placeholders."""

    return sql.replace('"', "`").replace("?", "%s")


def compile_mariadb_select_sql(
    query: AnySelectQuery,
) -> tuple[str, tuple[object, ...]]:
    """Compile a select query into parameterized MariaDB SQL."""

    sql, params = compile_select_sql(query)
    return _translate_sqlite_sql(sql), params


def compile_mariadb_write_sql(query: object) -> tuple[str, tuple[object, ...]]:
    """Compile a write query into parameterized MariaDB SQL."""

    sql, params = compile_write_sql(query)
    return _translate_sqlite_sql(sql), params


def materialize_mariadb_select_row(
    query: AnySelectQuery,
    row: Sequence[object],
) -> object:
    """Decode one MariaDB result row according to a select query."""

    return materialize_sqlite_select_row(query, row)

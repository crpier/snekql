"""Shared SQLite dialect SQL fragments and query Dialect registration."""

from __future__ import annotations

from typing import Any

from snekql._query_dialect import QueryDialect, register_query_dialect
from snekql.sqlite.identifiers import quote_identifier
from snekql.storage import Attr

# Server-side ISO-8601 UTC timestamp, shared by the CurrentTimestamp DDL default,
# the migration-history applied_at default, and update-time server expressions so
# every server clock value uses one identical text format.
CURRENT_TIMESTAMP_SQL = "strftime('%Y-%m-%dT%H:%M:%fZ', 'now')"


def _conflict_do_nothing_sql(targets: tuple[str, ...]) -> str:
    return f" ON CONFLICT ({', '.join(targets)}) DO NOTHING"


def _conflict_update_sql(targets: tuple[str, ...], assignments: str) -> str:
    return f" ON CONFLICT ({', '.join(targets)}) DO UPDATE SET {assignments}"


def _empty_insert_sql(quoted_table: str) -> str:
    return "INSERT INTO " + quoted_table + " DEFAULT VALUES"


def _encode_column_value(
    column: Attr[Any, Any, Any, Any, Any],
    value: object,
) -> object:
    return column.encode(value, backend="sqlite")


def _inserted_value_sql(quoted_column: str) -> str:
    return f"excluded.{quoted_column}"


SQLITE_QUERY_DIALECT = QueryDialect(
    conflict_do_nothing_sql=_conflict_do_nothing_sql,
    conflict_update_sql=_conflict_update_sql,
    current_timestamp_sql=CURRENT_TIMESTAMP_SQL,
    empty_insert_sql=_empty_insert_sql,
    encode_column_value=_encode_column_value,
    inserted_value_sql=_inserted_value_sql,
    placeholder="?",
    quote_identifier=quote_identifier,
    supports_delete_returning=True,
    supports_update_returning=True,
)

register_query_dialect("sqlite", SQLITE_QUERY_DIALECT)

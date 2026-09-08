"""Shared MariaDB dialect SQL fragments and query Dialect registration."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from snekql._query_dialect import QueryDialect, register_query_dialect
from snekql.errors import ModelValidationError
from snekql.mariadb.identifiers import quote_identifier
from snekql.storage import Attr

# Server-side timestamp with millisecond precision, shared by the CurrentTimestamp
# DDL default and update-time server expressions so both reference one fragment.
CURRENT_TIMESTAMP_SQL = "CURRENT_TIMESTAMP(3)"


def _conflict_do_nothing_sql(targets: tuple[str, ...]) -> str:
    target = targets[0]
    return f" ON DUPLICATE KEY UPDATE {target} = {target}"


def _conflict_update_sql(_targets: tuple[str, ...], assignments: str) -> str:
    return f" ON DUPLICATE KEY UPDATE {assignments}"


def _empty_insert_sql(quoted_table: str) -> str:
    return f"INSERT INTO {quoted_table} () VALUES ()"  # noqa: S608


def _encode_column_value(
    column: Attr[Any, Any, Any, Any, Any],
    value: object,
) -> object:
    return column.encode(value, backend="mariadb")


def _encode_sum_value(
    column: Attr[Any, Any, Any, Any, Any],
    value: object,
) -> object:
    """Native Decimal SUM bounds have no input-column precision/scale ceiling."""

    if column.storage_type_name != "Decimal" or value is None:
        return _encode_column_value(column, value)
    if not isinstance(value, Decimal) or not value.is_finite():
        msg = "native Decimal SUM comparison requires a finite Decimal"
        raise ModelValidationError(msg)
    return value


def _inserted_value_sql(quoted_column: str) -> str:
    return f"VALUES({quoted_column})"


MARIADB_QUERY_DIALECT = QueryDialect(
    conflict_do_nothing_sql=_conflict_do_nothing_sql,
    conflict_update_sql=_conflict_update_sql,
    current_timestamp_sql=CURRENT_TIMESTAMP_SQL,
    empty_insert_sql=_empty_insert_sql,
    encode_column_value=_encode_column_value,
    encode_sum_value=_encode_sum_value,
    inserted_value_sql=_inserted_value_sql,
    # MariaDB uses the maximum unsigned LIMIT to select all remaining rows.
    offset_only_limit_sql="LIMIT 18446744073709551615",
    placeholder="%s",
    quote_identifier=quote_identifier,
)

register_query_dialect("mariadb", MARIADB_QUERY_DIALECT)

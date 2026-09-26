"""Shared MariaDB dialect SQL fragments and query Dialect registration."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from snekql._query_dialect import ExplainMode, QueryDialect, register_query_dialect
from snekql._query_state import InsertState, LockWait, SelectState, WriteState
from snekql.errors import ModelValidationError, QueryCompilationError
from snekql.mariadb.identifiers import quote_identifier
from snekql.storage import Attr


# Server-side timestamp with millisecond precision, shared by the CurrentTimestamp
# DDL default and update-time server expressions so both reference one fragment.
def current_timestamp_sql(column: Attr[Any, Any, Any, Any, Any]) -> str:
    """Render the database clock in the destination's canonical representation."""
    column.require_current_timestamp()
    if column.storage_type_name == "DateTime":
        return f"CURRENT_TIMESTAMP({column.datetime_precision})"
    return "CONCAT(REPLACE(CURRENT_TIMESTAMP(6), ' ', 'T'), 'Z')"


def _conflict_do_nothing_sql(targets: tuple[str, ...]) -> str:
    target = targets[0]
    return f" ON DUPLICATE KEY UPDATE {target} = {target}"


def _conflict_update_sql(_targets: tuple[str, ...], assignments: str) -> str:
    return f" ON DUPLICATE KEY UPDATE {assignments}"


def _empty_insert_sql(quoted_table: str) -> str:
    return f"INSERT INTO {quoted_table} () VALUES ()"  # noqa: S608


def _encode_write_value(column: Attr[Any, Any, Any, Any, Any], value: object) -> object:
    """Writes must fit the destination; comparison bounds need not fit its precision."""
    return column.encode(value, backend="mariadb", write=True)


def _encode_column_value(
    column: Attr[Any, Any, Any, Any, Any],
    value: object,
) -> object:
    return column.encode(value, backend="mariadb")


def _encode_sum_value(
    column: Attr[Any, Any, Any, Any, Any],
    value: object,
) -> object:
    """Exact SUM bounds retain serialization without the input column's ceiling."""

    if column.storage_type_name == "Integer":
        return column.encode(value, backend="mariadb", integer_sum=True)

    if column.storage_type_name != "Decimal" or value is None:
        return _encode_column_value(column, value)
    if not isinstance(value, Decimal) or not value.is_finite():
        msg = "native Decimal SUM comparison requires a finite Decimal"
        raise ModelValidationError(msg)
    return value


def _inserted_value_sql(quoted_column: str) -> str:
    return f"VALUES({quoted_column})"


def _for_update_sql(wait: LockWait) -> str:
    """Keep MariaDB locking syntax in its dialect rather than shared compilation."""
    return {
        "block": "FOR UPDATE",
        "nowait": "FOR UPDATE NOWAIT",
        "skip_locked": "FOR UPDATE SKIP LOCKED",
    }[wait]


def _explain_sql(state: SelectState | WriteState, sql: str, mode: ExplainMode) -> str:
    """MariaDB uses ANALYZE, not EXPLAIN ANALYZE, for execution statistics."""

    if isinstance(state, InsertState):
        msg = "MariaDB plan inspection supports SELECT, UPDATE, and DELETE only"
        raise QueryCompilationError(msg)
    return ("ANALYZE " if mode == "analyze" else "EXPLAIN ") + sql


def _integer_literal_sql(placeholder: str) -> str:
    """Keep the full signed-64 width when MariaDB materializes a recursive anchor.

    A small bound integer, even CAST AS SIGNED, can become an INT32 temporary
    field. The intermediate exact decimal declares all 19 integer digits before
    the signed cast. Every accepted input already fits the signed-64 domain.
    """
    return f"CAST(CAST({placeholder} AS DECIMAL(19, 0)) AS SIGNED)"


MARIADB_QUERY_DIALECT = QueryDialect(
    integer_literal_sql=_integer_literal_sql,
    char_length_function="CHAR_LENGTH",
    conflict_do_nothing_sql=_conflict_do_nothing_sql,
    conflict_update_sql=_conflict_update_sql,
    current_timestamp_sql=current_timestamp_sql,
    empty_insert_sql=_empty_insert_sql,
    explain_sql=_explain_sql,
    for_update_sql=_for_update_sql,
    encode_column_value=_encode_column_value,
    encode_write_value=_encode_write_value,
    encode_sum_value=_encode_sum_value,
    inserted_value_sql=_inserted_value_sql,
    # MariaDB uses the maximum unsigned LIMIT to select all remaining rows.
    offset_only_limit_sql="LIMIT 18446744073709551615",
    placeholder="%s",
    quote_identifier=quote_identifier,
)

register_query_dialect("mariadb", MARIADB_QUERY_DIALECT)

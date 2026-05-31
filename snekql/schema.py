"""SQLite schema startup for snekql table models."""

from __future__ import annotations

import contextlib
import logging
from collections.abc import Sequence
from itertools import starmap
from typing import Any

from aiosqlite import Connection, Error

from snekql.errors import SchemaError, SchemaVerificationError
from snekql.model import Table, require_model_columns, require_model_table_name
from snekql.storage import Attr, CurrentTimestamp, SchemaPolicy

_LOGGER = logging.getLogger("snekql")


def quote_sqlite_identifier(identifier: str) -> str:
    """Quote a SQLite identifier with double-quote escaping."""

    escaped_identifier = identifier.replace('"', '""')
    return f'"{escaped_identifier}"'


def _compile_column_definition(
    name: str,
    column: Attr[Any, Any, Any, Any, Any],
) -> str:
    parts = [quote_sqlite_identifier(name), column.sqlite_storage_class]
    if column.primary_key:
        parts.append("PRIMARY KEY")
    if column.auto_increment:
        parts.append("AUTOINCREMENT")
    if column.nullable is False and not column.primary_key:
        parts.append("NOT NULL")
    if isinstance(column.server_default, CurrentTimestamp):
        parts.append("DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))")
    return " ".join(parts)


def _compile_create_table_sql(model: type[Table[Any]]) -> str:
    table_name = require_model_table_name(model)
    columns = require_model_columns(model)
    column_sql = ", ".join(starmap(_compile_column_definition, columns.items()))
    return f"CREATE TABLE {quote_sqlite_identifier(table_name)} ({column_sql}) STRICT"


async def _fetch_existing_create_table_sql(
    connection: Connection,
    table_name: str,
) -> str | None:
    cursor = await connection.execute(
        "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = ?",
        (table_name,),
    )
    try:
        row = await cursor.fetchone()
    finally:
        await cursor.close()
    if row is None:
        return None
    value = row[0]
    if not isinstance(value, str):
        msg = f"SQLite metadata for table {table_name!r} did not contain SQL text"
        raise SchemaVerificationError(
            msg,
        )
    return value


def _normalize_snekql_create_table_sql(sql: str) -> str:
    lines = [line.strip() for line in sql.strip().rstrip(";").splitlines()]
    normalized_sql = " ".join(line for line in lines if line)
    return normalized_sql.replace("( ", "(").replace(" )", ")").replace(" ,", ",")


async def _verify_or_create_model_table(
    connection: Connection,
    model: type[Table[Any]],
    schema_policy: SchemaPolicy,
) -> None:
    table_name = require_model_table_name(model)
    expected_sql = _compile_create_table_sql(model)
    existing_sql = await _fetch_existing_create_table_sql(connection, table_name)
    if existing_sql is None:
        _ = await connection.execute(expected_sql)
        return
    if _normalize_snekql_create_table_sql(
        existing_sql,
    ) == _normalize_snekql_create_table_sql(expected_sql):
        return
    message = f"schema drift detected for table {table_name!r}"
    if schema_policy == "strict":
        raise SchemaVerificationError(message)
    _LOGGER.warning(
        "schema drift detected",
        extra={"table_name": table_name},
    )


def _validate_schema_models(models: Sequence[type[Table[Any]]]) -> None:
    table_names: set[str] = set()
    for model in models:
        table_name = require_model_table_name(model)
        if table_name in table_names:
            msg = f"duplicate table name: {table_name!r}"
            raise SchemaError(msg)
        table_names.add(table_name)


async def _rollback_schema_setup(connection: Connection) -> None:
    with contextlib.suppress(Error):
        _ = await connection.execute("ROLLBACK")


def _validate_schema_policy(schema_policy: SchemaPolicy) -> None:
    if schema_policy not in {"strict", "warn"}:
        msg = "schema_policy must be 'strict' or 'warn'"
        raise SchemaError(msg)


async def _initialize_sqlite_schema(
    connection: Connection,
    models: Sequence[type[Table[Any]]],
    schema_policy: SchemaPolicy,
) -> None:
    _validate_schema_policy(schema_policy)
    _validate_schema_models(models)
    if not models:
        return
    try:
        _ = await connection.execute("BEGIN")
        for model in models:
            await _verify_or_create_model_table(connection, model, schema_policy)
        _ = await connection.execute("COMMIT")
    except Error as error:
        await _rollback_schema_setup(connection)
        msg = "SQLite schema setup failed"
        raise SchemaError(msg) from error
    except Exception:
        await _rollback_schema_setup(connection)
        raise


def validate_schema_models(models: Sequence[type[Table[Any]]]) -> None:
    """Reject duplicate resolved table names before schema startup."""

    _validate_schema_models(models)


def validate_schema_policy(schema_policy: SchemaPolicy) -> None:
    """Reject unsupported schema policy values."""

    _validate_schema_policy(schema_policy)


async def initialize_sqlite_schema(
    connection: Connection,
    models: Sequence[type[Table[Any]]],
    schema_policy: SchemaPolicy,
) -> None:
    """Create or verify all configured SQLite tables transactionally."""

    await _initialize_sqlite_schema(connection, models, schema_policy)

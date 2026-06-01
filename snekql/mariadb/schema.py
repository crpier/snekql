"""MariaDB schema startup for snekql table models."""

from __future__ import annotations

from collections.abc import Sequence
from itertools import starmap
from typing import Any, cast

from snekql.errors import SchemaError
from snekql.mariadb.identifiers import quote_identifier
from snekql.model import Table, require_model_columns, require_model_table_name
from snekql.storage import Attr, SchemaPolicy


def _compile_column_type(column: Attr[Any, Any, Any, Any, Any]) -> str:
    """Map the initial shared value families to MariaDB column types."""

    column_types = {
        "Blob": "BLOB",
        "Boolean": "BOOLEAN",
        "DateTime": "DATETIME(3)",
        "Integer": "BIGINT",
        "Json": "JSON",
        "Real": "DOUBLE",
        "Text": "TEXT",
    }
    try:
        return column_types[column.storage_type_name]
    except KeyError as error:
        msg = f"unsupported MariaDB column type: {column.storage_type_name}"
        raise SchemaError(msg) from error


def _compile_column_definition(
    name: str,
    column: Attr[Any, Any, Any, Any, Any],
) -> str:
    parts = [quote_identifier(name), _compile_column_type(column)]
    if column.nullable is False or column.primary_key:
        parts.append("NOT NULL")
    if column.auto_increment:
        parts.append("AUTO_INCREMENT")
    if column.primary_key:
        parts.append("PRIMARY KEY")
    return " ".join(parts)


def _compile_create_table_sql(model: type[Table[Any]]) -> str:
    table_name = require_model_table_name(model)
    columns = require_model_columns(model)
    column_sql = ", ".join(starmap(_compile_column_definition, columns.items()))
    return f"CREATE TABLE IF NOT EXISTS {quote_identifier(table_name)} ({column_sql})"


def _validate_schema_policy(schema_policy: SchemaPolicy) -> None:
    if schema_policy not in {"strict", "warn"}:
        msg = "schema_policy must be 'strict' or 'warn'"
        raise SchemaError(msg)


def _validate_schema_models(models: Sequence[type[Table[Any]]]) -> None:
    table_names: set[str] = set()
    for model in models:
        table_name = require_model_table_name(model)
        if table_name in table_names:
            msg = f"duplicate table name: {table_name!r}"
            raise SchemaError(msg)
        table_names.add(table_name)


async def _execute(connection: object, sql: str) -> None:
    """Execute one MariaDB schema statement with a dynamically imported driver."""

    connection_object = cast("Any", connection)
    cursor = await connection_object.cursor()
    try:
        _ = await cursor.execute(sql)
    finally:
        close_result = cursor.close()
        if close_result is not None:
            _ = await close_result


async def initialize_mariadb_schema(
    connection: object,
    models: Sequence[type[Table[Any]]],
    schema_policy: SchemaPolicy,
) -> None:
    """Create all configured MariaDB tables for the initial tracer bullet."""

    _validate_schema_policy(schema_policy)
    _validate_schema_models(models)
    for model in models:
        await _execute(connection, _compile_create_table_sql(model))

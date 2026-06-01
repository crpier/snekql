"""MariaDB schema startup for snekql table models."""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass
from itertools import starmap
from typing import Any, cast

from snekql.errors import SchemaError, SchemaVerificationError
from snekql.indexes import NormalizedIndex
from snekql.mariadb.identifiers import quote_identifier
from snekql.model import Table, require_model_columns, require_model_table_name
from snekql.storage import Attr, SchemaPolicy

_LOGGER = logging.getLogger("snekql")


@dataclass(frozen=True)
class _ColumnSignature:
    """Normalized MariaDB column metadata used for drift verification."""

    auto_increment: bool
    data_type: str
    max_length: int | None
    name: str
    nullable: bool
    primary_key: bool


@dataclass(frozen=True)
class _IndexSignature:
    """Normalized MariaDB index metadata used for drift verification."""

    column_names: tuple[str, ...]
    name: str
    unique: bool


def _compile_column_type(column: Attr[Any, Any, Any, Any, Any]) -> str:
    """Map the initial shared value families to MariaDB column types."""

    column_types = {
        "Blob": "BLOB",
        "Boolean": "BOOLEAN",
        "DateTime": "DATETIME(3)",
        "Integer": "BIGINT",
        "Json": "JSON",
        "Real": "DOUBLE",
        "Text": "VARCHAR(255)",
    }
    try:
        return column_types[column.storage_type_name]
    except KeyError as error:
        msg = f"unsupported MariaDB column type: {column.storage_type_name}"
        raise SchemaError(msg) from error


def _column_data_type(column: Attr[Any, Any, Any, Any, Any]) -> str:
    """Return information_schema.DATA_TYPE expected for a column."""

    data_types = {
        "Blob": "blob",
        "Boolean": "tinyint",
        "DateTime": "datetime",
        "Integer": "bigint",
        "Json": "longtext",
        "Real": "double",
        "Text": "varchar",
    }
    try:
        return data_types[column.storage_type_name]
    except KeyError as error:
        msg = f"unsupported MariaDB column type: {column.storage_type_name}"
        raise SchemaError(msg) from error


def _column_max_length(column: Attr[Any, Any, Any, Any, Any]) -> int | None:
    if column.storage_type_name == "Text":
        return 255
    return None


def _expected_column_signature(
    name: str,
    column: Attr[Any, Any, Any, Any, Any],
) -> _ColumnSignature:
    return _ColumnSignature(
        auto_increment=column.auto_increment,
        data_type=_column_data_type(column),
        max_length=_column_max_length(column),
        name=name,
        nullable=column.nullable is not False and not column.primary_key,
        primary_key=column.primary_key,
    )


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
    return f"CREATE TABLE {quote_identifier(table_name)} ({column_sql})"


def _compile_create_index_sql(table_name: str, index: NormalizedIndex) -> str:
    unique_sql = "UNIQUE " if index.unique else ""
    column_sql = ", ".join(
        quote_identifier(column_name) for column_name in index.column_names
    )
    return (
        f"CREATE {unique_sql}INDEX {quote_identifier(index.name)} "
        f"ON {quote_identifier(table_name)} ({column_sql})"
    )


def _compile_column_unique_indexes(model: type[Table[Any]]) -> list[NormalizedIndex]:
    table_name = require_model_table_name(model)
    columns = require_model_columns(model)
    return [
        NormalizedIndex(
            column_names=(column_name,),
            name=f"ux_{table_name}_{column_name}",
            unique=True,
        )
        for column_name, column in columns.items()
        if column.unique
    ]


def _compile_model_indexes(model: type[Table[Any]]) -> list[NormalizedIndex]:
    table_indexes = getattr(model, "__snekql_indexes__", ())
    return [*_compile_column_unique_indexes(model), *table_indexes]


def _expected_index_signatures(model: type[Table[Any]]) -> list[_IndexSignature]:
    return [
        _IndexSignature(
            column_names=index.column_names,
            name=index.name,
            unique=index.unique,
        )
        for index in _compile_model_indexes(model)
    ]


def _validate_schema_policy(schema_policy: SchemaPolicy) -> None:
    if schema_policy not in {"strict", "warn"}:
        msg = "schema_policy must be 'strict' or 'warn'"
        raise SchemaError(msg)


def _validate_schema_models(models: Sequence[type[Table[Any]]]) -> None:
    table_names: set[str] = set()
    index_names: set[str] = set()
    for model in models:
        table_name = require_model_table_name(model)
        if table_name in table_names:
            msg = f"duplicate table name: {table_name!r}"
            raise SchemaError(msg)
        table_names.add(table_name)
        for index in _compile_model_indexes(model):
            if index.name in index_names:
                msg = f"duplicate index name: {index.name!r}"
                raise SchemaError(msg)
            index_names.add(index.name)


async def _close_cursor(cursor: object) -> None:
    close_result = cast("Any", cursor).close()
    if close_result is not None:
        _ = await close_result


async def _execute(
    connection: object,
    sql: str,
    params: tuple[object, ...] = (),
) -> None:
    """Execute one MariaDB schema statement with a dynamically imported driver."""

    cursor = await cast("Any", connection).cursor()
    try:
        _ = await cursor.execute(sql, params)
    finally:
        await _close_cursor(cursor)


async def _fetchall(
    connection: object,
    sql: str,
    params: tuple[object, ...] = (),
) -> Sequence[Sequence[object]]:
    cursor = await cast("Any", connection).cursor()
    try:
        _ = await cursor.execute(sql, params)
        rows = await cursor.fetchall()
    finally:
        await _close_cursor(cursor)
    return [cast("Sequence[object]", row) for row in rows]


async def _table_exists(connection: object, table_name: str) -> bool:
    rows = await _fetchall(
        connection,
        """
        SELECT 1
        FROM INFORMATION_SCHEMA.TABLES
        WHERE TABLE_SCHEMA = DATABASE()
          AND TABLE_NAME = %s
        """,
        (table_name,),
    )
    return bool(rows)


async def _fetch_existing_column_signatures(
    connection: object,
    table_name: str,
) -> list[_ColumnSignature]:
    rows = await _fetchall(
        connection,
        """
        SELECT COLUMN_NAME, DATA_TYPE, CHARACTER_MAXIMUM_LENGTH, IS_NULLABLE,
               COLUMN_KEY, EXTRA
        FROM INFORMATION_SCHEMA.COLUMNS
        WHERE TABLE_SCHEMA = DATABASE()
          AND TABLE_NAME = %s
        ORDER BY ORDINAL_POSITION
        """,
        (table_name,),
    )
    signatures: list[_ColumnSignature] = []
    for row in rows:
        name, data_type, max_length, nullable, column_key, extra = row
        parsed_max_length = (
            int(max_length) if isinstance(max_length, int | str) else None
        )
        signatures.append(
            _ColumnSignature(
                auto_increment="auto_increment" in str(extra),
                data_type=str(data_type),
                max_length=parsed_max_length,
                name=str(name),
                nullable=nullable == "YES",
                primary_key=column_key == "PRI",
            )
        )
    return signatures


async def _fetch_existing_index_signatures(
    connection: object,
    table_name: str,
) -> list[_IndexSignature]:
    rows = await _fetchall(
        connection,
        """
        SELECT INDEX_NAME, NON_UNIQUE,
               GROUP_CONCAT(COLUMN_NAME ORDER BY SEQ_IN_INDEX)
        FROM INFORMATION_SCHEMA.STATISTICS
        WHERE TABLE_SCHEMA = DATABASE()
          AND TABLE_NAME = %s
          AND INDEX_NAME <> 'PRIMARY'
        GROUP BY INDEX_NAME, NON_UNIQUE
        ORDER BY INDEX_NAME
        """,
        (table_name,),
    )
    indexes: list[_IndexSignature] = []
    for row in rows:
        name, non_unique, column_csv = row
        indexes.append(
            _IndexSignature(
                column_names=tuple(str(column_csv).split(",")),
                name=str(name),
                unique=non_unique == 0,
            )
        )
    return indexes


async def _report_schema_drift(
    schema_policy: SchemaPolicy,
    table_name: str,
) -> None:
    message = f"schema drift detected for table {table_name!r}"
    if schema_policy == "strict":
        raise SchemaVerificationError(message)
    _LOGGER.warning(
        "schema drift detected",
        extra={"table_name": table_name},
    )


async def _verify_model_schema(
    connection: object,
    model: type[Table[Any]],
    schema_policy: SchemaPolicy,
) -> None:
    table_name = require_model_table_name(model)
    columns = require_model_columns(model)
    expected_columns = [
        _expected_column_signature(name, column) for name, column in columns.items()
    ]
    existing_columns = await _fetch_existing_column_signatures(connection, table_name)
    if existing_columns != expected_columns:
        await _report_schema_drift(schema_policy, table_name)
        return
    expected_indexes = sorted(
        _expected_index_signatures(model), key=lambda index: index.name
    )
    existing_indexes = await _fetch_existing_index_signatures(connection, table_name)
    if existing_indexes != expected_indexes:
        await _report_schema_drift(schema_policy, table_name)


async def _create_model_schema(connection: object, model: type[Table[Any]]) -> None:
    table_name = require_model_table_name(model)
    await _execute(connection, _compile_create_table_sql(model))
    for index in _compile_model_indexes(model):
        await _execute(connection, _compile_create_index_sql(table_name, index))


async def initialize_mariadb_schema(
    connection: object,
    models: Sequence[type[Table[Any]]],
    schema_policy: SchemaPolicy,
) -> None:
    """Create or verify all configured MariaDB tables."""

    _validate_schema_policy(schema_policy)
    _validate_schema_models(models)
    for model in models:
        table_name = require_model_table_name(model)
        if await _table_exists(connection, table_name):
            await _verify_model_schema(connection, model, schema_policy)
        else:
            await _create_model_schema(connection, model)

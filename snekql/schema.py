"""SQLite schema startup for snekql table models."""

from __future__ import annotations

import contextlib
from collections.abc import Sequence
from itertools import starmap
from typing import Any

from aiosqlite import Connection, Error

from snekql.errors import SchemaError, SchemaVerificationError
from snekql.indexes import NormalizedIndex
from snekql.model import Table, require_model_columns, require_model_table_name
from snekql.sqlite.identifiers import quote_identifier
from snekql.storage import Attr, CurrentTimestamp, SchemaPolicy
from snekql.structured_logging import ResolvedStructuredLogger


def quote_sqlite_identifier(identifier: str) -> str:
    """Quote a SQLite identifier with double-quote escaping."""

    return quote_identifier(identifier)


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


def _compile_create_index_sql(table_name: str, index: NormalizedIndex) -> str:
    unique_sql = "UNIQUE " if index.unique else ""
    column_sql = ", ".join(
        quote_sqlite_identifier(column_name) for column_name in index.column_names
    )
    return (
        f"CREATE {unique_sql}INDEX {quote_sqlite_identifier(index.name)} "
        f"ON {quote_sqlite_identifier(table_name)} ({column_sql})"
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


def _compile_model_index_sql(model: type[Table[Any]]) -> list[str]:
    table_name = require_model_table_name(model)
    return [
        _compile_create_index_sql(table_name, index)
        for index in _compile_model_indexes(model)
    ]


async def _fetch_existing_create_index_sql(
    connection: Connection,
    table_name: str,
) -> list[str | None]:
    cursor = await connection.execute(
        """
        SELECT sql FROM sqlite_master
        WHERE type = 'index' AND tbl_name = ?
        ORDER BY rowid
        """,
        (table_name,),
    )
    try:
        rows = await cursor.fetchall()
    finally:
        await cursor.close()
    return [row[0] if isinstance(row[0], str) else None for row in rows]


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


async def _report_schema_drift(
    schema_policy: SchemaPolicy,
    table_name: str,
    *,
    logger: ResolvedStructuredLogger,
) -> None:
    message = f"schema drift detected for table {table_name!r}"
    if schema_policy == "strict":
        raise SchemaVerificationError(message)
    logger.warning(
        "schema drift detected",
        table_name=table_name,
    )


async def _verify_model_indexes(
    connection: Connection,
    model: type[Table[Any]],
    schema_policy: SchemaPolicy,
    *,
    logger: ResolvedStructuredLogger,
) -> None:
    table_name = require_model_table_name(model)
    expected_sql = _compile_model_index_sql(model)
    existing_sql = await _fetch_existing_create_index_sql(connection, table_name)
    if existing_sql == expected_sql:
        logger.debug("schema indexes verified", table_name=table_name)
        return
    await _report_schema_drift(schema_policy, table_name, logger=logger)


async def _verify_or_create_model_table(
    connection: Connection,
    model: type[Table[Any]],
    schema_policy: SchemaPolicy,
    *,
    logger: ResolvedStructuredLogger,
) -> None:
    table_name = require_model_table_name(model)
    expected_sql = _compile_create_table_sql(model)
    existing_sql = await _fetch_existing_create_table_sql(connection, table_name)
    if existing_sql is None:
        _ = await connection.execute(expected_sql)
        logger.debug("schema table created", table_name=table_name)
        for index_sql in _compile_model_index_sql(model):
            _ = await connection.execute(index_sql)
            logger.debug("schema index created", table_name=table_name, sql=index_sql)
        return
    if _normalize_snekql_create_table_sql(
        existing_sql,
    ) != _normalize_snekql_create_table_sql(expected_sql):
        await _report_schema_drift(schema_policy, table_name, logger=logger)
        return
    logger.debug("schema table verified", table_name=table_name)
    await _verify_model_indexes(connection, model, schema_policy, logger=logger)


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
    *,
    logger: ResolvedStructuredLogger,
) -> None:
    _validate_schema_policy(schema_policy)
    _validate_schema_models(models)
    if not models:
        return
    logger.debug("schema startup started", model_count=len(models))
    try:
        _ = await connection.execute("BEGIN")
        for model in models:
            await _verify_or_create_model_table(
                connection,
                model,
                schema_policy,
                logger=logger,
            )
        _ = await connection.execute("COMMIT")
        logger.debug("schema startup completed", model_count=len(models))
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
    *,
    logger: ResolvedStructuredLogger,
) -> None:
    """Create or verify all configured SQLite tables transactionally."""

    await _initialize_sqlite_schema(
        connection,
        models,
        schema_policy,
        logger=logger,
    )

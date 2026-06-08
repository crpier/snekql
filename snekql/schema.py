"""SQLite schema startup for snekql table models."""

from __future__ import annotations

import contextlib
from collections.abc import Sequence
from typing import Any

from aiosqlite import Connection, Error

from snekql._schema_plan import (
    PlannedColumn,
    PlannedModel,
    build_schema_plan,
)
from snekql._schema_plan import (
    validate_schema_policy as validate_planned_schema_policy,
)
from snekql.errors import SchemaError, SchemaVerificationError
from snekql.indexes import NormalizedIndex
from snekql.model import Table
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


def _compile_planned_column_definition(planned_column: PlannedColumn) -> str:
    return _compile_column_definition(planned_column.name, planned_column.column)


def _compile_create_table_sql(planned_model: PlannedModel) -> str:
    column_sql = ", ".join(
        _compile_planned_column_definition(planned_column)
        for planned_column in planned_model.columns
    )
    return (
        f"CREATE TABLE {quote_sqlite_identifier(planned_model.table_name)} "
        f"({column_sql}) STRICT"
    )


def _compile_create_index_sql(table_name: str, index: NormalizedIndex) -> str:
    unique_sql = "UNIQUE " if index.unique else ""
    column_sql = ", ".join(
        quote_sqlite_identifier(column_name) for column_name in index.column_names
    )
    return (
        f"CREATE {unique_sql}INDEX {quote_sqlite_identifier(index.name)} "
        f"ON {quote_sqlite_identifier(table_name)} ({column_sql})"
    )


def _compile_model_index_sql(planned_model: PlannedModel) -> list[str]:
    return [
        _compile_create_index_sql(planned_model.table_name, index)
        for index in planned_model.indexes
    ]


async def _execute_schema_sql(
    connection: Connection,
    sql: str,
    params: tuple[object, ...] = (),
) -> None:
    """Execute schema DDL/control statements and always close their cursor."""

    cursor = await connection.execute(sql, params)
    try:
        return
    finally:
        await cursor.close()


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
    planned_model: PlannedModel,
    schema_policy: SchemaPolicy,
    logger: ResolvedStructuredLogger,
) -> None:
    expected_sql = _compile_model_index_sql(planned_model)
    existing_sql = await _fetch_existing_create_index_sql(
        connection,
        planned_model.table_name,
    )
    if existing_sql == expected_sql:
        logger.debug("schema indexes verified", table_name=planned_model.table_name)
        return
    await _report_schema_drift(schema_policy, planned_model.table_name, logger=logger)


async def _verify_or_create_model_table(
    connection: Connection,
    planned_model: PlannedModel,
    schema_policy: SchemaPolicy,
    logger: ResolvedStructuredLogger,
) -> None:
    expected_sql = _compile_create_table_sql(planned_model)
    existing_sql = await _fetch_existing_create_table_sql(
        connection,
        planned_model.table_name,
    )
    if existing_sql is None:
        await _execute_schema_sql(connection, expected_sql)
        logger.debug("schema table created", table_name=planned_model.table_name)
        for index_sql in _compile_model_index_sql(planned_model):
            await _execute_schema_sql(connection, index_sql)
            logger.debug(
                "schema index created",
                table_name=planned_model.table_name,
                sql=index_sql,
            )
        return
    if _normalize_snekql_create_table_sql(
        existing_sql,
    ) != _normalize_snekql_create_table_sql(expected_sql):
        await _report_schema_drift(
            schema_policy, planned_model.table_name, logger=logger
        )
        return
    logger.debug("schema table verified", table_name=planned_model.table_name)
    await _verify_model_indexes(connection, planned_model, schema_policy, logger)


async def _rollback_schema_setup(connection: Connection) -> None:
    with contextlib.suppress(Error):
        await _execute_schema_sql(connection, "ROLLBACK")


async def _initialize_sqlite_schema(
    connection: Connection,
    models: Sequence[type[Table[Any]]],
    schema_policy: SchemaPolicy,
    logger: ResolvedStructuredLogger,
) -> None:
    validate_planned_schema_policy(schema_policy)
    plan = build_schema_plan(models)
    if not plan.models:
        return
    logger.debug("schema startup started", model_count=len(plan.models))
    try:
        await _execute_schema_sql(connection, "BEGIN")
        for planned_model in plan.models:
            await _verify_or_create_model_table(
                connection,
                planned_model,
                schema_policy,
                logger,
            )
        await _execute_schema_sql(connection, "COMMIT")
        logger.debug("schema startup completed", model_count=len(plan.models))
    except Error as error:
        await _rollback_schema_setup(connection)
        msg = "SQLite schema setup failed"
        raise SchemaError(msg) from error
    except Exception:
        await _rollback_schema_setup(connection)
        raise


def validate_schema_models(models: Sequence[type[Table[Any]]]) -> None:
    """Reject duplicate resolved table names before schema startup."""

    _ = build_schema_plan(models)


def validate_schema_policy(schema_policy: SchemaPolicy) -> None:
    """Reject unsupported schema policy values."""

    validate_planned_schema_policy(schema_policy)


async def initialize_sqlite_schema(
    connection: Connection,
    models: Sequence[type[Table[Any]]],
    schema_policy: SchemaPolicy,
    logger: ResolvedStructuredLogger,
) -> None:
    """Create or verify all configured SQLite tables transactionally."""

    await _initialize_sqlite_schema(
        connection,
        models,
        schema_policy,
        logger,
    )

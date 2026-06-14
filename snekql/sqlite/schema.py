"""SQLite schema backend: DDL compilation and sqlite_master inspection."""

from __future__ import annotations

import contextlib
from collections.abc import AsyncGenerator, Sequence
from typing import Any

from aiosqlite import Connection, Error

from snekql._schema_plan import PlannedColumn, PlannedForeignKey, PlannedModel
from snekql._schema_startup import initialize_schema
from snekql.errors import SchemaError, SchemaVerificationError
from snekql.indexes import NormalizedIndex
from snekql.model import Table
from snekql.sqlite.identifiers import quote_identifier
from snekql.storage import Attr, CurrentTimestamp, SchemaPolicy
from snekql.structured_logging import ResolvedStructuredLogger


def _compile_column_definition(
    name: str,
    column: Attr[Any, Any, Any, Any, Any],
) -> str:
    parts = [quote_identifier(name), column.sqlite_storage_class]
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


def _compile_foreign_key_constraint(foreign_key: PlannedForeignKey) -> str:
    return (
        f"FOREIGN KEY ({quote_identifier(foreign_key.column_name)}) "
        f"REFERENCES {quote_identifier(foreign_key.target_table)} "
        f"({quote_identifier(foreign_key.target_column)})"
    )


def _compile_create_table_sql(planned_model: PlannedModel) -> str:
    definitions = [
        _compile_planned_column_definition(planned_column)
        for planned_column in planned_model.columns
    ]
    definitions.extend(
        _compile_foreign_key_constraint(foreign_key)
        for foreign_key in planned_model.foreign_keys
    )
    table_body = ", ".join(definitions)
    return (
        f"CREATE TABLE {quote_identifier(planned_model.table_name)} "
        f"({table_body}) STRICT"
    )


def _compile_create_index_sql(table_name: str, index: NormalizedIndex) -> str:
    unique_sql = "UNIQUE " if index.unique else ""
    column_sql = ", ".join(
        quote_identifier(column_name) for column_name in index.column_names
    )
    return (
        f"CREATE {unique_sql}INDEX {quote_identifier(index.name)} "
        f"ON {quote_identifier(table_name)} ({column_sql})"
    )


def _compile_model_index_sql(planned_model: PlannedModel) -> list[str]:
    return [
        _compile_create_index_sql(planned_model.table_name, index)
        for index in planned_model.indexes
    ]


def _normalize_snekql_create_table_sql(sql: str) -> str:
    lines = [line.strip() for line in sql.strip().rstrip(";").splitlines()]
    normalized_sql = " ".join(line for line in lines if line)
    return normalized_sql.replace("( ", "(").replace(" )", ")").replace(" ,", ",")


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


async def _rollback_schema_setup(connection: Connection) -> None:
    with contextlib.suppress(Error):
        await _execute_schema_sql(connection, "ROLLBACK")


class SQLiteSchemaBackend:
    """Schema backend adapter answering the neutral startup flow for SQLite."""

    def __init__(self, connection: Connection) -> None:
        self.connection: Connection = connection

    @contextlib.asynccontextmanager
    async def startup_transaction(self) -> AsyncGenerator[None]:
        """Run schema startup transactionally, rolling back on any failure."""

        await _execute_schema_sql(self.connection, "BEGIN")
        try:
            yield
            await _execute_schema_sql(self.connection, "COMMIT")
        except Error as error:
            await _rollback_schema_setup(self.connection)
            msg = "SQLite schema setup failed"
            raise SchemaError(msg) from error
        except Exception:
            await _rollback_schema_setup(self.connection)
            raise

    async def table_exists(self, table_name: str) -> bool:
        existing_sql = await _fetch_existing_create_table_sql(
            self.connection,
            table_name,
        )
        return existing_sql is not None

    async def table_matches(self, planned_model: PlannedModel) -> bool:
        existing_sql = await _fetch_existing_create_table_sql(
            self.connection,
            planned_model.table_name,
        )
        if existing_sql is None:
            return False
        expected_sql = _compile_create_table_sql(planned_model)
        return _normalize_snekql_create_table_sql(
            existing_sql,
        ) == _normalize_snekql_create_table_sql(expected_sql)

    async def indexes_match(self, planned_model: PlannedModel) -> bool:
        expected_sql = _compile_model_index_sql(planned_model)
        existing_sql = await _fetch_existing_create_index_sql(
            self.connection,
            planned_model.table_name,
        )
        return existing_sql == expected_sql

    async def create_table(self, planned_model: PlannedModel) -> None:
        await _execute_schema_sql(
            self.connection,
            _compile_create_table_sql(planned_model),
        )

    async def create_index(self, table_name: str, index: NormalizedIndex) -> str:
        sql = _compile_create_index_sql(table_name, index)
        await _execute_schema_sql(self.connection, sql)
        return sql


async def initialize_sqlite_schema(
    connection: Connection,
    models: Sequence[type[Table[Any]]],
    schema_policy: SchemaPolicy,
    logger: ResolvedStructuredLogger,
) -> None:
    """Create or verify all configured SQLite tables transactionally."""

    await initialize_schema(
        SQLiteSchemaBackend(connection),
        models,
        schema_policy,
        logger=logger,
    )

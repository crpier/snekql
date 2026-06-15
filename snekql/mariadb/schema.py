"""MariaDB schema startup for snekql table models."""

from __future__ import annotations

from collections.abc import AsyncGenerator, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any, cast

from snekql._schema_plan import PlannedColumn, PlannedForeignKey, PlannedModel
from snekql._schema_startup import initialize_schema
from snekql.errors import SchemaError
from snekql.indexes import NormalizedIndex
from snekql.mariadb.identifiers import quote_identifier
from snekql.model import Table
from snekql.storage import Attr, CurrentTimestamp, SchemaPolicy
from snekql.structured_logging import ResolvedStructuredLogger


@dataclass(frozen=True)
class _ColumnSignature:
    """Normalized MariaDB column metadata used for drift verification."""

    auto_increment: bool
    collation: str | None
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


# Case-sensitive, byte-ordered collation chosen so MariaDB string equality and
# UNIQUE constraints match SQLite's default BINARY collation instead of the
# case-insensitive utf8mb4 default.
TEXT_COLLATION = "utf8mb4_bin"


def _compile_column_type(column: Attr[Any, Any, Any, Any, Any]) -> str:
    """Map the initial shared value families to MariaDB column types."""

    column_types = {
        "Blob": "BLOB",
        "Boolean": "BOOLEAN",
        "DateTime": "DATETIME(3)",
        "Integer": "BIGINT",
        "Json": "JSON",
        "Real": "DOUBLE",
        "Text": f"VARCHAR(255) CHARACTER SET utf8mb4 COLLATE {TEXT_COLLATION}",
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


def _column_collation(column: Attr[Any, Any, Any, Any, Any]) -> str | None:
    """Text columns pin a case-sensitive collation; others have none here."""

    if column.storage_type_name == "Text":
        return TEXT_COLLATION
    return None


def _expected_column_signature(planned_column: PlannedColumn) -> _ColumnSignature:
    column = planned_column.column
    return _ColumnSignature(
        auto_increment=column.auto_increment,
        collation=_column_collation(column),
        data_type=_column_data_type(column),
        max_length=_column_max_length(column),
        name=planned_column.name,
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
    if isinstance(column.server_default, CurrentTimestamp):
        parts.append("DEFAULT CURRENT_TIMESTAMP(3)")
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
        f"({table_body}) ENGINE=InnoDB"
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


def _expected_index_signatures(planned_model: PlannedModel) -> list[_IndexSignature]:
    return [
        _IndexSignature(
            column_names=index.column_names,
            name=index.name,
            unique=index.unique,
        )
        for index in planned_model.indexes
    ]


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


async def _table_uses_innodb(connection: object, table_name: str) -> bool:
    """Whether an existing table uses InnoDB, required to enforce foreign keys."""

    rows = await _fetchall(
        connection,
        """
        SELECT ENGINE
        FROM INFORMATION_SCHEMA.TABLES
        WHERE TABLE_SCHEMA = DATABASE()
          AND TABLE_NAME = %s
        """,
        (table_name,),
    )
    if not rows:
        return False
    return str(rows[0][0]).lower() == "innodb"


async def _fetch_existing_column_signatures(
    connection: object,
    table_name: str,
) -> list[_ColumnSignature]:
    rows = await _fetchall(
        connection,
        """
        SELECT COLUMN_NAME, DATA_TYPE, CHARACTER_MAXIMUM_LENGTH, IS_NULLABLE,
               COLUMN_KEY, EXTRA, COLLATION_NAME
        FROM INFORMATION_SCHEMA.COLUMNS
        WHERE TABLE_SCHEMA = DATABASE()
          AND TABLE_NAME = %s
        ORDER BY ORDINAL_POSITION
        """,
        (table_name,),
    )
    signatures: list[_ColumnSignature] = []
    for row in rows:
        name, data_type, max_length, nullable, column_key, extra, collation = row
        parsed_max_length = (
            int(max_length) if isinstance(max_length, int | str) else None
        )
        signatures.append(
            _ColumnSignature(
                auto_increment="auto_increment" in str(extra),
                collation=(
                    str(collation)
                    if str(data_type) == "varchar" and collation
                    else None
                ),
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


class MariaDBSchemaBackend:
    """Schema backend adapter answering the neutral startup flow for MariaDB."""

    def __init__(self, connection: object) -> None:
        self.connection: object = connection

    @asynccontextmanager
    async def startup_transaction(self) -> AsyncGenerator[None]:
        """MariaDB DDL is not transactional; startup runs without one."""

        yield

    async def table_exists(self, table_name: str) -> bool:
        return await _table_exists(self.connection, table_name)

    async def table_matches(self, planned_model: PlannedModel) -> bool:
        if not await _table_uses_innodb(self.connection, planned_model.table_name):
            return False
        expected_columns = [
            _expected_column_signature(planned_column)
            for planned_column in planned_model.columns
        ]
        existing_columns = await _fetch_existing_column_signatures(
            self.connection,
            planned_model.table_name,
        )
        return existing_columns == expected_columns

    async def indexes_match(self, planned_model: PlannedModel) -> bool:
        expected_indexes = sorted(
            _expected_index_signatures(planned_model), key=lambda index: index.name
        )
        existing_indexes = await _fetch_existing_index_signatures(
            self.connection,
            planned_model.table_name,
        )
        return existing_indexes == expected_indexes

    async def create_table(self, planned_model: PlannedModel) -> None:
        await _execute(self.connection, _compile_create_table_sql(planned_model))

    async def create_index(self, table_name: str, index: NormalizedIndex) -> str:
        sql = _compile_create_index_sql(table_name, index)
        await _execute(self.connection, sql)
        return sql


async def initialize_mariadb_schema(
    connection: object,
    models: Sequence[type[Table[Any]]],
    schema_policy: SchemaPolicy,
    logger: ResolvedStructuredLogger,
    *,
    create_missing: bool = True,
) -> None:
    """Create or verify all configured MariaDB tables."""

    await initialize_schema(
        MariaDBSchemaBackend(connection),
        models,
        schema_policy,
        logger=logger,
        create_missing=create_missing,
    )

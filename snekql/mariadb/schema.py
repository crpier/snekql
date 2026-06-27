"""MariaDB schema verification and scaffold for snekql table models."""

from __future__ import annotations

from collections.abc import AsyncGenerator, Sequence
from contextlib import asynccontextmanager
from typing import Any, cast

from snekql._scaffold import scaffold_ddl, scaffold_statements
from snekql._schema_compile import (
    expected_table_shape,
)
from snekql._schema_dialect import SchemaDialect
from snekql._schema_plan import PlannedColumn, PlannedModel
from snekql._schema_shape import ColumnShape, IndexShape, TableShape
from snekql._schema_startup import verify_schema
from snekql.errors import SchemaError
from snekql.mariadb._dialect_sql import CURRENT_TIMESTAMP_SQL
from snekql.mariadb.identifiers import quote_identifier
from snekql.model import Table
from snekql.storage import Attr, CurrentTimestamp, SchemaPolicy

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
        "Uuid": "UUID",
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
        "Uuid": "uuid",
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


def _format_storage_type(data_type: str, max_length: int | None) -> str:
    """Fold a column's length into its type token (e.g. ``varchar(255)``).

    Only variable-length string types carry a meaningful declared length here,
    so the length is appended for ``varchar`` and ignored for fixed-width types.
    """

    if data_type == "varchar" and max_length is not None:
        return f"varchar({max_length})"
    return data_type


def _requires_not_null(column: Attr[Any, Any, Any, Any, Any]) -> bool:
    # MariaDB requires NOT NULL on every primary-key part, so the column DDL and
    # the expected shape share this one predicate to stay in lockstep.
    return column.nullable is False or column.primary_key


def _expected_column_shape(planned_column: PlannedColumn) -> ColumnShape:
    column = planned_column.column
    return ColumnShape(
        name=planned_column.name,
        storage_type=_format_storage_type(
            _column_data_type(column), _column_max_length(column)
        ),
        nullable=not _requires_not_null(column),
        primary_key=column.primary_key,
        auto_increment=column.auto_increment,
        has_server_default=column.server_default is CurrentTimestamp,
        collation=_column_collation(column),
    )


def _compile_column_definition(planned_column: PlannedColumn) -> str:
    column = planned_column.column
    parts = [quote_identifier(planned_column.name), _compile_column_type(column)]
    if _requires_not_null(column):
        parts.append("NOT NULL")
    if column.auto_increment:
        parts.append("AUTO_INCREMENT")
    # A composite primary key is rendered once as a table-level constraint, so its
    # member columns must not also carry an inline PRIMARY KEY.
    if column.primary_key and not planned_column.composite_pk:
        parts.append("PRIMARY KEY")
    if column.server_default is CurrentTimestamp:
        parts.append(f"DEFAULT {CURRENT_TIMESTAMP_SQL}")
    return " ".join(parts)


# Foreign keys are not part of the MariaDB shape: MariaDB auto-creates a backing
# index for each enforced constraint, so verifying foreign keys here would
# require modeling those implicit indexes. The constraints are still created with
# the table; verifying them is intentionally out of scope.
_SCHEMA_DIALECT = SchemaDialect(
    quote_identifier=quote_identifier,
    compile_column_definition=_compile_column_definition,
    expected_column_shape=_expected_column_shape,
    table_suffix="ENGINE=InnoDB",
    verifies_foreign_keys=False,
)


async def _close_cursor(cursor: object) -> None:
    close_result = cast("Any", cursor).close()
    if close_result is not None:
        _ = await close_result


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


async def _fetch_existing_column_shapes(
    connection: object,
    table_name: str,
) -> tuple[ColumnShape, ...]:
    rows = await _fetchall(
        connection,
        """
        SELECT COLUMN_NAME, DATA_TYPE, CHARACTER_MAXIMUM_LENGTH, IS_NULLABLE,
               COLUMN_KEY, EXTRA, COLLATION_NAME, COLUMN_DEFAULT
        FROM INFORMATION_SCHEMA.COLUMNS
        WHERE TABLE_SCHEMA = DATABASE()
          AND TABLE_NAME = %s
        ORDER BY ORDINAL_POSITION
        """,
        (table_name,),
    )
    shapes: list[ColumnShape] = []
    for row in rows:
        name, data_type, max_length, nullable, column_key, extra, collation = row[:7]
        default = row[7]
        parsed_max_length = (
            int(max_length) if isinstance(max_length, int | str) else None
        )
        shapes.append(
            ColumnShape(
                name=str(name),
                storage_type=_format_storage_type(str(data_type), parsed_max_length),
                nullable=nullable == "YES",
                primary_key=column_key == "PRI",
                auto_increment="auto_increment" in str(extra),
                has_server_default=default is not None,
                collation=(
                    str(collation)
                    if str(data_type) == "varchar" and collation
                    else None
                ),
            )
        )
    return tuple(shapes)


async def _fetch_existing_index_shapes(
    connection: object,
    table_name: str,
) -> tuple[IndexShape, ...]:
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
    return tuple(
        IndexShape(
            name=str(name),
            column_names=tuple(str(column_csv).split(",")),
            unique=non_unique == 0,
        )
        for name, non_unique, column_csv in rows
    )


class MariaDBSchemaBackend:
    """Schema backend adapter answering the neutral startup flow for MariaDB."""

    def __init__(self, connection: object) -> None:
        self.connection: object = connection

    @asynccontextmanager
    async def verification_transaction(self) -> AsyncGenerator[None]:
        """MariaDB schema verification reads the catalog without a transaction."""

        yield

    def expected_shape(self, planned_model: PlannedModel) -> TableShape:
        return expected_table_shape(planned_model, _SCHEMA_DIALECT)

    async def inspect_shape(self, planned_model: PlannedModel) -> TableShape | None:
        table_name = planned_model.table_name
        if not await _table_exists(self.connection, table_name):
            return None
        engine_innodb = await _table_uses_innodb(self.connection, table_name)
        return TableShape(
            table_name=table_name,
            columns=await _fetch_existing_column_shapes(self.connection, table_name),
            indexes=await _fetch_existing_index_shapes(self.connection, table_name),
            foreign_keys=(),
            storage_options=("ENGINE=InnoDB",) if engine_innodb else (),
        )


async def verify_mariadb_schema(
    connection: object,
    models: Sequence[type[Table[Any]]],
    schema_policy: SchemaPolicy,
) -> None:
    """Verify all configured MariaDB tables against the live schema."""

    await verify_schema(
        MariaDBSchemaBackend(connection),
        models,
        schema_policy,
    )


def scaffold_mariadb_ddl(models: Sequence[type[Table[Any]]]) -> str:
    """Emit the initial CREATE TABLE (and index) DDL for MariaDB models as text."""

    return scaffold_ddl(models, _SCHEMA_DIALECT)


def scaffold_mariadb_statements(
    models: Sequence[type[Table[Any]]],
) -> list[tuple[str, str]]:
    """Return (label, DDL) statement pairs for MariaDB model creation."""

    return scaffold_statements(models, _SCHEMA_DIALECT)

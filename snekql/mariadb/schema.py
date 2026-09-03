"""MariaDB schema verification and scaffold for snekql table models."""

from __future__ import annotations

from collections.abc import AsyncGenerator, Sequence
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, Any, cast

from snekql._scaffold import (
    require_scaffold_models,
    scaffold_ddl,
    scaffold_statements,
)
from snekql._schema_compile import (
    expected_table_shape,
)
from snekql._schema_dialect import SchemaDialect
from snekql._schema_plan import PlannedColumn, PlannedModel
from snekql._schema_shape import ColumnShape, ForeignKeyShape, IndexShape, TableShape
from snekql._schema_startup import verify_schema
from snekql._schema_verification import SchemaVerificationResult
from snekql.errors import SchemaError
from snekql.mariadb._dialect_sql import CURRENT_TIMESTAMP_SQL
from snekql.mariadb.identifiers import quote_identifier
from snekql.mariadb.model import Model
from snekql.model import Table
from snekql.storage import Attr, CurrentTimestamp, SchemaPolicy

# Case-sensitive, byte-ordered collation chosen so MariaDB string equality and
# UNIQUE constraints match SQLite's default BINARY collation instead of the
# case-insensitive utf8mb4 default.
if TYPE_CHECKING:
    from snekql.indexes import NormalizedIndex

TEXT_COLLATION = "utf8mb4_bin"


def _format_decimal_type(column: Attr[Any, Any, Any, Any, Any]) -> str:
    """Render a native DECIMAL type from its required precision metadata."""

    precision = column.decimal_precision
    scale = column.decimal_scale
    if precision is None or scale is None:
        msg = "Decimal column is missing precision metadata"
        raise SchemaError(msg)
    return f"DECIMAL({precision},{scale})"


def _compile_column_type(column: Attr[Any, Any, Any, Any, Any]) -> str:
    """Map the initial shared value families to MariaDB column types."""

    if column.storage_type_name == "Decimal":
        return _format_decimal_type(column)
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
        "Decimal": "decimal",
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


def _column_unsigned(column: Attr[Any, Any, Any, Any, Any]) -> bool | None:
    if column.storage_type_name in {"Boolean", "Decimal", "Integer", "Real"}:
        return False
    return None


def _column_collation(column: Attr[Any, Any, Any, Any, Any]) -> str | None:
    """Text columns pin a case-sensitive collation; others have none here."""

    if column.storage_type_name == "Text":
        return TEXT_COLLATION
    return None


def _column_numeric_precision(column: Attr[Any, Any, Any, Any, Any]) -> int | None:
    if column.storage_type_name == "Decimal":
        return column.decimal_precision
    return None


def _column_numeric_scale(column: Attr[Any, Any, Any, Any, Any]) -> int | None:
    if column.storage_type_name == "Decimal":
        return column.decimal_scale
    return None


def _format_storage_type(
    data_type: str,
    max_length: int | None,
    numeric_precision: int | None = None,
    numeric_scale: int | None = None,
) -> str:
    """Fold a column's declared parameters into its catalog type token."""

    if data_type == "varchar" and max_length is not None:
        return f"varchar({max_length})"
    if (
        data_type == "decimal"
        and numeric_precision is not None
        and numeric_scale is not None
    ):
        return f"decimal({numeric_precision},{numeric_scale})"
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
            _column_data_type(column),
            _column_max_length(column),
            _column_numeric_precision(column),
            _column_numeric_scale(column),
        ),
        nullable=not _requires_not_null(column),
        primary_key=column.primary_key,
        auto_increment=column.auto_increment,
        server_default=(
            "CurrentTimestamp" if column.server_default is CurrentTimestamp else None
        ),
        collation=_column_collation(column),
        datetime_precision=3 if column.storage_type_name == "DateTime" else None,
        unsigned=_column_unsigned(column),
    )


def _expected_index_shape(index: NormalizedIndex) -> IndexShape:
    return IndexShape(
        column_names=index.column_names,
        name=index.name,
        prefix_lengths=tuple(None for _ in index.column_names),
        index_type="BTREE",
        unique=index.unique,
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


def _normalize_foreign_key_action(action: str | None) -> str:
    """Normalize MariaDB's equivalent `NO ACTION` and `RESTRICT` spellings."""

    if action is None or action in {"NO ACTION", "RESTRICT"}:
        return "NO ACTION"
    return action


_SCHEMA_DIALECT = SchemaDialect(
    quote_identifier=quote_identifier,
    compile_column_definition=_compile_column_definition,
    expected_column_shape=_expected_column_shape,
    expected_index_shape=_expected_index_shape,
    normalize_foreign_key_action=_normalize_foreign_key_action,
    table_suffix="ENGINE=InnoDB",
    verifies_foreign_keys=True,
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


def _table_name_placeholders(table_names: tuple[str, ...]) -> str:
    """Build one parameter placeholder per validated planned table name."""

    return ", ".join("%s" for _ in table_names)


async def _fetch_table_storage_options(
    connection: object,
    table_names: tuple[str, ...],
) -> dict[str, tuple[str, ...]]:
    tables_sql = (
        "SELECT TABLE_NAME, ENGINE FROM INFORMATION_SCHEMA.TABLES "  # noqa: S608
        "WHERE TABLE_SCHEMA = DATABASE() "
        f"AND TABLE_NAME IN ({_table_name_placeholders(table_names)})"
    )
    rows = await _fetchall(connection, tables_sql, tuple(table_names))
    return {
        str(table_name): ("ENGINE=InnoDB",) if str(engine).lower() == "innodb" else ()
        for table_name, engine in rows
    }


async def _fetch_existing_column_shapes(
    connection: object,
    table_names: tuple[str, ...],
) -> dict[str, tuple[ColumnShape, ...]]:
    columns_sql = (
        "SELECT TABLE_NAME, COLUMN_NAME, DATA_TYPE, COLUMN_TYPE, "  # noqa: S608
        "CHARACTER_MAXIMUM_LENGTH, NUMERIC_PRECISION, NUMERIC_SCALE, "
        "DATETIME_PRECISION, IS_NULLABLE, COLUMN_KEY, EXTRA, COLLATION_NAME, "
        "COLUMN_DEFAULT FROM INFORMATION_SCHEMA.COLUMNS "
        "WHERE TABLE_SCHEMA = DATABASE() "
        f"AND TABLE_NAME IN ({_table_name_placeholders(table_names)}) "
        "ORDER BY TABLE_NAME, ORDINAL_POSITION"
    )
    rows = await _fetchall(connection, columns_sql, tuple(table_names))
    shapes: dict[str, list[ColumnShape]] = {}
    for row in rows:
        (
            table_name,
            name,
            data_type,
            column_type,
            max_length,
            numeric_precision,
            numeric_scale,
            datetime_precision,
            nullable,
            column_key,
            extra,
            collation,
            default,
        ) = row
        parsed_max_length = (
            int(max_length) if isinstance(max_length, int | str) else None
        )
        parsed_numeric_precision = (
            int(numeric_precision) if isinstance(numeric_precision, int | str) else None
        )
        parsed_numeric_scale = (
            int(numeric_scale) if isinstance(numeric_scale, int | str) else None
        )
        shapes.setdefault(str(table_name), []).append(
            ColumnShape(
                name=str(name),
                storage_type=_format_storage_type(
                    str(data_type),
                    parsed_max_length,
                    parsed_numeric_precision,
                    parsed_numeric_scale,
                ),
                nullable=nullable == "YES",
                primary_key=column_key == "PRI",
                auto_increment="auto_increment" in str(extra),
                server_default=(
                    "CurrentTimestamp"
                    if str(default).lower() == "current_timestamp(3)"
                    else str(default)
                    if default is not None
                    else None
                ),
                collation=(
                    str(collation)
                    if str(data_type) == "varchar" and collation
                    else None
                ),
                datetime_precision=(
                    int(datetime_precision)
                    if isinstance(datetime_precision, int | str)
                    else None
                ),
                unsigned=(
                    str(column_type).lower().endswith(" unsigned")
                    if str(data_type) in {"bigint", "decimal", "double", "tinyint"}
                    else None
                ),
            )
        )
    return {table_name: tuple(columns) for table_name, columns in shapes.items()}


async def _fetch_existing_index_shapes(
    connection: object,
    table_names: tuple[str, ...],
) -> dict[str, tuple[IndexShape, ...]]:
    indexes_sql = (
        "SELECT TABLE_NAME, INDEX_NAME, NON_UNIQUE, SEQ_IN_INDEX, COLUMN_NAME, "  # noqa: S608
        "SUB_PART, INDEX_TYPE FROM INFORMATION_SCHEMA.STATISTICS "
        "WHERE TABLE_SCHEMA = DATABASE() "
        f"AND TABLE_NAME IN ({_table_name_placeholders(table_names)}) "
        "AND INDEX_NAME <> 'PRIMARY' "
        "ORDER BY TABLE_NAME, INDEX_NAME, SEQ_IN_INDEX"
    )
    rows = await _fetchall(connection, indexes_sql, tuple(table_names))
    grouped_columns: dict[tuple[str, str], list[str]] = {}
    grouped_prefixes: dict[tuple[str, str], list[int | None]] = {}
    index_types: dict[tuple[str, str], str] = {}
    uniqueness: dict[tuple[str, str], bool] = {}
    for (
        table_name,
        name,
        non_unique,
        _sequence,
        column_name,
        prefix_length,
        index_type,
    ) in rows:
        index_key = (str(table_name), str(name))
        grouped_columns.setdefault(index_key, []).append(str(column_name))
        grouped_prefixes.setdefault(index_key, []).append(
            int(prefix_length) if isinstance(prefix_length, int | str) else None
        )
        index_types[index_key] = str(index_type).upper()
        uniqueness[index_key] = non_unique == 0
    shapes: dict[str, list[IndexShape]] = {}
    for index_key, column_names in grouped_columns.items():
        table_name, index_name = index_key
        shapes.setdefault(table_name, []).append(
            IndexShape(
                name=index_name,
                column_names=tuple(column_names),
                prefix_lengths=tuple(grouped_prefixes[index_key]),
                index_type=index_types[index_key],
                unique=uniqueness[index_key],
            )
        )
    return {table_name: tuple(indexes) for table_name, indexes in shapes.items()}


async def _fetch_existing_foreign_key_shapes(
    connection: object,
    table_names: tuple[str, ...],
) -> dict[str, tuple[ForeignKeyShape, ...]]:
    foreign_keys_sql = (
        "SELECT key_usage.TABLE_NAME, key_usage.COLUMN_NAME, "  # noqa: S608
        "key_usage.REFERENCED_TABLE_NAME, key_usage.REFERENCED_COLUMN_NAME, "
        "referential.UPDATE_RULE, referential.DELETE_RULE "
        "FROM INFORMATION_SCHEMA.KEY_COLUMN_USAGE AS key_usage "
        "JOIN INFORMATION_SCHEMA.REFERENTIAL_CONSTRAINTS AS referential "
        "ON referential.CONSTRAINT_SCHEMA = key_usage.CONSTRAINT_SCHEMA "
        "AND referential.TABLE_NAME = key_usage.TABLE_NAME "
        "AND referential.CONSTRAINT_NAME = key_usage.CONSTRAINT_NAME "
        "WHERE key_usage.TABLE_SCHEMA = DATABASE() "
        f"AND key_usage.TABLE_NAME IN ({_table_name_placeholders(table_names)}) "
        "AND key_usage.REFERENCED_TABLE_NAME IS NOT NULL "
        "ORDER BY key_usage.TABLE_NAME, key_usage.CONSTRAINT_NAME, "
        "key_usage.ORDINAL_POSITION"
    )
    rows = await _fetchall(connection, foreign_keys_sql, tuple(table_names))
    shapes: dict[str, list[ForeignKeyShape]] = {}
    for (
        table_name,
        column_name,
        target_table,
        target_column,
        on_update,
        on_delete,
    ) in rows:
        shapes.setdefault(str(table_name), []).append(
            ForeignKeyShape(
                column_name=str(column_name),
                target_table=str(target_table),
                target_column=str(target_column),
                on_update=_normalize_foreign_key_action(str(on_update)),
                on_delete=_normalize_foreign_key_action(str(on_delete)),
            )
        )
    return {
        table_name: tuple(foreign_keys) for table_name, foreign_keys in shapes.items()
    }


def _exclude_implicit_foreign_key_indexes(
    indexes: tuple[IndexShape, ...],
    foreign_keys: tuple[ForeignKeyShape, ...],
    planned_model: PlannedModel,
) -> tuple[IndexShape, ...]:
    """Ignore otherwise-unmanaged indexes MariaDB requires to enforce FKs."""

    expected_names = {index.name for index in planned_model.indexes}
    foreign_key_columns = {foreign_key.column_name for foreign_key in foreign_keys}
    return tuple(
        index
        for index in indexes
        if index.name in expected_names
        or not index.column_names
        or index.column_names[0] not in foreign_key_columns
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

    async def inspect_shapes(
        self,
        planned_models: Sequence[PlannedModel],
    ) -> dict[str, TableShape]:
        table_names = tuple(model.table_name for model in planned_models)
        storage_options_by_table = await _fetch_table_storage_options(
            self.connection, table_names
        )
        columns_by_table = await _fetch_existing_column_shapes(
            self.connection, table_names
        )
        indexes_by_table = await _fetch_existing_index_shapes(
            self.connection, table_names
        )
        foreign_keys_by_table = await _fetch_existing_foreign_key_shapes(
            self.connection, table_names
        )
        shapes: dict[str, TableShape] = {}
        for planned_model in planned_models:
            table_name = planned_model.table_name
            storage_options = storage_options_by_table.get(table_name)
            if storage_options is None:
                continue
            foreign_keys = foreign_keys_by_table.get(table_name, ())
            shapes[table_name] = TableShape(
                table_name=table_name,
                columns=columns_by_table.get(table_name, ()),
                indexes=_exclude_implicit_foreign_key_indexes(
                    indexes_by_table.get(table_name, ()),
                    foreign_keys,
                    planned_model,
                ),
                foreign_keys=foreign_keys,
                storage_options=storage_options,
            )
        return shapes


async def verify_mariadb_schema(
    connection: object,
    models: Sequence[type[Table[Any]]],
    schema_policy: SchemaPolicy,
) -> SchemaVerificationResult:
    """Verify all configured MariaDB tables against the live schema."""

    return await verify_schema(
        MariaDBSchemaBackend(connection),
        models,
        schema_policy,
    )


def scaffold_mariadb_ddl(models: Sequence[type[Model[Any, Any]]]) -> str:
    """Emit the initial CREATE TABLE (and index) DDL for MariaDB models as text."""

    require_scaffold_models("mariadb", models)
    return scaffold_ddl(models, _SCHEMA_DIALECT)


def scaffold_mariadb_statements(
    models: Sequence[type[Model[Any, Any]]],
) -> list[tuple[str, str]]:
    """Return (label, DDL) statement pairs for MariaDB model creation."""

    require_scaffold_models("mariadb", models)
    return scaffold_statements(models, _SCHEMA_DIALECT)

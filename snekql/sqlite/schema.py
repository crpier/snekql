"""SQLite schema backend: DDL compilation and sqlite_master inspection."""

from __future__ import annotations

import contextlib
from collections.abc import AsyncGenerator, Sequence
from typing import Any

from aiosqlite import Connection, Error

from snekql._schema_compile import (
    compile_create_index_sql,
    compile_create_table_sql,
    expected_table_shape,
)
from snekql._schema_dialect import SchemaDialect
from snekql._schema_plan import PlannedColumn, PlannedModel
from snekql._schema_shape import ColumnShape, ForeignKeyShape, IndexShape, TableShape
from snekql._schema_startup import initialize_schema
from snekql.errors import SchemaError
from snekql.indexes import NormalizedIndex
from snekql.model import Table
from snekql.sqlite.identifiers import quote_identifier
from snekql.storage import Attr, CurrentTimestamp, SchemaPolicy


def _requires_not_null(column: Attr[Any, Any, Any, Any, Any]) -> bool:
    # SQLite records no NOT NULL constraint for a primary-key column (the rowid
    # alias cannot be null on its own), so the column DDL and the expected shape
    # share this one predicate to stay in lockstep.
    return column.nullable is False and not column.primary_key


def _compile_column_definition(planned_column: PlannedColumn) -> str:
    column = planned_column.column
    parts = [quote_identifier(planned_column.name), column.sqlite_storage_class]
    if column.primary_key:
        parts.append("PRIMARY KEY")
    if column.auto_increment:
        parts.append("AUTOINCREMENT")
    if _requires_not_null(column):
        parts.append("NOT NULL")
    if isinstance(column.server_default, CurrentTimestamp):
        parts.append("DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))")
    return " ".join(parts)


def _expected_column_shape(planned_column: PlannedColumn) -> ColumnShape:
    column = planned_column.column
    return ColumnShape(
        name=planned_column.name,
        storage_type=column.sqlite_storage_class,
        nullable=not _requires_not_null(column),
        primary_key=column.primary_key,
        auto_increment=column.auto_increment,
        has_server_default=isinstance(column.server_default, CurrentTimestamp),
        collation=None,
    )


_SCHEMA_DIALECT = SchemaDialect(
    quote_identifier=quote_identifier,
    compile_column_definition=_compile_column_definition,
    expected_column_shape=_expected_column_shape,
    table_suffix="STRICT",
    verifies_foreign_keys=True,
)


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


async def _fetch_rows(
    connection: Connection,
    sql: str,
    params: tuple[object, ...] = (),
) -> list[tuple[Any, ...]]:
    cursor = await connection.execute(sql, params)
    try:
        rows = await cursor.fetchall()
    finally:
        await cursor.close()
    return [tuple(row) for row in rows]


async def _fetch_table_storage_options(
    connection: Connection,
    table_name: str,
) -> tuple[str, ...] | None:
    """Return a live table's storage-option tokens, or None if it is absent."""

    rows = await _fetch_rows(connection, "PRAGMA table_list")
    for row in rows:
        # PRAGMA table_list columns: schema, name, type, ncol, wr, strict.
        if str(row[1]) == table_name and str(row[2]) == "table":
            return ("STRICT",) if bool(row[5]) else ()
    return None


async def _table_uses_autoincrement(
    connection: Connection,
    table_name: str,
) -> bool:
    """Whether the table's primary key was declared AUTOINCREMENT.

    PRAGMA metadata does not expose AUTOINCREMENT, so the stored DDL keyword is
    the authoritative signal; it is only ever valid on the INTEGER PRIMARY KEY.
    """

    rows = await _fetch_rows(
        connection,
        "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = ?",
        (table_name,),
    )
    if not rows:
        return False
    return "AUTOINCREMENT" in str(rows[0][0]).upper()


async def _fetch_column_shapes(
    connection: Connection,
    table_name: str,
    *,
    has_autoincrement: bool,
) -> tuple[ColumnShape, ...]:
    rows = await _fetch_rows(
        connection,
        f"PRAGMA table_info({quote_identifier(table_name)})",
    )
    shapes: list[ColumnShape] = []
    for row in rows:
        # PRAGMA table_info columns: cid, name, type, notnull, dflt_value, pk.
        _cid, name, data_type, notnull, default, pk = row
        is_primary_key = int(pk) != 0
        shapes.append(
            ColumnShape(
                name=str(name),
                storage_type=str(data_type).upper(),
                nullable=int(notnull) == 0,
                primary_key=is_primary_key,
                auto_increment=is_primary_key and has_autoincrement,
                has_server_default=default is not None,
                collation=None,
            )
        )
    return tuple(shapes)


async def _fetch_index_shapes(
    connection: Connection,
    table_name: str,
) -> tuple[IndexShape, ...]:
    list_rows = await _fetch_rows(
        connection,
        f"PRAGMA index_list({quote_identifier(table_name)})",
    )
    shapes: list[IndexShape] = []
    for row in list_rows:
        # PRAGMA index_list columns: seq, name, unique, origin, partial.
        index_name, unique, origin = str(row[1]), int(row[2]), str(row[3])
        # origin 'c' marks an explicit CREATE INDEX; 'u'/'pk' indexes are
        # implicit constraint artifacts snekql does not manage by name.
        if origin != "c":
            continue
        info_rows = await _fetch_rows(
            connection,
            f"PRAGMA index_info({quote_identifier(index_name)})",
        )
        column_names = tuple(str(info_row[2]) for info_row in info_rows)
        shapes.append(
            IndexShape(
                name=index_name,
                column_names=column_names,
                unique=unique == 1,
            )
        )
    return tuple(shapes)


async def _fetch_foreign_key_shapes(
    connection: Connection,
    table_name: str,
) -> tuple[ForeignKeyShape, ...]:
    rows = await _fetch_rows(
        connection,
        f"PRAGMA foreign_key_list({quote_identifier(table_name)})",
    )
    return tuple(
        # PRAGMA foreign_key_list columns: id, seq, table, from, to, ...
        ForeignKeyShape(
            column_name=str(row[3]),
            target_table=str(row[2]),
            target_column=str(row[4]),
        )
        for row in rows
    )


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

    def expected_shape(self, planned_model: PlannedModel) -> TableShape:
        return expected_table_shape(planned_model, _SCHEMA_DIALECT)

    async def inspect_shape(self, planned_model: PlannedModel) -> TableShape | None:
        table_name = planned_model.table_name
        storage_options = await _fetch_table_storage_options(
            self.connection,
            table_name,
        )
        if storage_options is None:
            return None
        has_autoincrement = await _table_uses_autoincrement(
            self.connection,
            table_name,
        )
        return TableShape(
            table_name=table_name,
            columns=await _fetch_column_shapes(
                self.connection,
                table_name,
                has_autoincrement=has_autoincrement,
            ),
            indexes=await _fetch_index_shapes(self.connection, table_name),
            foreign_keys=await _fetch_foreign_key_shapes(self.connection, table_name),
            storage_options=storage_options,
        )

    async def create_table(self, planned_model: PlannedModel) -> None:
        await _execute_schema_sql(
            self.connection,
            compile_create_table_sql(planned_model, _SCHEMA_DIALECT),
        )

    async def create_index(self, table_name: str, index: NormalizedIndex) -> str:
        sql = compile_create_index_sql(table_name, index, _SCHEMA_DIALECT)
        await _execute_schema_sql(self.connection, sql)
        return sql


async def initialize_sqlite_schema(
    connection: Connection,
    models: Sequence[type[Table[Any]]],
    schema_policy: SchemaPolicy,
    *,
    create_missing: bool = True,
) -> None:
    """Create or verify all configured SQLite tables transactionally."""

    await initialize_schema(
        SQLiteSchemaBackend(connection),
        models,
        schema_policy,
        create_missing=create_missing,
    )

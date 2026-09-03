"""SQLite schema backend: DDL compilation and sqlite_master inspection."""

from __future__ import annotations

import contextlib
from collections.abc import AsyncGenerator, Sequence
from dataclasses import dataclass
from re import fullmatch
from typing import Any, Literal

import anyio
from aiosqlite import Connection, Error

from snekql._schema_compile import (
    expected_table_shape,
)
from snekql._schema_plan import PlannedModel
from snekql._schema_shape import ColumnShape, ForeignKeyShape, IndexShape, TableShape
from snekql._schema_startup import verify_schema
from snekql._schema_verification import SchemaVerificationResult
from snekql.errors import SchemaError
from snekql.model import Table
from snekql.sqlite._schema_ddl import SCHEMA_DIALECT, sqlite_type_affinity
from snekql.sqlite.identifiers import quote_identifier
from snekql.storage import SchemaPolicy


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
    table_names: tuple[str, ...],
) -> dict[str, tuple[str, ...]]:
    """Read table existence and storage options with one whole-catalog query."""

    requested_names = set(table_names)
    rows = await _fetch_rows(connection, "PRAGMA table_list")
    return {
        str(row[1]): ("STRICT",) if bool(row[5]) else ()
        for row in rows
        # PRAGMA table_list columns: schema, name, type, ncol, wr, strict.
        if str(row[0]) == "main"
        and str(row[1]) in requested_names
        and str(row[2]) == "table"
    }


@dataclass(frozen=True, slots=True)
class _SQLiteToken:
    """One relevant token from SQLite's stored table DDL."""

    kind: Literal["identifier", "literal", "symbol", "word"]
    text: str


def _sqlite_tokens(sql: str) -> tuple[_SQLiteToken, ...]:  # noqa: C901
    """Tokenize stored SQLite DDL without confusing quoted text for keywords."""

    tokens: list[_SQLiteToken] = []
    position = 0
    while position < len(sql):
        character = sql[position]
        following = sql[position + 1] if position + 1 < len(sql) else ""
        if character == "-" and following == "-":
            newline = sql.find("\n", position + 2)
            position = len(sql) if newline == -1 else newline + 1
            continue
        if character == "/" and following == "*":
            closing = sql.find("*/", position + 2)
            position = len(sql) if closing == -1 else closing + 2
            continue
        if character in {"'", '"', "`"}:
            quote = character
            kind: Literal["identifier", "literal"] = (
                "literal" if quote == "'" else "identifier"
            )
            value: list[str] = []
            position += 1
            while position < len(sql):
                if sql[position] != quote:
                    value.append(sql[position])
                    position += 1
                    continue
                if position + 1 < len(sql) and sql[position + 1] == quote:
                    value.append(quote)
                    position += 2
                    continue
                position += 1
                break
            tokens.append(_SQLiteToken(kind=kind, text="".join(value)))
            continue
        if character == "[":
            closing = sql.find("]", position + 1)
            end = len(sql) if closing == -1 else closing
            tokens.append(_SQLiteToken(kind="identifier", text=sql[position + 1 : end]))
            position = len(sql) if closing == -1 else closing + 1
            continue
        if character.isalpha() or character == "_":
            end = position + 1
            while end < len(sql) and (sql[end].isalnum() or sql[end] in {"_", "$"}):
                end += 1
            tokens.append(_SQLiteToken(kind="word", text=sql[position:end]))
            position = end
            continue
        if character in {"(", ")", ","}:
            tokens.append(_SQLiteToken(kind="symbol", text=character))
        position += 1
    return tuple(tokens)


def _sqlite_column_definitions(table_sql: str) -> tuple[tuple[_SQLiteToken, ...], ...]:
    """Split the outer CREATE TABLE body without splitting nested expressions."""

    tokens = _sqlite_tokens(table_sql)
    opening = next(
        (
            position
            for position, token in enumerate(tokens)
            if token.kind == "symbol" and token.text == "("
        ),
        None,
    )
    if opening is None:
        return ()
    definitions: list[tuple[_SQLiteToken, ...]] = []
    current: list[_SQLiteToken] = []
    depth = 0
    for token in tokens[opening + 1 :]:
        if token.kind == "symbol" and token.text == "(":
            depth += 1
        elif token.kind == "symbol" and token.text == ")":
            if depth == 0:
                if current:
                    definitions.append(tuple(current))
                break
            depth -= 1
        elif token.kind == "symbol" and token.text == "," and depth == 0:
            definitions.append(tuple(current))
            current = []
            continue
        current.append(token)
    return tuple(definitions)


def _sqlite_definition_collation(
    definition: tuple[_SQLiteToken, ...],
) -> tuple[str, str] | None:
    """Extract one column name and its effective top-level collation."""

    if not definition:
        return None
    name_token = definition[0]
    table_constraint_starts = {"CHECK", "CONSTRAINT", "FOREIGN", "PRIMARY", "UNIQUE"}
    if (
        name_token.kind == "word" and name_token.text.upper() in table_constraint_starts
    ) or name_token.kind not in {"identifier", "word"}:
        return None
    depth = 0
    for position, token in enumerate(definition[1:], start=1):
        if token.kind == "symbol" and token.text == "(":
            depth += 1
            continue
        if token.kind == "symbol" and token.text == ")":
            depth -= 1
            continue
        if depth != 0 or token.kind != "word" or token.text.upper() != "COLLATE":
            continue
        if position + 1 < len(definition):
            collation_token = definition[position + 1]
            if collation_token.kind in {"identifier", "word"}:
                return name_token.text.casefold(), collation_token.text.upper()
        break
    return name_token.text.casefold(), "BINARY"


def _sqlite_column_collations(table_sql: str | None) -> dict[str, str]:
    """Read top-level column COLLATE clauses, defaulting columns to BINARY."""

    if table_sql is None:
        return {}
    collations: dict[str, str] = {}
    for definition in _sqlite_column_definitions(table_sql):
        column_collation = _sqlite_definition_collation(definition)
        if column_collation is not None:
            column_name, collation = column_collation
            collations[column_name] = collation
    return collations


def _sqlite_top_level_words(
    definition: tuple[_SQLiteToken, ...],
) -> tuple[str, ...]:
    """Return unquoted words outside nested expressions in one table definition."""

    words: list[str] = []
    depth = 0
    for token in definition:
        if token.kind == "symbol" and token.text == "(":
            depth += 1
        elif token.kind == "symbol" and token.text == ")":
            depth -= 1
        elif depth == 0 and token.kind == "word":
            words.append(token.text.upper())
    return tuple(words)


async def _fetch_table_sql(
    connection: Connection,
    table_names: tuple[str, ...],
) -> dict[str, str]:
    placeholders = ", ".join("?" for _ in table_names)
    table_sql = (
        "SELECT name, sql FROM sqlite_master "  # noqa: S608
        f"WHERE type = 'table' AND name IN ({placeholders})"
    )
    rows = await _fetch_rows(connection, table_sql, tuple(table_names))
    return {str(name): str(sql) for name, sql in rows if sql is not None}


def _table_uses_autoincrement(table_sql: str | None) -> bool:
    """Detect the exact unquoted keyword from SQLite's stored table DDL."""

    if table_sql is None:
        return False
    for definition in _sqlite_column_definitions(table_sql):
        words = _sqlite_top_level_words(definition)
        try:
            primary_position = words.index("PRIMARY")
            key_position = words.index("KEY", primary_position + 1)
            _ = words.index("AUTOINCREMENT", key_position + 1)
        except ValueError:
            continue
        return True
    return False


def _normalize_server_default(default: object | None) -> str | None:
    """Recognize the supported server clock expression despite SQL spacing."""

    if default is None:
        return None
    expression = str(default)
    if fullmatch(
        r"(?i:strftime)\s*\(\s*'%Y-%m-%dT%H:%M:%fZ'\s*,\s*'(?i:now)'\s*\)",
        expression,
    ):
        return "CurrentTimestamp"
    return expression


async def _fetch_column_shapes(
    connection: Connection,
    table_name: str,
    *,
    collations: dict[str, str],
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
                # Compare by SQLite affinity class, not declared spelling, so
                # benign type aliases (INT vs INTEGER, VARCHAR vs TEXT) are not
                # drift while genuine affinity changes still are.
                storage_type=sqlite_type_affinity(str(data_type)),
                nullable=int(notnull) == 0,
                primary_key=is_primary_key,
                auto_increment=is_primary_key and has_autoincrement,
                server_default=_normalize_server_default(default),
                collation=collations.get(str(name).casefold(), "BINARY"),
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
        index_name, unique, origin, partial = (
            str(row[1]),
            int(row[2]),
            str(row[3]),
            int(row[4]),
        )
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
                partial=partial == 1,
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
        # PRAGMA foreign_key_list columns:
        # id, seq, table, from, to, on_update, on_delete, match.
        ForeignKeyShape(
            column_name=str(row[3]),
            target_table=str(row[2]),
            target_column=str(row[4]),
            on_update=str(row[5]),
            on_delete=str(row[6]),
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
    async def verification_transaction(self) -> AsyncGenerator[None]:
        """Always roll back read-only inspection, including during cancellation."""

        await _execute_schema_sql(self.connection, "BEGIN")
        try:
            yield
        except Error as error:
            with anyio.CancelScope(shield=True):
                await _rollback_schema_setup(self.connection)
            msg = "SQLite schema verification failed"
            raise SchemaError(msg) from error
        except BaseException:
            with anyio.CancelScope(shield=True):
                await _rollback_schema_setup(self.connection)
            raise
        else:
            try:
                with anyio.CancelScope(shield=True):
                    await _execute_schema_sql(self.connection, "ROLLBACK")
            except Error as error:
                msg = "SQLite schema verification failed"
                raise SchemaError(msg) from error

    def expected_shape(self, planned_model: PlannedModel) -> TableShape:
        return expected_table_shape(planned_model, SCHEMA_DIALECT)

    async def inspect_shapes(
        self,
        planned_models: Sequence[PlannedModel],
    ) -> dict[str, TableShape]:
        shapes: dict[str, TableShape] = {}
        table_names = tuple(model.table_name for model in planned_models)
        storage_options_by_table = await _fetch_table_storage_options(
            self.connection,
            table_names,
        )
        table_sql_by_name = await _fetch_table_sql(self.connection, table_names)
        for planned_model in planned_models:
            table_name = planned_model.table_name
            storage_options = storage_options_by_table.get(table_name)
            if storage_options is None:
                continue
            table_sql = table_sql_by_name.get(table_name)
            has_autoincrement = _table_uses_autoincrement(table_sql)
            shapes[table_name] = TableShape(
                table_name=table_name,
                columns=await _fetch_column_shapes(
                    self.connection,
                    table_name,
                    collations=_sqlite_column_collations(table_sql),
                    has_autoincrement=has_autoincrement,
                ),
                indexes=await _fetch_index_shapes(self.connection, table_name),
                foreign_keys=await _fetch_foreign_key_shapes(
                    self.connection, table_name
                ),
                storage_options=storage_options,
            )
        return shapes


async def verify_sqlite_schema(
    connection: Connection,
    models: Sequence[type[Table[Any]]],
    schema_policy: SchemaPolicy,
) -> SchemaVerificationResult:
    """Verify all configured SQLite tables against the live schema."""

    return await verify_schema(
        SQLiteSchemaBackend(connection),
        models,
        schema_policy,
    )

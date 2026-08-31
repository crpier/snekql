"""SQLite Migration History v2 and per-migration transaction execution."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from sqlite3 import (
    SQLITE_ALTER_TABLE,
    SQLITE_ATTACH,
    SQLITE_CREATE_INDEX,
    SQLITE_CREATE_TABLE,
    SQLITE_CREATE_TEMP_INDEX,
    SQLITE_CREATE_TEMP_TABLE,
    SQLITE_CREATE_TEMP_TRIGGER,
    SQLITE_CREATE_TEMP_VIEW,
    SQLITE_CREATE_TRIGGER,
    SQLITE_CREATE_VIEW,
    SQLITE_CREATE_VTABLE,
    SQLITE_DELETE,
    SQLITE_DENY,
    SQLITE_DETACH,
    SQLITE_DROP_INDEX,
    SQLITE_DROP_TABLE,
    SQLITE_DROP_TEMP_INDEX,
    SQLITE_DROP_TEMP_TABLE,
    SQLITE_DROP_TEMP_TRIGGER,
    SQLITE_DROP_TEMP_VIEW,
    SQLITE_DROP_TRIGGER,
    SQLITE_DROP_VIEW,
    SQLITE_DROP_VTABLE,
    SQLITE_INSERT,
    SQLITE_OK,
    SQLITE_READ,
    SQLITE_SAVEPOINT,
    SQLITE_TRANSACTION,
    SQLITE_UPDATE,
    complete_statement,
)
from typing import Literal

import anyio
from aiosqlite import Connection
from anyio.lowlevel import checkpoint

from snekql._migrations import (
    Migration,
    MigrationPlan,
    MigrationRecord,
    MigrationResult,
    validate_history_prefix,
    validate_legacy_history,
)
from snekql.errors import (
    MigrationDeclarationError,
    MigrationError,
    MigrationHistoryError,
    MigrationLockTimeoutError,
)
from snekql.sqlite._dialect_sql import CURRENT_TIMESTAMP_SQL
from snekql.sqlite.identifiers import quote_identifier
from snekql.sqlite.retry import (
    DEFAULT_BUSY_RETRY_POLICY,
    BusyRetryPolicy,
    is_sqlite_busy_error,
    retry_on_sqlite_busy,
)

logger = logging.getLogger(__name__)

_HISTORY_TABLE = "snekql_migrations"

_CREATE_HISTORY_SQL = (
    f"CREATE TABLE IF NOT EXISTS {quote_identifier(_HISTORY_TABLE)} ("
    '"position" INTEGER NOT NULL PRIMARY KEY CHECK ("position" > 0), '
    '"name" TEXT COLLATE BINARY NOT NULL UNIQUE '
    'CHECK (length("name") BETWEEN 1 AND 255 AND instr("name", char(0)) = 0), '
    '"checksum" TEXT COLLATE BINARY NOT NULL '
    'CHECK (length("checksum") = 64 AND instr("checksum", char(0)) = 0 '
    "AND \"checksum\" NOT GLOB '*[^0-9a-f]*'), "
    '"applied_at" TEXT NOT NULL) STRICT'
)
"""DDL enforcing correctness-bearing Migration History v2 fields."""

_V1_HISTORY_SQL = (
    f"CREATE TABLE {quote_identifier(_HISTORY_TABLE)} "
    '("name" TEXT PRIMARY KEY NOT NULL, "applied_at" TEXT NOT NULL) STRICT'
)
_V2_HISTORY_SQL = _CREATE_HISTORY_SQL.replace(" IF NOT EXISTS", "", 1)

_SELECT_HISTORY_SQL = (
    f"SELECT position, name, checksum FROM {quote_identifier(_HISTORY_TABLE)} "  # noqa: S608
    "ORDER BY position"
)

_INSERT_HISTORY_SQL = (
    f"INSERT INTO {quote_identifier(_HISTORY_TABLE)} "  # noqa: S608
    f"(position, name, checksum, applied_at) "
    f"VALUES (?, ?, ?, {CURRENT_TIMESTAMP_SQL}) "
    "RETURNING position, name, checksum"
)

_HISTORY_OBJECT_SQL = (
    "SELECT type, name FROM sqlite_master WHERE name = ? COLLATE NOCASE"
)

_HISTORY_DEPENDENCIES_SQL = (
    "SELECT type, name FROM sqlite_master "
    "WHERE tbl_name = ? COLLATE NOCASE AND type = 'trigger'"
)

_SELECT_LEGACY_SQL = f"SELECT name, applied_at FROM {quote_identifier(_HISTORY_TABLE)}"  # noqa: S608

_INSERT_ADOPTED_SQL = (
    f"INSERT INTO {quote_identifier(_HISTORY_TABLE)} "  # noqa: S608
    "(position, name, checksum, applied_at) VALUES (?, ?, ?, ?)"
)

_LEGACY_HISTORY_TABLE = "_snekql_migrations_v1"

_V1_COLUMNS = (
    (0, "name", "TEXT", 1, None, 1),
    (1, "applied_at", "TEXT", 1, None, 0),
)
_V2_COLUMNS = (
    (0, "position", "INTEGER", 1, None, 1),
    (1, "name", "TEXT", 1, None, 0),
    (2, "checksum", "TEXT", 1, None, 0),
    (3, "applied_at", "TEXT", 1, None, 0),
)

type _HistoryShape = Literal["absent", "unknown", "v1", "v2"]


@dataclass(slots=True)
class SQLiteMigrationConnectionState:
    """Whether a migration connection can safely return to its pool."""

    reusable: bool = False
    authorizer_uncertain: bool = False


_RESTRICTED_FIRST_KEYWORDS = frozenset(
    {
        "ATTACH",
        "BEGIN",
        "COMMIT",
        "DETACH",
        "END",
        "PRAGMA",
        "RELEASE",
        "ROLLBACK",
        "SAVEPOINT",
        "VACUUM",
    }
)

_TEMP_ACTIONS = frozenset(
    {
        SQLITE_CREATE_TEMP_INDEX,
        SQLITE_CREATE_TEMP_TABLE,
        SQLITE_CREATE_TEMP_TRIGGER,
        SQLITE_CREATE_TEMP_VIEW,
        SQLITE_DROP_TEMP_INDEX,
        SQLITE_DROP_TEMP_TABLE,
        SQLITE_DROP_TEMP_TRIGGER,
        SQLITE_DROP_TEMP_VIEW,
    }
)

_CONNECTION_ACTIONS = frozenset(
    {
        SQLITE_ATTACH,
        SQLITE_DETACH,
        SQLITE_SAVEPOINT,
        SQLITE_TRANSACTION,
    }
)

_MUTATION_ACTIONS = frozenset({SQLITE_DELETE, SQLITE_INSERT, SQLITE_UPDATE})

_HISTORY_FIRST_ARGUMENT_ACTIONS = frozenset(
    {
        SQLITE_CREATE_TABLE,
        SQLITE_CREATE_VIEW,
        SQLITE_CREATE_VTABLE,
        SQLITE_DELETE,
        SQLITE_DROP_TABLE,
        SQLITE_DROP_VIEW,
        SQLITE_DROP_VTABLE,
        SQLITE_INSERT,
        SQLITE_READ,
        SQLITE_UPDATE,
    }
)

_HISTORY_SECOND_ARGUMENT_ACTIONS = frozenset(
    {
        SQLITE_ALTER_TABLE,
        SQLITE_CREATE_INDEX,
        SQLITE_CREATE_TRIGGER,
        SQLITE_DROP_INDEX,
        SQLITE_DROP_TRIGGER,
    }
)


def _sql_tokens(sql: str) -> tuple[str, ...]:  # noqa: C901
    """Extract unquoted tokens while ignoring whitespace and SQL comments."""

    tokens: list[str] = []
    index = 0
    while index < len(sql):
        character = sql[index]
        if character.isspace():
            index += 1
            continue
        if sql.startswith("--", index):
            newline = sql.find("\n", index + 2)
            index = len(sql) if newline == -1 else newline + 1
            continue
        if sql.startswith("/*", index):
            comment_end = sql.find("*/", index + 2)
            index = len(sql) if comment_end == -1 else comment_end + 2
            continue
        if character in {"'", '"', "`", "["}:
            closing = "]" if character == "[" else character
            quoted_start = index + 1
            index += 1
            while index < len(sql):
                if sql[index] != closing:
                    index += 1
                    continue
                if (
                    closing != "]"
                    and index + 1 < len(sql)
                    and sql[index + 1] == closing
                ):
                    index += 2
                    continue
                index += 1
                break
            tokens.append(sql[quoted_start : index - 1].upper())
            continue
        if character.isalpha() or character == "_":
            token_end = index + 1
            while token_end < len(sql) and (
                sql[token_end].isalnum() or sql[token_end] == "_"
            ):
                token_end += 1
            tokens.append(sql[index:token_end].upper())
            index = token_end
            continue
        if character in {"(", ")", ",", ".", ";"}:
            tokens.append(character)
        index += 1
    return tuple(tokens)


def _operation_index(tokens: tuple[str, ...]) -> int:
    """Locate the operation beneath optional EXPLAIN and CTE prefixes."""

    index = 0
    if tokens[0] == "EXPLAIN" and len(tokens) > 1:
        index = 3 if tokens[1:3] == ("QUERY", "PLAN") else 1
    if index >= len(tokens) or tokens[index] != "WITH":
        return min(index, len(tokens) - 1)

    depth = 0
    completed_cte = False
    for candidate in range(index + 1, len(tokens)):
        if tokens[candidate] == "(":
            depth += 1
        elif tokens[candidate] == ")":
            depth -= 1
            completed_cte = completed_cte or depth == 0
        elif completed_cte and depth == 0 and tokens[candidate] == ",":
            completed_cte = False
        elif (
            completed_cte
            and depth == 0
            and tokens[candidate]
            in {
                "DELETE",
                "INSERT",
                "REPLACE",
                "SELECT",
                "UPDATE",
            }
        ):
            return candidate
    return index


def _operation_keyword(tokens: tuple[str, ...]) -> str:
    return tokens[_operation_index(tokens)]


def _name_index_after(
    tokens: tuple[str, ...],
    keyword: str,
    *,
    start: int = 0,
) -> int | None:
    try:
        index = tokens.index(keyword, start) + 1
    except ValueError:
        return None
    if tokens[index : index + 3] == ("IF", "NOT", "EXISTS"):
        index += 3
    elif tokens[index : index + 2] == ("IF", "EXISTS"):
        index += 2
    return index if index < len(tokens) else None


def _created_or_dropped_name_index(tokens: tuple[str, ...]) -> int | None:
    operation_index = _operation_index(tokens)
    for object_type in ("TABLE", "INDEX", "TRIGGER", "VIEW"):
        index = _name_index_after(tokens, object_type, start=operation_index)
        if index is not None:
            return index
    return None


def _object_name_index(tokens: tuple[str, ...]) -> int | None:
    """Locate the schema-qualifiable target name of common persistent statements."""

    operation_index = _operation_index(tokens)
    operation = tokens[operation_index]
    if operation in {"CREATE", "DROP"}:
        return _created_or_dropped_name_index(tokens)
    if operation == "UPDATE":
        name_index = operation_index + 1
        if tokens[name_index : name_index + 1] == ("OR",):
            name_index += 2
        return name_index if name_index < len(tokens) else None
    target_keyword = {
        "ALTER": "TABLE",
        "DELETE": "FROM",
        "INSERT": "INTO",
        "REPLACE": "INTO",
    }.get(operation)
    return (
        None
        if target_keyword is None
        else _name_index_after(tokens, target_keyword, start=operation_index)
    )


def _uses_temp_schema(tokens: tuple[str, ...]) -> bool:
    name_index = _object_name_index(tokens)
    return bool(
        name_index is not None and tokens[name_index : name_index + 2] == ("TEMP", ".")
    )


def _validate_sqlite_body(migration: Migration) -> None:
    """Require one persistent statement that cannot escape owned transaction state."""

    statement_end: int | None = None
    for index, character in enumerate(migration.sql):
        if character == ";" and complete_statement(migration.sql[: index + 1]):
            statement_end = index + 1
            break
    if statement_end is not None and _sql_tokens(migration.sql[statement_end:]):
        msg = f"SQLite migration {migration.name!r} must contain one statement"
        raise MigrationDeclarationError(msg)
    if statement_end is None and not complete_statement(f"{migration.sql}\n;"):
        msg = f"SQLite migration {migration.name!r} is not a complete statement"
        raise MigrationDeclarationError(msg)

    tokens = _sql_tokens(migration.sql)
    if not tokens:
        msg = f"SQLite migration {migration.name!r} must contain SQL"
        raise MigrationDeclarationError(msg)
    first_keyword = _operation_keyword(tokens)
    if first_keyword in _RESTRICTED_FIRST_KEYWORDS:
        msg = f"SQLite migration {migration.name!r} cannot execute {first_keyword}"
        raise MigrationDeclarationError(msg)
    if (
        len(tokens) > 1
        and tokens[0] == "CREATE"
        and tokens[1]
        in {
            "TEMP",
            "TEMPORARY",
        }
    ):
        msg = f"SQLite migration {migration.name!r} cannot create temporary objects"
        raise MigrationDeclarationError(msg)
    if _uses_temp_schema(tokens):
        msg = f"SQLite migration {migration.name!r} cannot use temporary objects"
        raise MigrationDeclarationError(msg)


def validate_sqlite_migrations(migrations: MigrationPlan) -> None:
    """Validate every SQLite body synchronously before connection acquisition."""

    for migration in migrations:
        _validate_sqlite_body(migration)


def _migration_authorizer(
    action: int,
    first_argument: str | None,
    second_argument: str | None,
    database_name: str | None,
    trigger_name: str | None,
) -> int:
    """Keep bodies inside persistent main schema and away from owned history."""

    _ = trigger_name
    if action in _CONNECTION_ACTIONS or action in _TEMP_ACTIONS:
        return SQLITE_DENY
    first_is_history = (
        first_argument is not None
        and first_argument.casefold() == _HISTORY_TABLE.casefold()
    )
    second_is_history = (
        second_argument is not None
        and second_argument.casefold() == _HISTORY_TABLE.casefold()
    )
    if (action in _HISTORY_FIRST_ARGUMENT_ACTIONS and first_is_history) or (
        action in _HISTORY_SECOND_ARGUMENT_ACTIONS and second_is_history
    ):
        return SQLITE_DENY
    if action in _MUTATION_ACTIONS and database_name not in {None, "main"}:
        return SQLITE_DENY
    return SQLITE_OK


async def _execute(
    connection: Connection, sql: str, params: tuple[object, ...] = ()
) -> None:
    cursor = await connection.execute(sql, params)
    await cursor.close()


async def _fetch_history(connection: Connection) -> tuple[MigrationRecord, ...]:
    cursor = await connection.execute(_SELECT_HISTORY_SQL, ())
    try:
        rows = await cursor.fetchall()
    finally:
        await cursor.close()
    return tuple(
        MigrationRecord(
            position=int(position),
            name=str(name),
            checksum=str(checksum),
        )
        for position, name, checksum in rows
    )


async def _fetch_history_object(
    connection: Connection,
) -> tuple[str, str] | None:
    cursor = await connection.execute(_HISTORY_OBJECT_SQL, (_HISTORY_TABLE,))
    try:
        rows = list(await cursor.fetchall())
    finally:
        await cursor.close()
    if not rows:
        return None
    if len(rows) != 1:
        return ("unknown", "unknown")
    return (str(rows[0][0]), str(rows[0][1]))


async def _fetch_history_shape(  # noqa: PLR0911
    connection: Connection,
) -> _HistoryShape:
    """Classify only the legacy and final history layouts snekql owns."""

    history_object = await _fetch_history_object(connection)
    if history_object is None:
        return "absent"
    if history_object != ("table", _HISTORY_TABLE):
        return "unknown"
    dependency_cursor = await connection.execute(
        _HISTORY_DEPENDENCIES_SQL, (_HISTORY_TABLE,)
    )
    try:
        dependencies = list(await dependency_cursor.fetchall())
    finally:
        await dependency_cursor.close()
    if dependencies:
        return "unknown"
    table_cursor = await connection.execute(
        f"PRAGMA table_list({quote_identifier(_HISTORY_TABLE)})"
    )
    try:
        table_rows = list(await table_cursor.fetchall())
    finally:
        await table_cursor.close()
    if len(table_rows) != 1 or tuple(table_rows[0][2:]) not in {
        ("table", 2, 0, 1),
        ("table", 4, 0, 1),
    }:
        return "unknown"
    sql_cursor = await connection.execute(
        "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = ?",
        (_HISTORY_TABLE,),
    )
    try:
        sql_row = await sql_cursor.fetchone()
    finally:
        await sql_cursor.close()
    stored_sql = None if sql_row is None else str(sql_row[0])

    column_cursor = await connection.execute(
        f"PRAGMA table_info({quote_identifier(_HISTORY_TABLE)})"
    )
    try:
        columns = tuple(tuple(row) for row in await column_cursor.fetchall())
    finally:
        await column_cursor.close()
    index_cursor = await connection.execute(
        f"PRAGMA index_list({quote_identifier(_HISTORY_TABLE)})"
    )
    try:
        indexes = list(await index_cursor.fetchall())
    finally:
        await index_cursor.close()
    if len(indexes) != 1 or int(indexes[0][2]) != 1 or int(indexes[0][4]) != 0:
        return "unknown"
    if (
        columns == _V1_COLUMNS
        and indexes[0][3] == "pk"
        and stored_sql == _V1_HISTORY_SQL
    ):
        return "v1"
    if (
        columns == _V2_COLUMNS
        and indexes[0][3] == "u"
        and stored_sql == _V2_HISTORY_SQL
    ):
        return "v2"
    return "unknown"


async def _fetch_legacy_history(connection: Connection) -> dict[str, str]:
    cursor = await connection.execute(_SELECT_LEGACY_SQL, ())
    try:
        rows = await cursor.fetchall()
    finally:
        await cursor.close()
    return {str(name): str(applied_at) for name, applied_at in rows}


async def _upgrade_legacy_history(
    connection: Connection,
    migrations: MigrationPlan,
    *,
    adopt_legacy: bool,
) -> bool:
    """Atomically rebuild exact v1 history after validating explicit consent."""

    legacy_history = await _fetch_legacy_history(connection)
    if legacy_history and not adopt_legacy:
        msg = (
            "non-empty legacy Migration History requires "
            "migrate(..., adopt_legacy=True)"
        )
        raise MigrationHistoryError(msg)
    prefix_length = validate_legacy_history(set(legacy_history), migrations)
    if await _table_named_exists(connection, _LEGACY_HISTORY_TABLE):
        msg = f"unexpected legacy staging object {_LEGACY_HISTORY_TABLE!r}"
        raise MigrationHistoryError(msg)
    await _execute(
        connection,
        f"ALTER TABLE {quote_identifier(_HISTORY_TABLE)} "
        f"RENAME TO {quote_identifier(_LEGACY_HISTORY_TABLE)}",
    )
    await _execute(connection, _CREATE_HISTORY_SQL)
    for migration in migrations[:prefix_length]:
        await _execute(
            connection,
            _INSERT_ADOPTED_SQL,
            (
                migration.position,
                migration.name,
                migration.checksum,
                legacy_history[migration.name],
            ),
        )
    await _execute(
        connection,
        f"DROP TABLE {quote_identifier(_LEGACY_HISTORY_TABLE)}",
    )
    return bool(legacy_history)


async def _table_named_exists(connection: Connection, table_name: str) -> bool:
    cursor = await connection.execute(_HISTORY_OBJECT_SQL, (table_name,))
    try:
        return await cursor.fetchone() is not None
    finally:
        await cursor.close()


async def _ensure_v2_history(
    connection: Connection,
    migrations: MigrationPlan,
    *,
    adopt_legacy: bool,
) -> bool:
    shape = await _fetch_history_shape(connection)
    if shape == "absent":
        await _execute(connection, _CREATE_HISTORY_SQL)
        if await _fetch_history_shape(connection) != "v2":
            msg = "could not create exact SQLite Migration History v2"
            raise MigrationHistoryError(msg)
        return False
    if shape == "v2":
        return False
    if shape == "v1":
        return await _upgrade_legacy_history(
            connection, migrations, adopt_legacy=adopt_legacy
        )
    msg = "Migration History has an unknown SQLite schema"
    raise MigrationHistoryError(msg)


async def _rollback_if_open(connection: Connection) -> None:
    """Leave no owned transaction on a pooled connection after any failure."""

    if not connection.in_transaction:
        return
    with anyio.CancelScope(shield=True):
        await connection.rollback()


async def _commit(connection: Connection) -> None:
    """Commit under shielding, then re-surface any pending cancellation."""

    with anyio.CancelScope(shield=True):
        await connection.commit()
    await checkpoint()


async def _begin_immediate(
    connection: Connection,
    busy_retry_policy: BusyRetryPolicy,
) -> None:
    try:
        await retry_on_sqlite_busy(
            lambda: _execute(connection, "BEGIN IMMEDIATE"),
            busy_retry_policy,
        )
    except Exception as error:
        if not is_sqlite_busy_error(error):
            raise
        attempts = busy_retry_policy.max_retries + 1
        msg = (
            "could not acquire SQLite migration writer lock "
            f"after {attempts} attempt(s)"
        )
        raise MigrationLockTimeoutError(msg) from error


async def _record_history(
    connection: Connection,
    migration: Migration,
) -> None:
    try:
        cursor = await connection.execute(
            _INSERT_HISTORY_SQL,
            (migration.position, migration.name, migration.checksum),
        )
        try:
            inserted_row = await cursor.fetchone()
        finally:
            await cursor.close()
    except Exception as error:
        msg = f"could not record migration {migration.name!r}"
        raise MigrationHistoryError(msg) from error
    expected_row = (migration.position, migration.name, migration.checksum)
    if inserted_row != expected_row:
        msg = f"could not confirm history row for migration {migration.name!r}"
        raise MigrationHistoryError(msg)


async def _apply_body(
    connection: Connection,
    migration: Migration,
    connection_state: SQLiteMigrationConnectionState,
) -> None:
    connection_state.authorizer_uncertain = True
    try:
        await connection.set_authorizer(_migration_authorizer)
        await _execute(connection, migration.sql)
    except Exception as error:
        logger.exception("migration %r failed", migration.name)
        msg = f"migration {migration.name!r} failed"
        raise MigrationError(msg) from error
    finally:
        with anyio.CancelScope(shield=True):
            await connection.set_authorizer(None)
        connection_state.authorizer_uncertain = False
    if not connection.in_transaction:
        msg = f"migration {migration.name!r} ended the transaction owned by snekql"
        raise MigrationError(msg)


async def apply_sqlite_migrations(
    connection: Connection,
    connection_state: SQLiteMigrationConnectionState,
    migrations: MigrationPlan,
    *,
    adopt_legacy: bool = False,
    busy_retry_policy: BusyRetryPolicy = DEFAULT_BUSY_RETRY_POLICY,
) -> MigrationResult:
    """Apply a declaration with one locked atomic transaction per pending body."""

    applied: list[str] = []
    applied_names: set[str] = set()
    already_applied: list[str] = []
    already_applied_names: set[str] = set()
    legacy_adopted = False
    while True:
        transaction_started = False
        try:
            await _begin_immediate(connection, busy_retry_policy)
            transaction_started = True
            legacy_adopted = (
                await _ensure_v2_history(
                    connection,
                    migrations,
                    adopt_legacy=adopt_legacy,
                )
                or legacy_adopted
            )
            history = await _fetch_history(connection)
            validate_history_prefix(history, migrations)
            for record in history:
                if (
                    record.name not in applied_names
                    and record.name not in already_applied_names
                ):
                    already_applied.append(record.name)
                    already_applied_names.add(record.name)
            if len(history) == len(migrations):
                await _commit(connection)
                transaction_started = False
                connection_state.reusable = True
                return MigrationResult(
                    applied=tuple(applied),
                    already_applied=tuple(already_applied),
                    legacy_adopted=legacy_adopted,
                )

            migration = migrations[len(history)]
            await _apply_body(connection, migration, connection_state)
            await _record_history(connection, migration)
            await _commit(connection)
            transaction_started = False
            applied.append(migration.name)
            applied_names.add(migration.name)
            logger.debug("migration %r applied", migration.name)
        except BaseException:
            if transaction_started:
                await _rollback_if_open(connection)
                connection_state.reusable = (
                    not connection.in_transaction
                    and not connection_state.authorizer_uncertain
                )
            raise


async def verify_sqlite_migrations(
    connection: Connection,
    connection_state: SQLiteMigrationConnectionState,
    migrations: MigrationPlan,
) -> None:
    """Verify v2 history at its exact head without taking locks or mutating it."""

    transaction_started = False
    try:
        await _execute(connection, "BEGIN")
        transaction_started = True
        shape = await _fetch_history_shape(connection)
        if shape == "absent":
            if migrations:
                msg = "Migration History is missing"
                raise MigrationHistoryError(msg)
            return
        if shape != "v2":
            msg = f"Migration History uses unsupported SQLite shape {shape!r}"
            raise MigrationHistoryError(msg)
        history = await _fetch_history(connection)
        validate_history_prefix(history, migrations, require_head=True)
    finally:
        if transaction_started:
            await _rollback_if_open(connection)
            connection_state.reusable = not connection.in_transaction

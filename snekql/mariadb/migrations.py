"""MariaDB revision history, function execution, and advisory locking."""

lazy import hashlib
lazy from contextlib import asynccontextmanager
lazy from typing import TYPE_CHECKING, Any, Literal, cast

lazy import anyio
lazy from anyio.lowlevel import checkpoint

lazy from snekql._migrations import (
    Migration,
    MigrationParameters,
    MigrationPlan,
    MigrationRecord,
    MigrationResult,
    MigrationStatus,
    _MigrationQueryResult,
    run_migration,
    validate_history_prefix,
)
lazy from snekql.errors import (
    MigrationDeclarationError,
    MigrationError,
    MigrationHistoryError,
    MigrationLockError,
    MigrationLockTimeoutError,
)
lazy from snekql.mariadb.identifiers import quote_identifier
lazy from snekql.validation import NonNegativeFloat

if TYPE_CHECKING:
    lazy from collections.abc import AsyncGenerator

_HISTORY_TABLE = "snekql_migrations"

_LOCK_NAME_PREFIX = "snekql_migrations."
_LOCK_NAME_MAX = 64

_ACQUIRE_LOCK_SQL = "SELECT GET_LOCK(%s, %s)"
_RELEASE_LOCK_SQL = "SELECT RELEASE_LOCK(%s)"

_NAME_UNIQUE_KEY = "uq_snekql_migrations_name"
_POSITION_CHECK = "chk_snekql_migrations_position"
_NAME_CHECK = "chk_snekql_migrations_name"

_CREATE_HISTORY_SQL = (
    f"CREATE TABLE {quote_identifier(_HISTORY_TABLE)} ("
    "position BIGINT UNSIGNED NOT NULL, "
    "name VARBINARY(1020) NOT NULL, "
    "applied_at DATETIME(3) NOT NULL, "
    "PRIMARY KEY (position), "
    f"UNIQUE KEY {quote_identifier(_NAME_UNIQUE_KEY)} (name), "
    f"CONSTRAINT {quote_identifier(_POSITION_CHECK)} CHECK (position > 0), "
    f"CONSTRAINT {quote_identifier(_NAME_CHECK)} "
    "CHECK (OCTET_LENGTH(name) BETWEEN 1 AND 1020 "
    "AND CHAR_LENGTH(CONVERT(name USING utf8mb4)) BETWEEN 1 AND 255)"
    ") ENGINE=InnoDB"
)
"""Revision history with unpadded byte-exact identity and SQL constraints."""

_HISTORY_OBJECT_SQL = (
    "SELECT TABLE_NAME, TABLE_TYPE, ENGINE FROM INFORMATION_SCHEMA.TABLES "
    "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = %s"
)

_HISTORY_COLUMNS_SQL = (
    "SELECT COLUMN_NAME, COLUMN_TYPE, IS_NULLABLE, COLUMN_KEY, "
    "CHARACTER_SET_NAME, COLLATION_NAME, DATETIME_PRECISION, COLUMN_DEFAULT, EXTRA "
    "FROM INFORMATION_SCHEMA.COLUMNS "
    "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = %s "
    "ORDER BY ORDINAL_POSITION"
)

_HISTORY_INDEXES_SQL = (
    "SELECT INDEX_NAME, NON_UNIQUE, SEQ_IN_INDEX, COLUMN_NAME, SUB_PART "
    "FROM INFORMATION_SCHEMA.STATISTICS "
    "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = %s "
    "ORDER BY INDEX_NAME, SEQ_IN_INDEX"
)

_HISTORY_CHECKS_SQL = (
    "SELECT CONSTRAINT_NAME, CHECK_CLAUSE "
    "FROM INFORMATION_SCHEMA.CHECK_CONSTRAINTS "
    "WHERE CONSTRAINT_SCHEMA = DATABASE() AND TABLE_NAME = %s "
    "ORDER BY CONSTRAINT_NAME"
)

_HISTORY_CONSTRAINTS_SQL = (
    "SELECT CONSTRAINT_NAME, CONSTRAINT_TYPE "
    "FROM INFORMATION_SCHEMA.TABLE_CONSTRAINTS "
    "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = %s "
    "ORDER BY CONSTRAINT_NAME"
)

_HISTORY_TRIGGERS_SQL = (
    "SELECT TRIGGER_NAME FROM INFORMATION_SCHEMA.TRIGGERS "
    "WHERE TRIGGER_SCHEMA = DATABASE() AND EVENT_OBJECT_TABLE = %s"
)

_SELECT_HISTORY_SQL = (
    f"SELECT position, CAST(name AS BINARY) "  # noqa: S608
    f"FROM {quote_identifier(_HISTORY_TABLE)} "
    "ORDER BY position"
)

_INSERT_HISTORY_SQL = (
    f"INSERT INTO {quote_identifier(_HISTORY_TABLE)} "  # noqa: S608
    "(position, name, applied_at) VALUES (%s, %s, UTC_TIMESTAMP(3))"
)

type _HistoryShape = Literal["absent", "unknown", "revision"]

_EXPECTED_CHECKS = {
    _NAME_CHECK: (
        "octet_length(`name`) between 1 and 1020 and "
        "char_length(convert(`name` using utf8mb4)) between 1 and 255"
    ),
    _POSITION_CHECK: "`position` > 0",
}

_RESTRICTED_BODY_TOKENS = frozenset(
    {
        "AUTOCOMMIT",
        "CALL",
        "CHARACTER_SET_CLIENT",
        "CHARACTER_SET_CONNECTION",
        "CHARACTER_SET_RESULTS",
        "CHECK_CONSTRAINT_CHECKS",
        "COLLATION_CONNECTION",
        "COMMIT",
        "EXECUTE",
        "FOREIGN_KEY_CHECKS",
        "GET_LOCK",
        "NAMES",
        "PREPARE",
        "RELEASE_ALL_LOCKS",
        "RELEASE_LOCK",
        "ROLLBACK",
        "SAVEPOINT",
        "SQL_MODE",
        "TIME_ZONE",
        "TRANSACTION",
        "UNIQUE_CHECKS",
        "USE",
    }
)


def _executable_comment_tokens(
    sql: str,
    start: int,
    end: int,
) -> tuple[str, ...]:
    if sql.startswith("/*!", start):
        content_start = start + 3
    elif sql.startswith("/*M!", start):
        content_start = start + 4
    else:
        return ()
    executable_sql = sql[content_start:end].lstrip()
    executable_sql = executable_sql.lstrip("0123456789").lstrip()
    return _sql_tokens(executable_sql)


def _read_quoted(sql: str, index: int, quote: str) -> tuple[str, int]:
    """Read quoted text, treating backslashes literally inside backtick identifiers.

    String literals support backslash escapes; identifiers escape a backtick
    only by doubling it. Confusing these rules can hide transaction control.
    """

    value: list[str] = []
    index += 1
    while index < len(sql):
        if quote != "`" and sql[index] == "\\" and index + 1 < len(sql):
            value.append(sql[index + 1])
            index += 2
            continue
        if sql[index] != quote:
            value.append(sql[index])
            index += 1
            continue
        if index + 1 < len(sql) and sql[index + 1] == quote:
            value.append(quote)
            index += 2
            continue
        return "".join(value), index + 1
    return "".join(value), index


def _sql_tokens(sql: str) -> tuple[str, ...]:  # noqa: C901
    """Extract MariaDB tokens while retaining quoted identifiers, not literals."""

    tokens: list[str] = []
    index = 0
    while index < len(sql):
        character = sql[index]
        if character.isspace():
            index += 1
            continue
        if character == "#":
            newline = sql.find("\n", index + 1)
            index = len(sql) if newline == -1 else newline + 1
            continue
        if sql.startswith("--", index) and (
            index + 2 == len(sql) or sql[index + 2].isspace()
        ):
            newline = sql.find("\n", index + 2)
            index = len(sql) if newline == -1 else newline + 1
            continue
        if sql.startswith("/*", index):
            comment_end = sql.find("*/", index + 2)
            if comment_end == -1:
                index = len(sql)
                continue
            tokens.extend(_executable_comment_tokens(sql, index, comment_end))
            index = comment_end + 2
            continue
        if character == "`":
            identifier, index = _read_quoted(sql, index, character)
            tokens.append(identifier.upper())
            continue
        if character in {"'", '"'}:
            _, index = _read_quoted(sql, index, character)
            continue
        if character.isalpha() or character in {"_", "@"}:
            token_end = index + 1
            while token_end < len(sql) and (
                sql[token_end].isalnum() or sql[token_end] in {"_", "@"}
            ):
                token_end += 1
            tokens.append(sql[index:token_end].upper().lstrip("@"))
            index = token_end
            continue
        if character == ";":
            tokens.append(character)
        index += 1
    return tuple(tokens)


def _statement_starts(tokens: tuple[str, ...]) -> tuple[tuple[str, ...], ...]:
    statements: list[tuple[str, ...]] = []
    start = 0
    for index in range(len(tokens)):
        if tokens[index] != ";":
            continue
        if start < index:
            statements.append(tokens[start:index])
        start = index + 1
    if start < len(tokens):
        statements.append(tokens[start:])
    return tuple(statements)


def _validate_statement(migration: Migration, sql: str) -> None:
    """Keep each command inside the runner's transaction and lock contract."""
    tokens = _sql_tokens(sql)
    statements = _statement_starts(tokens)
    restricted = _RESTRICTED_BODY_TOKENS.intersection(tokens)
    invalid_start = any(
        statement[0] in {"BEGIN", "XA", "SET"}
        or statement[:2] in {("LOCK", "TABLES"), ("START", "TRANSACTION")}
        or statement[:2] == ("UNLOCK", "TABLES")
        for statement in statements
    )
    if (
        len(statements) != 1
        or restricted
        or invalid_start
        or _HISTORY_TABLE.upper() in tokens
        or "TEMPORARY" in tokens
    ):
        msg = f"MariaDB migration {migration.name!r} requires one managed SQL statement"
        raise MigrationDeclarationError(msg)


def build_migration_lock_name(database: str) -> str:
    """Build the per-database `GET_LOCK` name, folding long names to a digest."""

    candidate = f"{_LOCK_NAME_PREFIX}{database}"
    if len(candidate) <= _LOCK_NAME_MAX:
        return candidate
    digest = hashlib.sha256(database.encode("utf-8")).hexdigest()[:16]
    return f"{_LOCK_NAME_PREFIX}{digest}"


async def _close_cursor(cursor: object) -> None:
    close_result = cast("Any", cursor).close()
    if close_result is not None:
        _ = await close_result


async def _execute(
    connection: object,
    sql: str,
    params: tuple[object, ...] | None = None,
) -> None:
    """Execute raw SQL unless internal statements explicitly supply bound values.

    aiomysql interpolates percent signs even with an empty argument tuple.
    None preserves a hand-authored migration body exactly as declared.
    """

    cursor = await cast("Any", connection).cursor()
    try:
        _ = await cursor.execute(sql, params)
    finally:
        await _close_cursor(cursor)


async def _fetch_all(
    connection: object,
    sql: str,
    params: tuple[object, ...] = (),
) -> list[tuple[object, ...]]:
    cursor = await cast("Any", connection).cursor()
    try:
        _ = await cursor.execute(sql, params)
        rows = await cursor.fetchall()
    finally:
        await _close_cursor(cursor)
    return [tuple(row) for row in rows]


async def _fetch_one(
    connection: object,
    sql: str,
    params: tuple[object, ...] = (),
) -> tuple[object, ...] | None:
    cursor = await cast("Any", connection).cursor()
    try:
        _ = await cursor.execute(sql, params)
        row = await cursor.fetchone()
    finally:
        await _close_cursor(cursor)
    return None if row is None else tuple(row)


async def _rollback(connection: object) -> None:
    with anyio.CancelScope(shield=True):
        await cast("Any", connection).rollback()
    await checkpoint()


async def _commit(connection: object) -> None:
    with anyio.CancelScope(shield=True):
        await cast("Any", connection).commit()
    await checkpoint()


def _decode_name(value: object) -> str:
    if isinstance(value, bytes):
        try:
            return value.decode("utf-8")
        except UnicodeDecodeError as error:
            msg = "Migration History contains a name that is not valid UTF-8"
            raise MigrationHistoryError(msg) from error
    if type(value) is str:
        return value
    msg = "Migration History contains a non-text name"
    raise MigrationHistoryError(msg)


async def _fetch_history(connection: object) -> tuple[MigrationRecord, ...]:
    rows = await _fetch_all(connection, _SELECT_HISTORY_SQL)
    return tuple(
        MigrationRecord(
            position=int(cast("int | str | bytes", position)),
            name=_decode_name(name),
        )
        for position, name in rows
    )


def _normalize_check_clause(value: object) -> str:
    return " ".join(str(value).lower().split())


async def _fetch_history_shape(connection: object) -> _HistoryShape:
    table_rows = await _fetch_all(connection, _HISTORY_OBJECT_SQL, (_HISTORY_TABLE,))
    if not table_rows:
        return "absent"
    if table_rows != [(_HISTORY_TABLE, "BASE TABLE", "InnoDB")]:
        return "unknown"

    column_rows = await _fetch_all(connection, _HISTORY_COLUMNS_SQL, (_HISTORY_TABLE,))
    index_rows = await _fetch_all(connection, _HISTORY_INDEXES_SQL, (_HISTORY_TABLE,))
    check_rows = await _fetch_all(connection, _HISTORY_CHECKS_SQL, (_HISTORY_TABLE,))
    constraint_rows = await _fetch_all(
        connection, _HISTORY_CONSTRAINTS_SQL, (_HISTORY_TABLE,)
    )
    trigger_rows = await _fetch_all(
        connection, _HISTORY_TRIGGERS_SQL, (_HISTORY_TABLE,)
    )
    column_names = tuple(str(row[0]) for row in column_rows)
    indexes = {
        (
            str(name),
            int(cast("int | str | bytes", non_unique)),
            int(cast("int | str | bytes", sequence)),
            str(column),
            prefix,
        )
        for name, non_unique, sequence, column, prefix in index_rows
    }
    checks = {str(name): _normalize_check_clause(clause) for name, clause in check_rows}
    constraints = {(str(name), str(kind)) for name, kind in constraint_rows}
    if trigger_rows:
        return "unknown"

    if column_names == ("position", "name", "applied_at"):
        position, name, applied_at = column_rows
        expected_indexes = {
            ("PRIMARY", 0, 1, "position", None),
            (_NAME_UNIQUE_KEY, 0, 1, "name", None),
        }
        expected_constraints = {
            ("PRIMARY", "PRIMARY KEY"),
            (_NAME_UNIQUE_KEY, "UNIQUE"),
            (_NAME_CHECK, "CHECK"),
            (_POSITION_CHECK, "CHECK"),
        }
        if (
            tuple(position)
            == (
                "position",
                "bigint(20) unsigned",
                "NO",
                "PRI",
                None,
                None,
                None,
                None,
                "",
            )
            and tuple(name)
            == (
                "name",
                "varbinary(1020)",
                "NO",
                "UNI",
                None,
                None,
                None,
                None,
                "",
            )
            and tuple(applied_at)
            == (
                "applied_at",
                "datetime(3)",
                "NO",
                "",
                None,
                None,
                3,
                None,
                "",
            )
            and indexes == expected_indexes
            and constraints == expected_constraints
            and checks == _EXPECTED_CHECKS
        ):
            return "revision"
    return "unknown"


async def _ensure_history(connection: object) -> None:
    shape = await _fetch_history_shape(connection)
    if shape == "absent":
        await _execute(connection, _CREATE_HISTORY_SQL)
        shape = await _fetch_history_shape(connection)
    if shape != "revision":
        msg = "Migration History has an unsupported MariaDB schema"
        raise MigrationHistoryError(msg)


class MariaDBMigrationBackend:
    """Own one MariaDB connection and its migration advisory-lock disposition."""

    def __init__(
        self,
        connection: object,
        *,
        lock_name: str,
        lock_timeout: NonNegativeFloat,
    ) -> None:
        self.connection: object = connection
        self.connection_reusable: bool = False
        self.lock_name: str = lock_name
        self.lock_timeout: NonNegativeFloat = lock_timeout

    @asynccontextmanager
    async def migration_lock(self) -> AsyncGenerator[None]:
        """Hold and positively release the connection-scoped migration lock."""

        acquired = await self._acquire_lock()
        if not acquired:
            self.connection_reusable = True
            msg = (
                f"timed out acquiring migration lock {self.lock_name!r} "
                f"after {self.lock_timeout}s; another instance is migrating"
            )
            raise MigrationLockTimeoutError(msg)
        try:
            yield
        finally:
            with anyio.CancelScope(shield=True):
                await self._release_lock()
            self.connection_reusable = True
            await checkpoint()

    async def _acquire_lock(self) -> bool:
        try:
            row = await _fetch_one(
                self.connection,
                _ACQUIRE_LOCK_SQL,
                (self.lock_name, self.lock_timeout),
            )
        except BaseException as error:
            if isinstance(error, anyio.get_cancelled_exc_class()):
                raise
            msg = f"could not acquire migration lock {self.lock_name!r}"
            raise MigrationLockError(msg) from error
        if row == (1,):
            return True
        if row == (0,):
            return False
        msg = f"could not confirm acquisition of migration lock {self.lock_name!r}"
        raise MigrationLockError(msg)

    async def _release_lock(self) -> None:
        released = False
        while True:
            try:
                row = await _fetch_one(
                    self.connection,
                    _RELEASE_LOCK_SQL,
                    (self.lock_name,),
                )
            except BaseException as error:
                if isinstance(error, anyio.get_cancelled_exc_class()):
                    raise
                msg = f"could not release migration lock {self.lock_name!r}"
                raise MigrationLockError(msg) from error
            if row == (1,):
                released = True
                continue
            if released and row in {(0,), (None,)}:
                return
            msg = f"could not confirm release of migration lock {self.lock_name!r}"
            raise MigrationLockError(msg)


async def _apply_body_and_history(
    connection: object,
    migration: Migration,
    expected_history: MigrationPlan,
) -> None:
    """Commit only after the body has preserved the canonical history contract."""

    async def execute(sql: str, params: MigrationParameters) -> _MigrationQueryResult:
        _validate_statement(migration, sql)
        cursor = await cast("Any", connection).cursor()
        try:
            await cursor.execute(sql, params)
            rows = (
                [tuple(row) for row in await cursor.fetchall()]
                if cursor.description is not None
                else []
            )
            return _MigrationQueryResult(rows=rows, rowcount=cursor.rowcount)
        finally:
            await _close_cursor(cursor)

    await cast("Any", connection).begin()
    try:
        await run_migration(migration, execute)
    except BaseException as error:
        await _rollback(connection)
        if isinstance(error, anyio.get_cancelled_exc_class()):
            raise
        msg = f"migration {migration.name!r} failed"
        raise MigrationError(msg) from error
    try:
        await _execute(
            connection,
            _INSERT_HISTORY_SQL,
            (
                migration.position,
                migration.name.encode("utf-8"),
            ),
        )
        if await _fetch_history_shape(connection) != "revision":
            msg = "migration changed the owned Migration History schema"
            raise MigrationHistoryError(msg)  # noqa: TRY301 - rollback belongs to this unit
        validate_history_prefix(
            await _fetch_history(connection), expected_history, require_head=True
        )
        await _commit(connection)
    except BaseException as error:
        await _rollback(connection)
        if isinstance(error, anyio.get_cancelled_exc_class()):
            raise
        msg = f"could not record migration {migration.name!r}"
        raise MigrationHistoryError(msg) from error


async def apply_mariadb_migrations(
    backend: MariaDBMigrationBackend,
    migrations: MigrationPlan,
) -> MigrationResult:
    """Apply a complete declaration under one connection-scoped advisory lock."""

    async with backend.migration_lock():
        try:
            await _ensure_history(backend.connection)
            history = await _fetch_history(backend.connection)
            validate_history_prefix(history, migrations)
            already_applied = tuple(record.name for record in history)
            await _rollback(backend.connection)
            applied: list[str] = []
            for migration in migrations[len(history) :]:
                await _apply_body_and_history(
                    backend.connection, migration, migrations[: migration.position]
                )
                applied.append(migration.name)
            return MigrationResult(
                applied=tuple(applied),
                already_applied=already_applied,
            )
        except BaseException:
            await _rollback(backend.connection)
            raise


async def verify_mariadb_migrations(
    connection: object,
    migrations: MigrationPlan,
    *,
    minimum_applied: int | None = None,
) -> MigrationStatus:
    """Verify revision history within the approved range without mutation."""

    if minimum_applied is None:
        minimum_applied = len(migrations)
    try:
        shape = await _fetch_history_shape(connection)
        if shape == "absent":
            if minimum_applied:
                msg = "Migration History is missing"
                raise MigrationHistoryError(msg)
            return MigrationStatus(
                applied=(),
                history_present=False,
                pending=tuple(migration.name for migration in migrations),
            )
        if shape != "revision":
            msg = f"Migration History uses unsupported MariaDB shape {shape!r}"
            raise MigrationHistoryError(msg)
        history = await _fetch_history(connection)
        validate_history_prefix(history, migrations, minimum_applied=minimum_applied)
        return MigrationStatus(
            applied=tuple(record.name for record in history),
            history_present=True,
            pending=tuple(migration.name for migration in migrations[len(history) :]),
        )
    finally:
        await _rollback(connection)


__all__ = [
    "MariaDBMigrationBackend",
    "apply_mariadb_migrations",
    "build_migration_lock_name",
    "verify_mariadb_migrations",
]

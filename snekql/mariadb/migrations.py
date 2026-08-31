"""MariaDB Migration History v2, legacy adoption, and advisory locking."""

from __future__ import annotations

import hashlib
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, Any, Literal, cast

import anyio
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
    MigrationLockError,
    MigrationLockTimeoutError,
)
from snekql.mariadb.identifiers import quote_identifier
from snekql.mariadb.schema import TEXT_COLLATION
from snekql.validation import NonNegativeFloat

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

_HISTORY_TABLE = "snekql_migrations"

_LOCK_NAME_PREFIX = "snekql_migrations."
_LOCK_NAME_MAX = 64

_ACQUIRE_LOCK_SQL = "SELECT GET_LOCK(%s, %s)"
_RELEASE_LOCK_SQL = "SELECT RELEASE_LOCK(%s)"

_NAME_UNIQUE_KEY = "uq_snekql_migrations_name"
_POSITION_CHECK = "chk_snekql_migrations_position"
_NAME_CHECK = "chk_snekql_migrations_name"
_CHECKSUM_CHECK = "chk_snekql_migrations_checksum"

_CREATE_HISTORY_SQL = (
    f"CREATE TABLE {quote_identifier(_HISTORY_TABLE)} ("
    "position BIGINT UNSIGNED NOT NULL, "
    "name VARBINARY(1020) NOT NULL, "
    "checksum VARBINARY(64) NOT NULL, "
    "applied_at DATETIME(3) NOT NULL, "
    "PRIMARY KEY (position), "
    f"UNIQUE KEY {quote_identifier(_NAME_UNIQUE_KEY)} (name), "
    f"CONSTRAINT {quote_identifier(_POSITION_CHECK)} CHECK (position > 0), "
    f"CONSTRAINT {quote_identifier(_NAME_CHECK)} "
    "CHECK (OCTET_LENGTH(name) BETWEEN 1 AND 1020 "
    "AND CHAR_LENGTH(CONVERT(name USING utf8mb4)) BETWEEN 1 AND 255), "
    f"CONSTRAINT {quote_identifier(_CHECKSUM_CHECK)} "
    "CHECK (OCTET_LENGTH(checksum) = 64 "
    "AND checksum NOT REGEXP BINARY '[^0-9a-f]')"
    ") ENGINE=InnoDB"
)
"""Final v2 history with unpadded byte-exact identity and SQL constraints."""

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
    f"SELECT position, CAST(name AS BINARY), CAST(checksum AS BINARY) "  # noqa: S608
    f"FROM {quote_identifier(_HISTORY_TABLE)} "
    "ORDER BY position"
)

_SELECT_LEGACY_SQL = (
    f"SELECT CAST(name AS BINARY), applied_at FROM {quote_identifier(_HISTORY_TABLE)}"  # noqa: S608
)

_SELECT_STAGING_SQL = (
    f"SELECT CAST(name AS BINARY), applied_at, position, checksum "  # noqa: S608
    f"FROM {quote_identifier(_HISTORY_TABLE)}"
)

_INSERT_HISTORY_SQL = (
    f"INSERT INTO {quote_identifier(_HISTORY_TABLE)} "  # noqa: S608
    "(position, name, checksum, applied_at) VALUES (%s, %s, %s, UTC_TIMESTAMP(3))"
)

_ADD_STAGING_COLUMNS_SQL = (
    f"ALTER TABLE {quote_identifier(_HISTORY_TABLE)} "
    "ADD COLUMN position BIGINT UNSIGNED NULL, "
    "ADD COLUMN checksum VARBINARY(64) NULL"
)

_UPDATE_STAGING_SQL = (
    f"UPDATE {quote_identifier(_HISTORY_TABLE)} "  # noqa: S608
    "SET position = %s, checksum = %s WHERE BINARY name = %s "
    "AND position IS NULL AND checksum IS NULL"
)

_FINALIZE_STAGING_SQL = (
    f"ALTER TABLE {quote_identifier(_HISTORY_TABLE)} "
    "MODIFY COLUMN position BIGINT UNSIGNED NOT NULL FIRST, "
    "MODIFY COLUMN name VARBINARY(1020) NOT NULL AFTER position, "
    "MODIFY COLUMN checksum VARBINARY(64) NOT NULL AFTER name, "
    "MODIFY COLUMN applied_at DATETIME(3) NOT NULL AFTER checksum, "
    "DROP PRIMARY KEY, ADD PRIMARY KEY (position), "
    f"ADD UNIQUE KEY {quote_identifier(_NAME_UNIQUE_KEY)} (name), "
    f"ADD CONSTRAINT {quote_identifier(_POSITION_CHECK)} CHECK (position > 0), "
    f"ADD CONSTRAINT {quote_identifier(_NAME_CHECK)} "
    "CHECK (OCTET_LENGTH(name) BETWEEN 1 AND 1020 "
    "AND CHAR_LENGTH(CONVERT(name USING utf8mb4)) BETWEEN 1 AND 255), "
    f"ADD CONSTRAINT {quote_identifier(_CHECKSUM_CHECK)} "
    "CHECK (OCTET_LENGTH(checksum) = 64 "
    "AND checksum NOT REGEXP BINARY '[^0-9a-f]')"
)

type _HistoryShape = Literal["absent", "staging", "unknown", "v1", "v2"]

_EXPECTED_CHECKS = {
    _CHECKSUM_CHECK: (
        "octet_length(`checksum`) = 64 and "
        "!(`checksum` regexp cast('[^0-9a-f]' as char charset binary))"
    ),
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

_V1_COLUMN_COUNT = 2


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
    """Read one MariaDB quoted value, resolving doubled and escaped characters."""

    value: list[str] = []
    index += 1
    while index < len(sql):
        if sql[index] == "\\" and index + 1 < len(sql):
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


def validate_mariadb_migrations(migrations: MigrationPlan) -> None:
    """Reject bodies that can escape migration transaction or lock ownership."""

    for migration in migrations:
        tokens = _sql_tokens(migration.sql)
        restricted = _RESTRICTED_BODY_TOKENS.intersection(tokens)
        invalid_start = any(
            statement[0] in {"BEGIN", "XA"}
            or statement[:2] in {("LOCK", "TABLES"), ("START", "TRANSACTION")}
            or statement[:2] == ("UNLOCK", "TABLES")
            for statement in _statement_starts(tokens)
            if statement
        )
        if restricted or invalid_start:
            msg = (
                f"MariaDB migration {migration.name!r} cannot change transaction "
                "or advisory-lock state"
            )
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
    params: tuple[object, ...] = (),
) -> None:
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


def _decode_checksum(value: object) -> str:
    if isinstance(value, bytes):
        try:
            return value.decode("ascii")
        except UnicodeDecodeError as error:
            msg = "Migration History contains a non-ASCII checksum"
            raise MigrationHistoryError(msg) from error
    if type(value) is str:
        return value
    msg = "Migration History contains an invalid checksum"
    raise MigrationHistoryError(msg)


async def _fetch_history(connection: object) -> tuple[MigrationRecord, ...]:
    rows = await _fetch_all(connection, _SELECT_HISTORY_SQL)
    return tuple(
        MigrationRecord(
            position=int(cast("int | str | bytes", position)),
            name=_decode_name(name),
            checksum=_decode_checksum(checksum),
        )
        for position, name, checksum in rows
    )


def _normalize_check_clause(value: object) -> str:
    return " ".join(str(value).lower().split())


def _has_v1_columns(column_rows: list[tuple[object, ...]]) -> bool:
    if len(column_rows) < _V1_COLUMN_COUNT:
        return False
    name, applied_at = column_rows[:_V1_COLUMN_COUNT]
    return tuple(name) == (
        "name",
        "varchar(255)",
        "NO",
        "PRI",
        "utf8mb4",
        TEXT_COLLATION,
        None,
        None,
        "",
    ) and tuple(applied_at) == (
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


async def _fetch_history_shape(connection: object) -> _HistoryShape:  # noqa: PLR0911
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

    if column_names == ("name", "applied_at"):
        if (
            _has_v1_columns(column_rows)
            and indexes == {("PRIMARY", 0, 1, "name", None)}
            and constraints == {("PRIMARY", "PRIMARY KEY")}
            and not checks
        ):
            return "v1"
        return "unknown"

    if column_names == ("name", "applied_at", "position", "checksum"):
        position = column_rows[2]
        checksum = column_rows[3]
        if (
            _has_v1_columns(column_rows)
            and tuple(position)
            == (
                "position",
                "bigint(20) unsigned",
                "YES",
                "",
                None,
                None,
                None,
                "NULL",
                "",
            )
            and tuple(checksum)
            == (
                "checksum",
                "varbinary(64)",
                "YES",
                "",
                None,
                None,
                None,
                "NULL",
                "",
            )
            and indexes == {("PRIMARY", 0, 1, "name", None)}
            and constraints == {("PRIMARY", "PRIMARY KEY")}
            and not checks
        ):
            return "staging"
        return "unknown"

    if column_names == ("position", "name", "checksum", "applied_at"):
        position, name, checksum, applied_at = column_rows
        expected_indexes = {
            ("PRIMARY", 0, 1, "position", None),
            (_NAME_UNIQUE_KEY, 0, 1, "name", None),
        }
        expected_constraints = {
            ("PRIMARY", "PRIMARY KEY"),
            (_NAME_UNIQUE_KEY, "UNIQUE"),
            (_CHECKSUM_CHECK, "CHECK"),
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
            and tuple(checksum)
            == (
                "checksum",
                "varbinary(64)",
                "NO",
                "",
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
            return "v2"
    return "unknown"


async def _fill_staging_history(
    connection: object,
    migrations: MigrationPlan,
) -> bool:
    rows = await _fetch_all(connection, _SELECT_STAGING_SQL)
    legacy_names = {_decode_name(row[0]) for row in rows}
    prefix_length = validate_legacy_history(legacy_names, migrations)
    expected_by_name = {
        migration.name: migration for migration in migrations[:prefix_length]
    }
    for name_value, _, position, checksum in rows:
        name = _decode_name(name_value)
        migration = expected_by_name[name]
        if position is None and checksum is None:
            await _execute(
                connection,
                _UPDATE_STAGING_SQL,
                (
                    migration.position,
                    migration.checksum.encode("ascii"),
                    name.encode("utf-8"),
                ),
            )
            continue
        if position is None or checksum is None:
            msg = f"legacy staging row {name!r} is only partially populated"
            raise MigrationHistoryError(msg)
        if (
            int(cast("int | str | bytes", position)) != migration.position
            or _decode_checksum(checksum) != migration.checksum
        ):
            msg = f"legacy staging row {name!r} differs from the declaration"
            raise MigrationHistoryError(msg)
    await _commit(connection)
    await _execute(connection, _FINALIZE_STAGING_SQL)
    if await _fetch_history_shape(connection) != "v2":
        msg = "could not finalize exact MariaDB Migration History v2"
        raise MigrationHistoryError(msg)
    return bool(rows)


async def _ensure_v2_history(
    connection: object,
    migrations: MigrationPlan,
    *,
    adopt_legacy: bool,
) -> bool:
    shape = await _fetch_history_shape(connection)
    if shape == "absent":
        await _execute(connection, _CREATE_HISTORY_SQL)
        if await _fetch_history_shape(connection) != "v2":
            msg = "could not create exact MariaDB Migration History v2"
            raise MigrationHistoryError(msg)
        return False
    if shape == "v2":
        return False
    if shape == "unknown":
        msg = "Migration History has an unknown MariaDB schema"
        raise MigrationHistoryError(msg)
    if shape == "v1":
        legacy_rows = await _fetch_all(connection, _SELECT_LEGACY_SQL)
        legacy_names = {_decode_name(row[0]) for row in legacy_rows}
        if legacy_names and not adopt_legacy:
            msg = (
                "non-empty legacy Migration History requires "
                "migrate(..., adopt_legacy=True)"
            )
            raise MigrationHistoryError(msg)
        validate_legacy_history(legacy_names, migrations)
        await _execute(connection, _ADD_STAGING_COLUMNS_SQL)
    return await _fill_staging_history(connection, migrations)


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
) -> None:
    await cast("Any", connection).begin()
    try:
        await _execute(connection, migration.sql)
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
                migration.checksum.encode("ascii"),
            ),
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
    *,
    adopt_legacy: bool = False,
) -> MigrationResult:
    """Apply a complete declaration under one connection-scoped advisory lock."""

    async with backend.migration_lock():
        try:
            legacy_adopted = await _ensure_v2_history(
                backend.connection,
                migrations,
                adopt_legacy=adopt_legacy,
            )
            history = await _fetch_history(backend.connection)
            validate_history_prefix(history, migrations)
            already_applied = tuple(record.name for record in history)
            await _rollback(backend.connection)
            applied: list[str] = []
            for migration in migrations[len(history) :]:
                await _apply_body_and_history(backend.connection, migration)
                applied.append(migration.name)
            return MigrationResult(
                applied=tuple(applied),
                already_applied=already_applied,
                legacy_adopted=legacy_adopted,
            )
        except BaseException:
            await _rollback(backend.connection)
            raise


async def verify_mariadb_migrations(
    connection: object,
    migrations: MigrationPlan,
) -> None:
    """Require exact final v2 history without locking or changing its schema."""

    try:
        shape = await _fetch_history_shape(connection)
        if shape == "absent":
            if migrations:
                msg = "Migration History is missing"
                raise MigrationHistoryError(msg)
            return
        if shape != "v2":
            msg = f"Migration History uses unsupported MariaDB shape {shape!r}"
            raise MigrationHistoryError(msg)
        history = await _fetch_history(connection)
        validate_history_prefix(history, migrations, require_head=True)
    finally:
        await _rollback(connection)


__all__ = [
    "MariaDBMigrationBackend",
    "apply_mariadb_migrations",
    "build_migration_lock_name",
    "validate_mariadb_migrations",
    "verify_mariadb_migrations",
]

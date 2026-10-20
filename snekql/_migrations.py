"""Immutable Migration declarations, results, and history comparison."""

lazy from annotationlib import Format
lazy from collections.abc import Awaitable, Callable, Mapping, Sequence
lazy from dataclasses import dataclass
lazy from inspect import iscoroutinefunction, signature

lazy import anyio

lazy from snekql.errors import (
    MigrationDeclarationError,
    MigrationError,
    MigrationHistoryError,
)

_MAX_MIGRATION_NAME_LENGTH = 255


@dataclass(frozen=True, slots=True)
class MigrationStatus:
    """Read-only, point-in-time status of a complete Migration declaration.

    `applied` and `pending` contain ordered names. Absent history does not imply
    an empty database. This snapshot does not reserve a plan for later execution.
    """

    applied: tuple[str, ...]
    history_present: bool
    pending: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class MigrationResult:
    """Ordered outcome of applying one complete Migration declaration.

    `applied` names ran during this call. `already_applied` names were found
    in valid ordered history rather than run by this call.
    """

    applied: tuple[str, ...]
    already_applied: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class Migration:
    """One validated Migration in an immutable declaration snapshot."""

    position: int
    name: str
    body: MigrationFunction

    def history_record(self) -> MigrationRecord:
        """Return the correctness fields persisted in Migration History."""

        return MigrationRecord(
            position=self.position,
            name=self.name,
        )


@dataclass(frozen=True, slots=True)
class MigrationRecord:
    """Correctness-bearing fields read from one Migration History row."""

    position: int
    name: str


type MigrationPlan = tuple[Migration, ...]


type MigrationParameters = Mapping[str, object] | Sequence[object] | None


@dataclass(frozen=True, slots=True)
class _MigrationQueryResult:
    rows: list[tuple[object, ...]]
    rowcount: int


type _MigrationExecutor = Callable[
    [str, MigrationParameters], Awaitable[_MigrationQueryResult]
]


class MigrationContext:
    """SQL access on one managed migration connection, valid only in its body.

    Values use native backend placeholders. There is no commit, rollback, pool
    access, or transaction entry: the runner owns transaction/history completion.
    """

    def __init__(self, execute: _MigrationExecutor) -> None:
        self._execute = execute
        self._owner = anyio.get_current_task().id
        self._active = True

    def _expire(self) -> None:
        self._active = False

    async def _query(
        self, sql: str, params: MigrationParameters
    ) -> _MigrationQueryResult:
        if not self._active or anyio.get_current_task().id != self._owner:
            msg = "migration context is inactive or used from another task"
            raise MigrationError(msg)
        if type(sql) is not str or not sql.strip() or "\x00" in sql:
            msg = "migration SQL must be a non-empty string without NUL characters"
            raise MigrationDeclarationError(msg)
        return await self._execute(sql, params)

    async def execute(self, sql: str, *, params: MigrationParameters = None) -> int:
        """Execute one SQL statement and return the driver row count."""
        return (await self._query(sql, params)).rowcount

    async def fetch_all(
        self, sql: str, *, params: MigrationParameters = None
    ) -> list[tuple[object, ...]]:
        """Execute one SQL statement and return native tuple rows."""
        return (await self._query(sql, params)).rows


type MigrationFunction = Callable[[MigrationContext], Awaitable[None]]


def prepare_migrations(migrations: object) -> MigrationPlan:
    """Snapshot one complete ordered chain of revision IDs and async functions."""
    if not isinstance(migrations, Mapping):
        msg = "migrations must map revision IDs to async functions"
        raise MigrationDeclarationError(msg)
    prepared: list[Migration] = []
    for position, (name, body) in enumerate(tuple(migrations.items()), start=1):
        if type(name) is not str or not name or len(name) > _MAX_MIGRATION_NAME_LENGTH:
            msg = f"migration revision at position {position} must be a 1-255 character str"
            raise MigrationDeclarationError(msg)
        if "\x00" in name:
            msg = f"migration {name!r} contains a NUL character"
            raise MigrationDeclarationError(msg)
        try:
            name.encode("utf-8")
        except UnicodeEncodeError as error:
            msg = f"migration {name!r} must contain valid UTF-8 text"
            raise MigrationDeclarationError(msg) from error
        if not iscoroutinefunction(body):
            msg = f"migration {name!r} must be an async function"
            raise MigrationDeclarationError(msg)
        try:
            signature(body, annotation_format=Format.STRING).bind(object())
        except (TypeError, ValueError) as error:
            msg = f"migration {name!r} must accept one migration context"
            raise MigrationDeclarationError(msg) from error
        prepared.append(Migration(position=position, name=name, body=body))
    return tuple(prepared)


def validate_history_prefix(
    actual: tuple[MigrationRecord, ...],
    expected: MigrationPlan,
    *,
    require_head: bool = False,
    minimum_applied: int = 0,
) -> None:
    """Require an unchanged ordered prefix containing every mandatory migration."""

    if len(actual) > len(expected):
        msg = (
            f"Migration History has {len(actual)} row(s), but the declaration "
            f"has only {len(expected)}"
        )
        raise MigrationHistoryError(msg)
    for ordinal, record in enumerate(actual, start=1):
        if record.position != ordinal:
            msg = (
                f"Migration History position {record.position} is invalid; "
                f"expected {ordinal}"
            )
            raise MigrationHistoryError(msg)
        expected_record = expected[ordinal - 1].history_record()
        if record != expected_record:
            msg = (
                f"Migration History diverges at position {ordinal}: "
                f"recorded {record.name!r}, declared {expected_record.name!r}"
            )
            raise MigrationHistoryError(msg)
    if require_head:
        minimum_applied = len(expected)
    if len(actual) < minimum_applied:
        next_name = expected[len(actual)].name
        msg = f"Migration History is behind the declaration; {next_name!r} is pending"
        raise MigrationHistoryError(msg)


async def run_migration(migration: Migration, execute: _MigrationExecutor) -> None:
    """Bound context lifetime to its pending function, even on cancellation."""
    context = MigrationContext(execute)
    try:
        result = await migration.body(context)
        if result is not None:
            msg = "migration functions must return None"
            raise MigrationDeclarationError(msg)
    finally:
        context._expire()  # noqa: SLF001 - runner owns context lifetime

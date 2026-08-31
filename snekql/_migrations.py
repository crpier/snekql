"""Immutable Migration declarations, results, and history comparison."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256

from snekql.errors import (
    MigrationDeclarationError,
    MigrationHistoryError,
)

_MAX_MIGRATION_NAME_LENGTH = 255


@dataclass(frozen=True, slots=True)
class MigrationResult:
    """Ordered outcome of applying one complete Migration declaration.

    `applied` names ran during this call. `already_applied` names were found in
    valid history rather than run by this call. `legacy_adopted` is true when
    this call adopted v1 history or completed a previously consented staged
    adoption.
    """

    applied: tuple[str, ...]
    already_applied: tuple[str, ...]
    legacy_adopted: bool


@dataclass(frozen=True, slots=True)
class Migration:
    """One validated Migration in an immutable declaration snapshot."""

    position: int
    name: str
    checksum: str
    sql: str

    def history_record(self) -> MigrationRecord:
        """Return the correctness fields persisted in Migration History."""

        return MigrationRecord(
            position=self.position,
            name=self.name,
            checksum=self.checksum,
        )


@dataclass(frozen=True, slots=True)
class MigrationRecord:
    """Correctness-bearing fields read from one Migration History row."""

    position: int
    name: str
    checksum: str


type MigrationPlan = tuple[Migration, ...]


def prepare_migrations(migrations: dict[str, str]) -> MigrationPlan:
    """Snapshot and validate one complete linear Migration declaration.

    Exact built-in strings keep names and checksums byte-stable and avoid a
    mutable or hostile string subclass changing after validation.
    """

    if type(migrations) is not dict:
        msg = "migrations must be an exact dict[str, str]"
        raise MigrationDeclarationError(msg)

    prepared: list[Migration] = []
    for position, (name, sql) in enumerate(tuple(migrations.items()), start=1):
        if type(name) is not str:
            msg = f"migration name at position {position} must be an exact str"
            raise MigrationDeclarationError(msg)
        if not name:
            msg = f"migration name at position {position} must not be empty"
            raise MigrationDeclarationError(msg)
        if len(name) > _MAX_MIGRATION_NAME_LENGTH:
            msg = f"migration name {name!r} exceeds 255 characters"
            raise MigrationDeclarationError(msg)
        if type(sql) is not str:
            msg = f"migration {name!r} body must be an exact str"
            raise MigrationDeclarationError(msg)
        if not sql.strip():
            msg = f"migration {name!r} body must contain SQL"
            raise MigrationDeclarationError(msg)
        if "\x00" in name or "\x00" in sql:
            msg = f"migration {name!r} contains a NUL character"
            raise MigrationDeclarationError(msg)
        try:
            name.encode("utf-8")
            sql_bytes = sql.encode("utf-8")
        except UnicodeEncodeError as error:
            msg = f"migration {name!r} must contain valid UTF-8 text"
            raise MigrationDeclarationError(msg) from error
        prepared.append(
            Migration(
                position=position,
                name=name,
                checksum=sha256(sql_bytes).hexdigest(),
                sql=sql,
            )
        )
    return tuple(prepared)


def validate_history_prefix(
    actual: tuple[MigrationRecord, ...],
    expected: MigrationPlan,
    *,
    require_head: bool = False,
) -> None:
    """Require ordered history to equal a valid declaration prefix or head."""

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
    if require_head and len(actual) != len(expected):
        next_name = expected[len(actual)].name
        msg = f"Migration History is behind the declaration; {next_name!r} is pending"
        raise MigrationHistoryError(msg)


def validate_legacy_history(
    legacy_names: set[str],
    expected: MigrationPlan,
) -> int:
    """Require unordered v1 names to equal one complete declared prefix set."""

    if len(legacy_names) > len(expected):
        msg = "legacy Migration History is longer than the declaration"
        raise MigrationHistoryError(msg)
    prefix_length = len(legacy_names)
    declared_prefix = {migration.name for migration in expected[:prefix_length]}
    if legacy_names != declared_prefix:
        msg = "legacy Migration History is not the declared prefix"
        raise MigrationHistoryError(msg)
    return prefix_length

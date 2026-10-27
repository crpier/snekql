"""Prepare bounded SQLite rebuilds from complete observed CREATE definitions."""

from collections import Counter
from typing import Any

from pydantic import Field

from snekql.errors import SchemaError
from snekql.experimental._migration_checks import (
    removed_check_obstacle,
)
from snekql.experimental._migration_indexes import (
    validate_removed_sqlite_indexes,
)
from snekql.experimental._migration_reference_parents import (
    validate_sqlite_reference_parents,
)
from snekql.experimental._migration_sql import (
    ascii_lower,
    column_name,
    split_table,
    tokens,
)
from snekql.experimental.migrations import (
    AdoptTable,
    Package,
    PackageError,
    Parameter,
    State,
    _Value,
)
lazy from snekql.experimental._migration_prepare_v1 import prepare_steps as prepare_v1


class ExecutionStep(_Value):
    """One progress unit, possibly several transactional SQLite rebuild statements."""

    statements: tuple[str, ...]
    bindings: tuple[tuple[Parameter, ...], ...]
    transactional: bool = False
    required: tuple[tuple[str, str], ...] = ()
    rebuild: bool = False
    sequence_table: str | None = None
    copy_tables: tuple[str, str] | None = None
    copy_at: int | None = None
    copy_columns: tuple[str, ...] = Field(
        default=(), exclude_if=lambda value: not value
    )
    dropped_columns: tuple[str, ...] = Field(
        default=(), exclude_if=lambda value: not value
    )
    validate_triggers: bool = False


def prepare_steps(
    package: Package, catalog: list[tuple[Any, ...]], *, execution_epoch: int
) -> tuple[ExecutionStep, ...]:
    """Dispatch by the package/retained-plan epoch, never a current lowerer default."""
    if (
        type(execution_epoch) is not int
        or execution_epoch != 1
        or execution_epoch != package.execution_epoch
    ):
        msg = "prepared execution epoch differs from package interpretation"
        raise PackageError(msg)
    return prepare_v1(package, catalog)


def _signature(sql: str) -> tuple[tuple[str, str], ...]:
    return tuple(
        (
            token.kind,
            ascii_lower(token.value) if token.kind == "word" else token.value,
        )
        for token in tokens(sql)
    )


def _index_signature(sql: str) -> tuple[tuple[str, str], ...]:
    """Ignore only the known execution guard, not persistent index properties."""
    signature = _signature(sql)
    guard = (("word", "if"), ("word", "not"), ("word", "exists"))
    for prefix in (
        (("word", "create"), ("word", "index")),
        (("word", "create"), ("word", "unique"), ("word", "index")),
    ):
        offset = len(prefix)
        if (
            signature[:offset] == prefix
            and signature[offset : offset + len(guard)] == guard
        ):
            return signature[:offset] + signature[offset + len(guard) :]
    return signature


def validate_preserved(package: Package, objects: list[tuple[Any, ...]]) -> None:
    """Allow unmanaged additions only after validating every recorded managed fact."""
    validate_managed(package.draft.before, objects)


def validate_managed(state: State, objects: list[tuple[Any, ...]]) -> None:
    """Check recorded SQLite facts without claiming ownership of unmanaged extras."""
    for table in state.tables:
        actual = next(
            (row[3] for row in objects if row[0] == "table" and row[1] == table.name),
            None,
        )
        if actual is None:
            msg = f"managed table {table.name!r} is missing"
            raise PackageError(msg)
        _, expected_parts, expected_suffix = split_table(table.sql)
        _, actual_parts, actual_suffix = split_table(actual)
        expected_signatures = Counter(_part_signature(part) for part in expected_parts)
        actual_signatures = Counter(_part_signature(part) for part in actual_parts)
        if (
            _signature(expected_suffix) != _signature(actual_suffix)
            or expected_signatures - actual_signatures
        ):
            msg = f"{table.name}: managed declarations differ from the observed definitions"
            raise PackageError(msg)
        indexes = {
            _index_signature(row[3])
            for row in objects
            if row[0] == "index" and row[2] == table.name and row[3] is not None
        }
        if any(_index_signature(sql) not in indexes for sql in table.indexes):
            msg = f"{table.name}: a managed index has changed or disappeared"
            raise PackageError(msg)


def validate_completed(package: Package, objects: list[tuple[Any, ...]]) -> None:
    """Require the managed SQLite endpoint before committing completion evidence."""
    try:
        validate_managed(package.target, objects)
        validate_sqlite_reference_parents(package, objects)
        validate_removed_sqlite_indexes(package, objects)
    except (PackageError, SchemaError) as error:
        msg = f"managed schema postcondition failed; transaction rolled back: {error}"
        raise PackageError(msg) from error
    if obstacle := removed_check_obstacle(package, objects):
        raise PackageError(obstacle)


def _part_signature(sql: str) -> tuple[str | None, tuple[tuple[str, str], ...]]:
    name = column_name(sql)
    # A bare column name and its quoted spelling designate the same identifier.
    # Other expressions remain conservative token comparisons, not guessed SQL
    # equivalence; strings, defaults and constraints keep their actual contents.
    tail = sql[tokens(sql)[0].end :] if name is not None else sql
    return name, _signature(tail)


def validate_adopted(package: Package, objects: list[tuple[Any, ...]]) -> None:
    """Prove bounded SQLite adoption against observation, without executing DDL."""
    for operation in package.draft.operations:
        if not isinstance(operation, AdoptTable):
            continue
        table = operation.table
        actual = next(
            (row[3] for row in objects if row[0] == "table" and row[1] == table.name),
            None,
        )
        if actual is None:
            msg = f"adoption requires an existing table {table.name!r}"
            raise PackageError(msg)
        try:
            _, expected_parts, expected_suffix = split_table(table.sql)
            _, actual_parts, actual_suffix = split_table(actual)
            differences = []
            expected = Counter(_part_signature(part) for part in expected_parts)
            observed = Counter(_part_signature(part) for part in actual_parts)
            if expected != observed:
                names = sorted(
                    {
                        name or "<table constraint>"
                        for name, _ in (*(expected - observed), *(observed - expected))
                    }
                )
                differences.append(
                    "column/constraint declarations: " + ", ".join(names)
                )
            if _signature(expected_suffix) != _signature(actual_suffix):
                differences.append("table storage options")
            if Counter(_index_signature(sql) for sql in table.indexes) != Counter(
                _index_signature(row[3])
                for row in objects
                if row[0] == "index" and row[2] == table.name and row[3] is not None
            ):
                differences.append("index declarations")
            if any(row[0] == "trigger" and row[2] == table.name for row in objects):
                differences.append("unmanaged triggers")
        except SchemaError as error:
            msg = f"{table.name}: adoption cannot interpret the observed definition"
            raise PackageError(msg) from error
        if differences:
            msg = f"{table.name}: adoption cannot accept " + "; ".join(differences)
            raise PackageError(msg)

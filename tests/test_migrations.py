"""Backend-neutral immutable Migration declaration and history tests."""

from __future__ import annotations

from snektest import assert_eq, assert_raises, test

from snekql._migrations import (
    MigrationRecord,
    prepare_migrations,
    validate_history_prefix,
    validate_legacy_history,
)
from snekql.errors import MigrationDeclarationError, MigrationHistoryError


@test(mark="fast")
def declaration_snapshot_preserves_order_sql_and_checksum() -> None:
    """Planning copies insertion order and hashes the exact UTF-8 body."""

    migrations = {"001_select": "SELECT 1"}
    plan = prepare_migrations(migrations)
    migrations["002_late"] = "SELECT 2"

    assert_eq(len(plan), 1)
    assert_eq(plan[0].position, 1)
    assert_eq(plan[0].name, "001_select")
    assert_eq(plan[0].sql, "SELECT 1")
    assert_eq(
        plan[0].checksum,
        "e004ebd5b5532a4b85984a62f8ad48a81aa3460c1ca07701f386135d72cdecf5",
    )


@test(mark="fast")
def declaration_rejects_invalid_names_and_bodies() -> None:
    """Migration identity and exact SQL must be stable UTF-8 built-in strings."""

    invalid_declarations: tuple[object, ...] = (
        [],
        {"": "SELECT 1"},
        {"x" * 256: "SELECT 1"},
        {"001": ""},
        {"001": "   "},
        {"001\x00": "SELECT 1"},
        {"001": "SELECT\x00 1"},
        {"001": "\ud800"},
    )
    for declaration in invalid_declarations:
        with assert_raises(MigrationDeclarationError):
            prepare_migrations(
                declaration  # ty: ignore[invalid-argument-type]
            )


@test(mark="fast")
def every_ordered_history_prefix_is_valid() -> None:
    """Migration accepts exactly each prefix of the complete declaration."""

    plan = prepare_migrations({"001": "SELECT 1", "002": "SELECT 2", "003": "SELECT 3"})
    records = tuple(migration.history_record() for migration in plan)

    for prefix_length in range(len(records) + 1):
        validate_history_prefix(records[:prefix_length], plan)


@test(mark="fast")
def divergent_ordered_history_is_rejected() -> None:
    """Holes, unknown names, body edits, and overlong history fail closed."""

    plan = prepare_migrations({"001": "SELECT 1", "002": "SELECT 2"})
    first, second = (migration.history_record() for migration in plan)
    divergent_histories = (
        (MigrationRecord(2, first.name, first.checksum),),
        (MigrationRecord(1, "unknown", first.checksum),),
        (MigrationRecord(1, first.name, "0" * 64),),
        (first, second, MigrationRecord(3, "003", "0" * 64)),
    )

    for history in divergent_histories:
        with assert_raises(MigrationHistoryError):
            validate_history_prefix(history, plan)


@test(mark="fast")
def full_head_verification_rejects_pending_history() -> None:
    """Read-only verification requires the declaration's complete head."""

    plan = prepare_migrations({"001": "SELECT 1", "002": "SELECT 2"})

    with assert_raises(MigrationHistoryError):
        validate_history_prefix(
            (plan[0].history_record(),),
            plan,
            require_head=True,
        )


@test(mark="fast")
def legacy_names_must_equal_one_declared_prefix_set() -> None:
    """Adoption rejects holes, unknown rows, and overlong legacy history."""

    plan = prepare_migrations({"001": "SELECT 1", "002": "SELECT 2"})
    assert_eq(validate_legacy_history({"001"}, plan), 1)

    for legacy_names in ({"002"}, {"unknown"}, {"001", "002", "003"}):
        with assert_raises(MigrationHistoryError):
            validate_legacy_history(legacy_names, plan)

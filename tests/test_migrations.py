"""Revision identity and declaration checks through the public database interface."""

from __future__ import annotations

from typing import Any

from snektest import assert_eq, assert_raises, test

from snekql import sqlite


@test(mark="fast")
async def applied_revision_identity_does_not_depend_on_function_code() -> None:
    """An edited function is not executed or rejected under an applied ID."""

    async def original(migration: sqlite.MigrationContext) -> None:
        await migration.execute("CREATE TABLE entry (id INTEGER) STRICT")

    async def changed(migration: sqlite.MigrationContext) -> None:
        _ = migration
        msg = "an applied revision must not run again"
        raise AssertionError(msg)

    async with await sqlite.Database.initialize(database=":memory:") as db:
        await db.migrate({"001": original})
        result = await db.migrate({"001": changed})
        assert_eq(result.already_applied, ("001",))
        await db.verify_migrations({"001": changed})


@test(mark="fast")
async def divergent_revision_chains_are_rejected() -> None:
    """Applied order, IDs, and the complete prefix remain authoritative."""

    async def noop(migration: sqlite.MigrationContext) -> None:
        pass

    async with await sqlite.Database.initialize(database=":memory:") as db:
        await db.migrate({"001": noop, "002": noop})
        for declaration in (
            {},
            {"001": noop},
            {"002": noop, "001": noop},
            {"001": noop, "unknown": noop},
        ):
            with assert_raises(sqlite.MigrationHistoryError):
                await db.migrate(declaration)
            with assert_raises(sqlite.MigrationHistoryError):
                await db.migration_status(declaration)


@test(mark="fast")
async def invalid_declarations_are_rejected_before_waiting_for_a_connection() -> None:
    """Names and async-function signatures are validated before database I/O."""

    async def noop(migration: sqlite.MigrationContext) -> None:
        pass

    async def missing_context() -> None:
        pass

    async def extra_argument(context: sqlite.MigrationContext, required: int) -> None:
        pass

    invalid: tuple[Any, ...] = (
        [],
        {"": noop},
        {"x" * 256: noop},
        {"nul\x00": noop},
        {"\ud800": noop},
        {"001": "SELECT 1"},
        {"001": missing_context},
        {"001": extra_argument},
        {"001": lambda _context: None},
    )
    async with (
        await sqlite.Database.initialize(database=":memory:", pool_size=1) as db,
        db.transaction(),
    ):
        for declaration in invalid:
            with assert_raises(sqlite.MigrationDeclarationError):
                await db.migrate(declaration)

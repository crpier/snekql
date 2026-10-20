"""Function migrations exercised through the public database interface."""

from __future__ import annotations

from pathlib import Path

import anyio
from snektest import assert_eq, assert_raises, test

from snekql import sqlite


@test(mark="fast")
async def pending_functions_execute_once_with_application_checks() -> None:
    """The runner executes application code only for pending revision IDs."""
    checks: list[str] = []

    async def create_todos(migration: sqlite.MigrationContext) -> None:
        checks.append("space checked")
        await migration.execute("CREATE TABLE todo (title TEXT NOT NULL) STRICT")
        await migration.execute("INSERT INTO todo VALUES (?)", params=("First",))
        assert_eq(await migration.fetch_all("SELECT title FROM todo"), [("First",)])

    async with await sqlite.Database.initialize(database=":memory:") as db:
        declaration = {"001_create": create_todos}
        result = await db.migrate(declaration)
        assert_eq(result.applied, ("001_create",))
        assert_eq((await db.migrate(declaration)).already_applied, ("001_create",))
        await db.verify_migrations(declaration)
        assert_eq((await db.migration_status(declaration)).pending, ())
    assert_eq(checks, ["space checked"])


@test(mark="fast")
async def failed_function_rolls_back_and_leaves_revision_pending() -> None:
    """Failure preserves earlier progress and retries only the failed revision."""
    attempts = 0

    async def first(migration: sqlite.MigrationContext) -> None:
        await migration.execute("CREATE TABLE item (value INTEGER NOT NULL) STRICT")

    async def second(migration: sqlite.MigrationContext) -> None:
        nonlocal attempts
        attempts += 1
        await migration.execute("INSERT INTO item VALUES (?)", params=(42,))
        if attempts == 1:
            msg = "application precondition failed"
            raise RuntimeError(msg)
        assert_eq(await migration.fetch_all("SELECT value FROM item"), [(42,)])

    async with await sqlite.Database.initialize(database=":memory:") as db:
        declaration = {"001": first, "002": second}
        with assert_raises(sqlite.MigrationError):
            await db.migrate(declaration)
        status = await db.migration_status(declaration)
        assert_eq(status.applied, ("001",))
        assert_eq(status.pending, ("002",))
        result = await db.migrate(declaration)
        assert_eq(result.applied, ("002",))
        await db.verify_migrations(declaration)


@test(mark="fast")
async def completed_context_cannot_be_used_again() -> None:
    """A retained context cannot execute after the runner records its revision."""
    retained: list[sqlite.MigrationContext] = []

    async def retain(migration: sqlite.MigrationContext) -> None:
        retained.append(migration)

    async with await sqlite.Database.initialize(database=":memory:") as db:
        await db.migrate({"001": retain})
        with assert_raises(sqlite.MigrationError):
            await retained[0].execute("SELECT 1")


@test(mark="fast")
async def migration_context_rejects_work_from_child_tasks() -> None:
    """A spawned task cannot outlive or concurrently use the managed context."""

    async def check(migration: sqlite.MigrationContext) -> None:
        async def child() -> None:
            with assert_raises(sqlite.MigrationError):
                await migration.execute("SELECT 1")

        async with anyio.create_task_group() as group:
            group.start_soon(child)

    async with await sqlite.Database.initialize(database=":memory:") as db:
        await db.migrate({"001": check})
        await db.verify_migrations({"001": check})


@test(mark="fast")
async def cancellation_expires_context_and_leaves_revision_pending() -> None:
    """Cancellation rolls back database work and never records an unfinished body."""
    entered = anyio.Event()
    contexts: list[sqlite.MigrationContext] = []

    async def unfinished(migration: sqlite.MigrationContext) -> None:
        contexts.append(migration)
        await migration.execute("CREATE TABLE unfinished (id INTEGER) STRICT")
        entered.set()
        await anyio.sleep_forever()

    async with await sqlite.Database.initialize(database=":memory:") as db:
        async with anyio.create_task_group() as group:
            group.start_soon(db.migrate, {"001": unfinished})
            await entered.wait()
            group.cancel_scope.cancel()
        assert_eq((await db.migration_status({"001": unfinished})).pending, ("001",))
        with assert_raises(sqlite.MigrationError):
            await contexts[0].execute("SELECT 1")


@test(mark="medium")
async def competing_runners_do_not_repeat_committed_function_checks() -> None:
    """Revision checks run once when competing runners share a file database."""
    checks: list[str] = []

    async def create(migration: sqlite.MigrationContext) -> None:
        checks.append("checked")
        await anyio.lowlevel.checkpoint()
        await migration.execute("CREATE TABLE entry (id INTEGER PRIMARY KEY) STRICT")

    async with (
        anyio.TemporaryDirectory() as directory,
        await sqlite.Database.initialize(database=Path(directory) / "app.db") as first,
        await sqlite.Database.initialize(database=Path(directory) / "app.db") as second,
    ):
        async with anyio.create_task_group() as group:
            group.start_soon(first.migrate, {"001": create})
            group.start_soon(second.migrate, {"001": create})
        await first.verify_migrations({"001": create})
    assert_eq(checks, ["checked"])

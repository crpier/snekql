"""Backend-neutral migration runner flow tests using a fake migration backend."""

from __future__ import annotations

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from snektest import assert_eq, assert_raises, assert_true, test

from snekql._migrations import run_migrations
from snekql.errors import MigrationError


class _RecordingStructuredLogger:
    """Structured logger fake that stores event calls for assertions."""

    def __init__(self) -> None:
        self.events: list[tuple[str, str, dict[str, object]]] = []

    def debug(self, event: str, **fields: object) -> None:
        self.events.append(("debug", event, fields))

    def info(self, event: str, **fields: object) -> None:
        self.events.append(("info", event, fields))

    def warning(self, event: str, **fields: object) -> None:
        self.events.append(("warning", event, fields))

    def error(self, event: str, **fields: object) -> None:
        self.events.append(("error", event, fields))


class _MigrationBodyError(Exception):
    """Raised by the fake backend to simulate a failing migration body."""


class _FakeMigrationBackend:
    """Migration backend fake that scripts applied names and records calls.

    Mirrors the schema-startup `_FakeSchemaBackend`: it answers what has been
    applied and records the ordered call sequence so flow tests can assert the
    runner ensures history, reads applied names, and applies pending bodies in
    insertion order with bookkeeping after each success.
    """

    def __init__(
        self,
        *,
        applied: set[str] | None = None,
        failing_body: str | None = None,
    ) -> None:
        self.calls: list[tuple[str, str | None]] = []
        self.applied: set[str] = applied or set()
        self.failing_body: str | None = failing_body

    @asynccontextmanager
    async def migration_lock(self) -> AsyncGenerator[None]:
        self.calls.append(("migration_lock_enter", None))
        try:
            yield
        finally:
            self.calls.append(("migration_lock_exit", None))

    async def ensure_history_table(self) -> None:
        self.calls.append(("ensure_history_table", None))

    async def fetch_applied_names(self) -> set[str]:
        self.calls.append(("fetch_applied_names", None))
        return set(self.applied)

    async def execute_migration_body(self, sql: str) -> None:
        self.calls.append(("execute_migration_body", sql))
        if sql == self.failing_body:
            raise _MigrationBodyError(sql)

    async def record_applied(self, name: str) -> None:
        self.calls.append(("record_applied", name))


@test(mark="fast")
async def pending_migrations_apply_in_insertion_order() -> None:
    """The runner ensures history, reads applied, then applies pending bodies in order."""

    backend = _FakeMigrationBackend()
    logger = _RecordingStructuredLogger()

    await run_migrations(
        backend,
        {
            "001_create_users": "CREATE TABLE users (id INTEGER)",
            "002_add_email": "ALTER TABLE users ADD COLUMN email TEXT",
        },
        logger=logger,
    )

    assert_eq(
        backend.calls,
        [
            ("migration_lock_enter", None),
            ("ensure_history_table", None),
            ("fetch_applied_names", None),
            ("execute_migration_body", "CREATE TABLE users (id INTEGER)"),
            ("record_applied", "001_create_users"),
            ("execute_migration_body", "ALTER TABLE users ADD COLUMN email TEXT"),
            ("record_applied", "002_add_email"),
            ("migration_lock_exit", None),
        ],
    )


@test(mark="fast")
async def already_applied_migrations_are_skipped() -> None:
    """A migration whose name is already in history is neither run nor re-recorded."""

    backend = _FakeMigrationBackend(applied={"001_create_users"})
    logger = _RecordingStructuredLogger()

    await run_migrations(
        backend,
        {
            "001_create_users": "CREATE TABLE users (id INTEGER)",
            "002_add_email": "ALTER TABLE users ADD COLUMN email TEXT",
        },
        logger=logger,
    )

    assert_true(
        ("execute_migration_body", "CREATE TABLE users (id INTEGER)")
        not in backend.calls
    )
    assert_true(("record_applied", "001_create_users") not in backend.calls)
    skipped = {"ensure_history_table", "migration_lock_enter", "migration_lock_exit"}
    assert_eq(
        [call for call in backend.calls if call[0] not in skipped],
        [
            ("fetch_applied_names", None),
            ("execute_migration_body", "ALTER TABLE users ADD COLUMN email TEXT"),
            ("record_applied", "002_add_email"),
        ],
    )


@test(mark="fast")
async def empty_migration_mapping_performs_no_backend_work() -> None:
    """An empty migration mapping touches the Migration History backend not at all."""

    backend = _FakeMigrationBackend()
    logger = _RecordingStructuredLogger()

    await run_migrations(backend, {}, logger=logger)

    assert_eq(backend.calls, [])


@test(mark="fast")
async def failing_migration_halts_and_keeps_prior_successes_recorded() -> None:
    """A failing body halts the run; earlier successes stay recorded, later ones never run."""

    failing_body = "ALTER TABLE users ADD COLUMN broken"
    backend = _FakeMigrationBackend(failing_body=failing_body)
    logger = _RecordingStructuredLogger()

    with assert_raises(MigrationError):
        await run_migrations(
            backend,
            {
                "001_create_users": "CREATE TABLE users (id INTEGER)",
                "002_break": failing_body,
                "003_after": "CREATE TABLE later (id INTEGER)",
            },
            logger=logger,
        )

    assert_true(("record_applied", "001_create_users") in backend.calls)
    assert_true(("record_applied", "002_break") not in backend.calls)
    assert_true(
        ("execute_migration_body", "CREATE TABLE later (id INTEGER)")
        not in backend.calls
    )


@test(mark="fast")
async def apply_flow_runs_inside_the_advisory_lock() -> None:
    """The lock is entered before any history work and exited only after the last."""

    backend = _FakeMigrationBackend()
    logger = _RecordingStructuredLogger()

    await run_migrations(
        backend,
        {"001_create_users": "CREATE TABLE users (id INTEGER)"},
        logger=logger,
    )

    assert_eq(backend.calls[0], ("migration_lock_enter", None))
    assert_eq(backend.calls[-1], ("migration_lock_exit", None))
    inner = backend.calls[1:-1]
    assert_true(("migration_lock_enter", None) not in inner)
    assert_true(("migration_lock_exit", None) not in inner)


@test(mark="fast")
async def failing_migration_still_releases_the_advisory_lock() -> None:
    """A body failure exits the lock so a fixed retry can re-acquire it."""

    failing_body = "ALTER TABLE users ADD COLUMN broken"
    backend = _FakeMigrationBackend(failing_body=failing_body)
    logger = _RecordingStructuredLogger()

    with assert_raises(MigrationError):
        await run_migrations(backend, {"001_break": failing_body}, logger=logger)

    assert_eq(backend.calls[-1], ("migration_lock_exit", None))

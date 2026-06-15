"""Backend-neutral schema startup flow tests using a fake schema backend."""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, Any, ClassVar

from snektest import assert_eq, assert_raises, assert_true, test

from snekql import (
    Fetched,
    Index,
    Integer,
    Model,
    Pending,
    SchemaVerificationError,
    Text,
)
from snekql._schema_startup import initialize_schema

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

    from snekql._schema_plan import PlannedModel
    from snekql.indexes import NormalizedIndex


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


class _FakeSchemaBackend:
    """Schema backend fake that scripts inspection answers and records calls."""

    def __init__(
        self,
        *,
        existing_tables: set[str] | None = None,
        matching_tables: set[str] | None = None,
        matching_indexes: set[str] | None = None,
    ) -> None:
        self.calls: list[tuple[str, str]] = []
        self.existing_tables: set[str] = existing_tables or set()
        self.matching_tables: set[str] = matching_tables or set()
        self.matching_indexes: set[str] = matching_indexes or set()
        self.transaction_events: list[str] = []

    @asynccontextmanager
    async def startup_transaction(self) -> AsyncGenerator[None]:
        self.transaction_events.append("enter")
        try:
            yield
        finally:
            self.transaction_events.append("exit")

    async def table_exists(self, table_name: str) -> bool:
        self.calls.append(("table_exists", table_name))
        return table_name in self.existing_tables

    async def table_matches(self, planned_model: PlannedModel) -> bool:
        self.calls.append(("table_matches", planned_model.table_name))
        return planned_model.table_name in self.matching_tables

    async def indexes_match(self, planned_model: PlannedModel) -> bool:
        self.calls.append(("indexes_match", planned_model.table_name))
        return planned_model.table_name in self.matching_indexes

    async def create_table(self, planned_model: PlannedModel) -> None:
        self.calls.append(("create_table", planned_model.table_name))

    async def create_index(self, table_name: str, index: NormalizedIndex) -> str:
        _ = table_name
        self.calls.append(("create_index", index.name))
        return f"CREATE INDEX {index.name}"


class User[S = Pending](Model[S, "User[Fetched]"]):
    """Table model with one index used by schema startup flow tests."""

    id: User.GenCol[int] = Integer(primary_key=True, auto_increment=True)
    email: User.Col[str] = Text(nullable=False)
    __indexes__: ClassVar[list[Index[Any]]] = [
        Index(email, name="ix_user_email"),
    ]


@test(mark="fast")
async def missing_tables_are_created_with_their_indexes() -> None:
    """Schema startup creates absent tables and their indexes inside the startup transaction."""

    backend = _FakeSchemaBackend()
    logger = _RecordingStructuredLogger()

    await initialize_schema(backend, [User], "strict", logger=logger)

    assert_eq(
        backend.calls,
        [
            ("table_exists", "user"),
            ("create_table", "user"),
            ("create_index", "ix_user_email"),
        ],
    )
    assert_eq(backend.transaction_events, ["enter", "exit"])
    created_events = [event for _, event, _ in logger.events]
    assert_true("schema table created" in created_events)
    assert_true("schema index created" in created_events)


@test(mark="fast")
async def strict_schema_policy_raises_on_table_drift() -> None:
    """Table drift under the strict schema policy fails startup before index checks."""

    backend = _FakeSchemaBackend(existing_tables={"user"})
    logger = _RecordingStructuredLogger()

    with assert_raises(SchemaVerificationError):
        await initialize_schema(backend, [User], "strict", logger=logger)

    assert_true(("indexes_match", "user") not in backend.calls)
    assert_eq(backend.transaction_events, ["enter", "exit"])


@test(mark="fast")
async def warn_schema_policy_logs_drift_and_continues() -> None:
    """Table drift under the warn schema policy logs a warning and completes startup."""

    backend = _FakeSchemaBackend(existing_tables={"user"})
    logger = _RecordingStructuredLogger()

    await initialize_schema(backend, [User], "warn", logger=logger)

    warnings = [event for level, event, _ in logger.events if level == "warning"]
    assert_eq(warnings, ["schema drift detected"])
    completed_events = [event for _, event, _ in logger.events]
    assert_true("schema startup completed" in completed_events)


@test(mark="fast")
async def index_drift_is_reported_after_table_verification() -> None:
    """Index drift on a verified table reports schema drift under the active policy."""

    backend = _FakeSchemaBackend(
        existing_tables={"user"},
        matching_tables={"user"},
    )
    logger = _RecordingStructuredLogger()

    with assert_raises(SchemaVerificationError):
        await initialize_schema(backend, [User], "strict", logger=logger)

    assert_true(("indexes_match", "user") in backend.calls)
    verified_events = [event for _, event, _ in logger.events]
    assert_true("schema table verified" in verified_events)


@test(mark="fast")
async def matching_schema_is_verified_without_mutation() -> None:
    """A fully matching live schema verifies tables and indexes without DDL."""

    backend = _FakeSchemaBackend(
        existing_tables={"user"},
        matching_tables={"user"},
        matching_indexes={"user"},
    )
    logger = _RecordingStructuredLogger()

    await initialize_schema(backend, [User], "strict", logger=logger)

    call_names = [name for name, _ in backend.calls]
    assert_true("create_table" not in call_names)
    assert_true("create_index" not in call_names)
    verified_events = [event for _, event, _ in logger.events]
    assert_true("schema table verified" in verified_events)
    assert_true("schema indexes verified" in verified_events)


@test(mark="fast")
async def verify_only_startup_reports_missing_table_as_drift() -> None:
    """With create_missing=False a missing table is drift, not auto-created."""

    backend = _FakeSchemaBackend()
    logger = _RecordingStructuredLogger()

    with assert_raises(SchemaVerificationError):
        await initialize_schema(
            backend, [User], "strict", logger=logger, create_missing=False
        )

    call_names = [name for name, _ in backend.calls]
    assert_true("create_table" not in call_names)


@test(mark="fast")
async def verify_only_startup_verifies_existing_table_without_creating() -> None:
    """With create_missing=False an existing matching table is verified, never created."""

    backend = _FakeSchemaBackend(
        existing_tables={"user"},
        matching_tables={"user"},
        matching_indexes={"user"},
    )
    logger = _RecordingStructuredLogger()

    await initialize_schema(
        backend, [User], "strict", logger=logger, create_missing=False
    )

    call_names = [name for name, _ in backend.calls]
    assert_true("create_table" not in call_names)
    verified_events = [event for _, event, _ in logger.events]
    assert_true("schema table verified" in verified_events)


@test(mark="fast")
async def empty_model_list_skips_schema_startup() -> None:
    """Schema startup with no models performs no backend work."""

    backend = _FakeSchemaBackend()
    logger = _RecordingStructuredLogger()

    await initialize_schema(backend, [], "strict", logger=logger)

    assert_eq(backend.calls, [])
    assert_eq(backend.transaction_events, [])
    assert_eq(logger.events, [])

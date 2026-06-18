"""Backend-neutral schema startup flow tests using a fake schema backend."""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, Any, ClassVar, cast

from snektest import assert_eq, assert_raises, assert_true, test

from snekql._schema_shape import ColumnShape, IndexShape, TableShape
from snekql._schema_startup import initialize_schema
from snekql.sqlite import (
    Fetched,
    Index,
    Integer,
    Model,
    Pending,
    SchemaVerificationError,
    Text,
)

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


_USER_SHAPE = TableShape(
    table_name="user",
    columns=(
        ColumnShape(
            name="id",
            storage_type="INTEGER",
            nullable=True,
            primary_key=True,
            auto_increment=True,
            has_server_default=False,
            collation=None,
        ),
        ColumnShape(
            name="email",
            storage_type="TEXT",
            nullable=False,
            primary_key=False,
            auto_increment=False,
            has_server_default=False,
            collation=None,
        ),
    ),
    indexes=(IndexShape(name="ix_user_email", column_names=("email",), unique=False),),
    foreign_keys=(),
    storage_options=("STRICT",),
)


class _FakeSchemaBackend:
    """Schema backend fake scripting expected/actual shapes and recording calls.

    ``expected`` is the model-derived shape the flow diffs against; ``actual``
    maps table names to the live shape (a missing key means the table is absent).
    """

    def __init__(
        self,
        *,
        expected: TableShape = _USER_SHAPE,
        actual: dict[str, TableShape] | None = None,
    ) -> None:
        self.calls: list[tuple[str, str]] = []
        self.expected: TableShape = expected
        self.actual: dict[str, TableShape] = actual or {}
        self.transaction_events: list[str] = []

    @asynccontextmanager
    async def startup_transaction(self) -> AsyncGenerator[None]:
        self.transaction_events.append("enter")
        try:
            yield
        finally:
            self.transaction_events.append("exit")

    def expected_shape(self, planned_model: PlannedModel) -> TableShape:
        self.calls.append(("expected_shape", planned_model.table_name))
        return self.expected

    async def inspect_shape(self, planned_model: PlannedModel) -> TableShape | None:
        self.calls.append(("inspect_shape", planned_model.table_name))
        return self.actual.get(planned_model.table_name)

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


def _drifted_user_shape() -> TableShape:
    """A live shape that diverges from the expected user shape on one index."""

    return TableShape(
        table_name="user",
        columns=_USER_SHAPE.columns,
        indexes=(
            IndexShape(name="ix_user_email", column_names=("email",), unique=True),
        ),
        foreign_keys=(),
        storage_options=("STRICT",),
    )


@test(mark="fast")
async def missing_tables_are_created_with_their_indexes() -> None:
    """Schema startup creates absent tables and their indexes inside the startup transaction."""

    backend = _FakeSchemaBackend()
    logger = _RecordingStructuredLogger()

    await initialize_schema(backend, [User], "strict", logger=logger)

    assert_eq(
        backend.calls,
        [
            ("inspect_shape", "user"),
            ("create_table", "user"),
            ("create_index", "ix_user_email"),
        ],
    )
    assert_eq(backend.transaction_events, ["enter", "exit"])
    created_events = [event for _, event, _ in logger.events]
    assert_true("schema table created" in created_events)
    assert_true("schema index created" in created_events)


@test(mark="fast")
async def strict_schema_policy_raises_on_drift() -> None:
    """A live shape that diverges from the model fails startup under strict policy."""

    backend = _FakeSchemaBackend(actual={"user": _drifted_user_shape()})
    logger = _RecordingStructuredLogger()

    with assert_raises(SchemaVerificationError):
        await initialize_schema(backend, [User], "strict", logger=logger)

    assert_eq(backend.transaction_events, ["enter", "exit"])


@test(mark="fast")
async def strict_drift_error_names_the_divergent_index() -> None:
    """Strict drift raises an error message naming the specific index that diverged."""

    backend = _FakeSchemaBackend(actual={"user": _drifted_user_shape()})
    logger = _RecordingStructuredLogger()

    with assert_raises(SchemaVerificationError) as raised:
        await initialize_schema(backend, [User], "strict", logger=logger)

    message = str(raised.exception)
    assert_true("user" in message)
    assert_true("ix_user_email" in message)
    assert_true("uniqueness" in message)


@test(mark="fast")
async def warn_schema_policy_logs_drift_and_continues() -> None:
    """Drift under the warn schema policy logs a warning with issues and completes startup."""

    backend = _FakeSchemaBackend(actual={"user": _drifted_user_shape()})
    logger = _RecordingStructuredLogger()

    await initialize_schema(backend, [User], "warn", logger=logger)

    warnings = [
        (event, fields) for level, event, fields in logger.events if level == "warning"
    ]
    assert_eq([event for event, _ in warnings], ["schema drift detected"])
    issues = warnings[0][1]["issues"]
    assert_true(isinstance(issues, list))
    assert_eq(len(cast("list[object]", issues)), 1)
    completed_events = [event for _, event, _ in logger.events]
    assert_true("schema startup completed" in completed_events)


@test(mark="fast")
async def matching_schema_is_verified_without_mutation() -> None:
    """A fully matching live schema verifies tables and indexes without DDL."""

    backend = _FakeSchemaBackend(actual={"user": _USER_SHAPE})
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

    backend = _FakeSchemaBackend(actual={"user": _USER_SHAPE})
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

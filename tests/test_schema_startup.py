"""Backend-neutral schema verification flow tests using a fake schema backend."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, Any, ClassVar

from snektest import assert_eq, assert_raises, assert_true, test

from snekql._schema_shape import ColumnShape, IndexShape, TableShape
from snekql._schema_startup import verify_schema
from snekql.sqlite import (
    Fetched,
    Index,
    Integer,
    Model,
    Pending,
    SchemaVerificationError,
    Text,
)
from tests.helpers import capture_snekql_logs

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

    from snekql._schema_plan import PlannedModel


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
    async def verification_transaction(self) -> AsyncGenerator[None]:
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


class User[S = Pending](Model[S, "User[Fetched]"]):
    """Table model with one index used by schema verification flow tests."""

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
async def missing_table_is_reported_as_drift() -> None:
    """A model whose table is absent is drift under strict, never created."""

    backend = _FakeSchemaBackend()

    with assert_raises(SchemaVerificationError) as raised:
        await verify_schema(backend, [User], "strict")

    assert_eq(backend.transaction_events, ["enter", "exit"])
    message = str(raised.exception)
    assert_true("user" in message)
    assert_true("missing" in message)


@test(mark="fast")
async def missing_table_under_warn_logs_drift_and_continues() -> None:
    """A missing table under warn logs drift rather than raising."""

    backend = _FakeSchemaBackend()

    with capture_snekql_logs() as logs:
        await verify_schema(backend, [User], "warn")

    drift_warnings = [
        message
        for message in logs.messages(logging.WARNING)
        if "schema drift detected" in message
    ]
    assert_eq(len(drift_warnings), 1)
    assert_true("missing" in drift_warnings[0])


@test(mark="fast")
async def strict_schema_policy_raises_on_drift() -> None:
    """A live shape that diverges from the model fails under strict policy."""

    backend = _FakeSchemaBackend(actual={"user": _drifted_user_shape()})

    with assert_raises(SchemaVerificationError):
        await verify_schema(backend, [User], "strict")

    assert_eq(backend.transaction_events, ["enter", "exit"])


@test(mark="fast")
async def strict_drift_error_names_the_divergent_index() -> None:
    """Strict drift raises an error message naming the specific index that diverged."""

    backend = _FakeSchemaBackend(actual={"user": _drifted_user_shape()})

    with assert_raises(SchemaVerificationError) as raised:
        await verify_schema(backend, [User], "strict")

    message = str(raised.exception)
    assert_true("user" in message)
    assert_true("ix_user_email" in message)
    assert_true("uniqueness" in message)


@test(mark="fast")
async def warn_schema_policy_logs_drift_and_continues() -> None:
    """Drift under the warn schema policy logs a warning with issues and completes."""

    backend = _FakeSchemaBackend(actual={"user": _drifted_user_shape()})

    with capture_snekql_logs() as logs:
        await verify_schema(backend, [User], "warn")

    drift_warnings = [
        message
        for message in logs.messages(logging.WARNING)
        if "schema drift detected" in message
    ]
    assert_eq(len(drift_warnings), 1)
    assert_true("'user'" in drift_warnings[0])
    assert_true(logs.has(logging.DEBUG, "schema verification completed"))


@test(mark="fast")
async def matching_schema_is_verified_without_mutation() -> None:
    """A fully matching live schema verifies tables and indexes without any DDL."""

    backend = _FakeSchemaBackend(actual={"user": _USER_SHAPE})

    with capture_snekql_logs() as logs:
        await verify_schema(backend, [User], "strict")

    assert_true(logs.has(logging.DEBUG, "schema table and indexes for 'user' verified"))


@test(mark="fast")
async def empty_model_list_skips_schema_verification() -> None:
    """Schema verification with no models performs no backend work."""

    backend = _FakeSchemaBackend()

    with capture_snekql_logs() as logs:
        await verify_schema(backend, [], "strict")

    assert_eq(backend.calls, [])
    assert_eq(backend.transaction_events, [])
    assert_eq(logs.records, [])

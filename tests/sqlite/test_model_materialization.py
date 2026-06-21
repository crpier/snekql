"""SQLite Table Model materialization tests."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import cast

from pydantic import Json, PositiveInt
from snektest import assert_eq, assert_raises, test

from snekql._model_materialization import decode_model_row, encode_model_row
from snekql.sqlite import (
    Fetched,
    Integer,
    Model,
    ModelValidationError,
    Pending,
    Text,
)


@test(mark="fast")
def sqlite_model_materialization_uses_one_backend_codec_path() -> None:
    """SQLite Pending/Fetched Model conversion is handled by the materializer."""

    class Event[S = Pending](Model[S, "Event[Fetched]"]):
        """SQLite model used by materialization seam tests."""

        enabled: Event.Col[bool] = Integer(nullable=False)
        happened_at: Event.Col[datetime] = Text(nullable=False)
        payload: Event.Col[Json[dict[str, object]]] = Text(nullable=False)

    timestamp = datetime(2026, 1, 2, 3, 4, 5, 678901, tzinfo=UTC)
    pending_event = Event(
        enabled=True,
        happened_at=timestamp,
        payload={"ok": True},
    )
    model_class, encoded_row = encode_model_row(pending_event, backend="sqlite")
    fetched_event = cast(
        "Event[Fetched]",
        decode_model_row(
            Event,
            {
                "enabled": 0,
                "happened_at": "2026-01-02T03:04:05.678901Z",
                "payload": '{"ok":true}',
            },
            backend="sqlite",
        ),
    )

    assert_eq(model_class, Event)
    assert_eq(
        encoded_row,
        {
            "enabled": 1,
            "happened_at": "2026-01-02T03:04:05.678901Z",
            "payload": '{"ok":true}',
        },
    )
    assert_eq(fetched_event.enabled, False)
    assert_eq(
        fetched_event.happened_at, datetime(2026, 1, 2, 3, 4, 5, 678901, tzinfo=UTC)
    )
    assert_eq(fetched_event.payload, {"ok": True})


@test(mark="fast")
def sqlite_model_materialization_asserts_database_row_shape() -> None:
    """SQLite model materialization treats row-shape mismatch as invariant failure."""

    class Event[S = Pending](Model[S, "Event[Fetched]"]):
        """SQLite model used by row-shape checks."""

        enabled: Event.Col[bool] = Integer(nullable=False)

    with assert_raises(AssertionError):
        _ = decode_model_row(Event, {}, backend="sqlite")

    with assert_raises(AssertionError):
        _ = decode_model_row(Event, {"enabled": 1, "extra": 2}, backend="sqlite")


@test(mark="fast")
def sqlite_model_materialization_validates_logical_types() -> None:
    """Materialization validates wire-decoded values against the logical type."""

    class Receipt[S = Pending](Model[S, "Receipt[Fetched]"]):
        """SQLite model with a constrained logical type."""

        amount: Receipt.Col[PositiveInt] = Integer(nullable=False)

    with assert_raises(ModelValidationError):
        _ = decode_model_row(Receipt, {"amount": -5}, backend="sqlite")


@test(mark="fast")
def sqlite_model_materialization_can_skip_validation() -> None:
    """Passing validate=False materializes the wire-decoded value unchecked."""

    class Receipt[S = Pending](Model[S, "Receipt[Fetched]"]):
        """SQLite model with a constrained logical type."""

        amount: Receipt.Col[PositiveInt] = Integer(nullable=False)

    fetched = cast(
        "Receipt[Fetched]",
        decode_model_row(Receipt, {"amount": -5}, backend="sqlite", validate=False),
    )

    assert_eq(fetched.amount, -5)

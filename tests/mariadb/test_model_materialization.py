"""MariaDB Table Model materialization tests."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import cast

from snektest import assert_eq, assert_raises, test

from snekql import ModelValidationError, Pending, mariadb
from snekql._model_materialization import decode_model_row, encode_model_row


@test(mark="fast")
def mariadb_model_materialization_uses_one_backend_codec_path() -> None:
    """MariaDB Pending/Fetched Model conversion is handled by the materializer."""

    class Event[S = Pending](mariadb.Model[S, "Event[object]"]):
        """MariaDB model used by materialization seam tests."""

        enabled: Event.Col[bool] = mariadb.Boolean(nullable=False)
        happened_at: Event.Col[datetime] = mariadb.DateTime(nullable=False)
        payload: Event.Col[dict[str, object]] = mariadb.Json(nullable=False)

    timestamp = datetime(2026, 1, 2, 3, 4, 5, 678901, tzinfo=UTC)
    pending_event = Event(
        enabled=True,
        happened_at=timestamp,
        payload={"ok": True},
    )
    model_class, encoded_row = encode_model_row(pending_event, backend="mariadb")
    fetched_event = cast(
        "Event[object]",
        decode_model_row(
            Event,
            {
                "enabled": 0,
                "happened_at": "2026-01-02 03:04:05.678",
                "payload": b'{"ok":true}',
            },
            backend="mariadb",
        ),
    )

    assert_eq(model_class, Event)
    assert_eq(
        encoded_row,
        {
            "enabled": 1,
            "happened_at": "2026-01-02 03:04:05.678",
            "payload": '{"ok":true}',
        },
    )
    assert_eq(fetched_event.enabled, False)
    assert_eq(
        fetched_event.happened_at, datetime(2026, 1, 2, 3, 4, 5, 678000, tzinfo=UTC)
    )
    assert_eq(fetched_event.payload, {"ok": True})


@test(mark="fast")
def mariadb_model_materialization_validates_database_row_shape() -> None:
    """Fetched Model materialization reports missing or extra database columns."""

    class Event[S = Pending](mariadb.Model[S, "Event[object]"]):
        """MariaDB model used by row-shape checks."""

        enabled: Event.Col[bool] = mariadb.Boolean(nullable=False)

    with assert_raises(ModelValidationError):
        _ = decode_model_row(Event, {}, backend="mariadb")

    with assert_raises(ModelValidationError):
        _ = decode_model_row(Event, {"enabled": 1, "extra": 2}, backend="mariadb")

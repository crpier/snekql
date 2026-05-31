"""SQLite storage type and value codec tests."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timezone, timedelta
from typing import cast

from snektest import assert_eq, assert_false, assert_raises, assert_true, test

import snekql
from snekql import (
    MISSING,
    Blob,
    Boolean,
    CurrentTimestamp,
    DateTime,
    Integer,
    Json,
    Model,
    ModelDeclarationError,
    ModelValidationError,
    Pending,
    Real,
    Text,
)


@test()
def v1_exposes_only_sqlite_first_storage_classes() -> None:
    """Text has no length option and Varchar is not a v1 storage class."""

    text_constructor = cast(Callable[..., object], Text)

    assert_false(hasattr(snekql, "Varchar"))
    with assert_raises(TypeError):
        _ = text_constructor(length=255)


@test()
def storage_classes_expose_sqlite_metadata() -> None:
    """V1 columns record the SQLite storage class used for schema generation."""

    class StorageExample[S = Pending](Model[S, "StorageExample[object]"]):
        """Table model using every v1 storage class."""

        integer_value: StorageExample.Col[int] = Integer(nullable=False)
        real_value: StorageExample.Col[float] = Real(nullable=False)
        text_value: StorageExample.Col[str] = Text(nullable=False)
        blob_value: StorageExample.Col[bytes] = Blob(nullable=False)
        json_value: StorageExample.Col[dict[str, object]] = Json(nullable=False)
        boolean_value: StorageExample.Col[bool] = Boolean(nullable=False)
        datetime_value: StorageExample.Col[object] = DateTime(nullable=False)

    columns = StorageExample.__snekql_columns__

    assert_eq(columns["integer_value"].sqlite_storage_class, "INTEGER")
    assert_eq(columns["real_value"].sqlite_storage_class, "REAL")
    assert_eq(columns["text_value"].sqlite_storage_class, "TEXT")
    assert_eq(columns["blob_value"].sqlite_storage_class, "BLOB")
    assert_eq(columns["json_value"].sqlite_storage_class, "TEXT")
    assert_eq(columns["boolean_value"].sqlite_storage_class, "INTEGER")
    assert_eq(columns["datetime_value"].sqlite_storage_class, "TEXT")


@test()
def boolean_values_encode_to_integer_and_decode_before_validation() -> None:
    """Boolean columns use INTEGER storage while models expose bools."""

    class FeatureFlag[S = Pending](Model[S, "FeatureFlag[object]"]):
        """Table model with a boolean flag."""

        enabled: FeatureFlag.Col[bool] = Boolean(nullable=False)

    enabled = FeatureFlag(enabled=True)
    from_row = cast(
        Callable[[dict[str, object]], FeatureFlag[object]],
        getattr(FeatureFlag, "_snekql_from_row"),
    )
    to_row = cast(
        Callable[[], dict[str, object]],
        getattr(enabled, "_snekql_to_row"),
    )
    disabled = from_row({"enabled": 0})

    assert_eq(to_row(), {"enabled": 1})
    assert_false(disabled.enabled)

    with assert_raises(ModelValidationError):
        _ = from_row({"enabled": 2})


@test()
def json_values_encode_to_text_and_decode_before_validation() -> None:
    """Json columns store JSON text and expose decoded Python values."""

    class Event[S = Pending](Model[S, "Event[object]"]):
        """Table model with a JSON payload."""

        payload: Event.Col[dict[str, object]] = Json(nullable=False)

    event = Event(payload={"kind": "created", "count": 2})
    from_row = cast(
        Callable[[dict[str, object]], Event[object]],
        getattr(Event, "_snekql_from_row"),
    )
    to_row = cast(
        Callable[[], dict[str, object]],
        getattr(event, "_snekql_to_row"),
    )
    fetched = from_row({"payload": '{"kind":"created","count":2}'})

    assert_eq(to_row(), {"payload": '{"kind":"created","count":2}'})
    assert_eq(fetched.payload, {"kind": "created", "count": 2})

    with assert_raises(ModelValidationError):
        _ = Event(payload={"bad": {object()}})

    with assert_raises(ModelValidationError):
        _ = from_row({"payload": "not json"})


@test()
def datetime_values_are_utc_millisecond_text() -> None:
    """DateTime accepts aware values and stores UTC millisecond text."""

    class AuditLog[S = Pending](Model[S, "AuditLog[object]"]):
        """Table model with a timestamp."""

        created_at: AuditLog.Col[datetime] = DateTime(nullable=False)

    source_timezone = timezone(timedelta(hours=5, minutes=30))
    source = datetime(2026, 5, 31, 12, 0, 1, 987654, tzinfo=source_timezone)
    audit_log = AuditLog(created_at=source)
    from_row = cast(
        Callable[[dict[str, object]], AuditLog[object]],
        getattr(AuditLog, "_snekql_from_row"),
    )
    to_row = cast(
        Callable[[], dict[str, object]],
        getattr(audit_log, "_snekql_to_row"),
    )
    fetched = from_row({"created_at": "2026-05-31T06:30:01.987Z"})

    expected = datetime(2026, 5, 31, 6, 30, 1, 987000, tzinfo=UTC)
    assert_eq(audit_log.created_at, expected)
    assert_eq(to_row(), {"created_at": "2026-05-31T06:30:01.987Z"})
    assert_eq(fetched.created_at, expected)

    with assert_raises(ModelValidationError):
        _ = AuditLog(created_at=datetime(2026, 5, 31, 12, 0, 1))


@test()
def external_value_failures_are_wrapped_in_model_validation_error() -> None:
    """Default factories and codecs do not leak third-party exceptions."""

    def broken_default() -> object:
        raise ValueError("outside validation failure")

    class ExternalValue[S = Pending](Model[S, "ExternalValue[object]"]):
        """Table model with an external default provider."""

        payload: ExternalValue.Col[object] = Json(default_factory=broken_default)

    with assert_raises(ModelValidationError):
        _ = ExternalValue()


@test()
def current_timestamp_is_valid_only_for_datetime_generated_columns() -> None:
    """Server timestamp defaults are limited to generated DateTime fields."""

    class CreatedEvent[S = Pending](Model[S, "CreatedEvent[object]"]):
        """Valid generated timestamp column."""

        created_at: CreatedEvent.GenCol[datetime] = DateTime(
            server_default=CurrentTimestamp(),
            default=MISSING,
        )

    assert_true(
        isinstance(
            CreatedEvent.__snekql_columns__["created_at"].server_default,
            CurrentTimestamp,
        ),
    )

    with assert_raises(ModelDeclarationError):

        class NonGeneratedTimestamp[S = Pending](
            Model[S, "NonGeneratedTimestamp[object]"]
        ):
            """Invalid non-generated timestamp default."""

            created_at: NonGeneratedTimestamp.Col[datetime] = DateTime(
                server_default=CurrentTimestamp(),
                default=MISSING,
            )

    with assert_raises(ModelDeclarationError):

        class NonDateTimeTimestamp[S = Pending](
            Model[S, "NonDateTimeTimestamp[object]"]
        ):
            """Invalid CurrentTimestamp use outside a DateTime server default."""

            created_at: NonDateTimeTimestamp.GenCol[datetime] = Text(
                default=CurrentTimestamp(),
            )

    with assert_raises(ModelDeclarationError):

        class TimestampWithPythonDefault[S = Pending](
            Model[S, "TimestampWithPythonDefault[object]"],
        ):
            """Invalid server default paired with a Python default."""

            created_at: TimestampWithPythonDefault.GenCol[datetime] = DateTime(
                server_default=CurrentTimestamp(),
                default=datetime(2026, 5, 31, tzinfo=UTC),
            )

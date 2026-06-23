"""SQLite storage type and value codec tests."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta, timezone
from typing import cast

from pydantic import BaseModel, Json
from snektest import assert_eq, assert_false, assert_raises, assert_true, test

import snekql
from snekql._model_materialization import decode_model_row, encode_model_row
from snekql.sqlite import (
    MISSING,
    Blob,
    CurrentTimestamp,
    Fetched,
    Integer,
    Model,
    ModelDeclarationError,
    ModelValidationError,
    Pending,
    QueryConstructionError,
    Real,
    Text,
)


@test()
def v1_exposes_only_sqlite_first_storage_classes() -> None:
    """Text has no length option and Varchar is not a v1 storage class."""

    assert_false(hasattr(snekql, "Varchar"))
    with assert_raises(TypeError):
        _ = Text()(length=255)


@test()
def storage_classes_expose_sqlite_metadata() -> None:
    """Column Types map to the four SQLite storage classes; the Logical Type
    (the annotation) decides the Python value, not the constructor."""

    class StorageExample[S = Pending](Model[S, "StorageExample[Fetched]"]):
        """Table model pairing each storage class with a logical type."""

        integer_value: StorageExample.Col[int] = Integer(nullable=False)
        real_value: StorageExample.Col[float] = Real(nullable=False)
        text_value: StorageExample.Col[str] = Text(nullable=False)
        blob_value: StorageExample.Col[bytes] = Blob(nullable=False)
        json_value: StorageExample.Col[Json[dict[str, object]]] = Text(nullable=False)
        boolean_value: StorageExample.Col[bool] = Integer(nullable=False)
        datetime_value: StorageExample.Col[datetime] = Text(nullable=False)

    columns = StorageExample.__snekql_columns__

    assert_eq(columns["integer_value"].sqlite_storage_class, "INTEGER")
    assert_eq(columns["real_value"].sqlite_storage_class, "REAL")
    assert_eq(columns["text_value"].sqlite_storage_class, "TEXT")
    assert_eq(columns["blob_value"].sqlite_storage_class, "BLOB")
    assert_eq(columns["json_value"].sqlite_storage_class, "TEXT")
    assert_eq(columns["boolean_value"].sqlite_storage_class, "INTEGER")
    assert_eq(columns["datetime_value"].sqlite_storage_class, "TEXT")


@test()
def bool_logical_type_encodes_to_integer_and_decodes_before_validation() -> None:
    """A ``Col[bool]`` over ``Integer()`` stores 0/1 while the model holds bools."""

    class FeatureFlag[S = Pending](Model[S, "FeatureFlag[Fetched]"]):
        """Table model with a boolean flag stored as INTEGER."""

        enabled: FeatureFlag.Col[bool] = Integer(nullable=False)

    enabled = FeatureFlag(enabled=True)
    disabled = cast(
        "FeatureFlag[Fetched]",
        decode_model_row(FeatureFlag, {"enabled": 0}, backend="sqlite"),
    )
    _, encoded_enabled = encode_model_row(enabled, backend="sqlite")

    # pydantic serializes a bool as ``True``/``False``; SQLite's INTEGER affinity
    # stores those as 1/0 (``True == 1``).
    assert_eq(encoded_enabled, {"enabled": 1})
    assert_false(disabled.enabled)

    with assert_raises(ModelValidationError):
        _ = decode_model_row(FeatureFlag, {"enabled": 2}, backend="sqlite")


@test()
def json_marker_encodes_to_text_and_decodes_before_validation() -> None:
    """A ``Col[Json[T]]`` over ``Text()`` stores JSON text and exposes decoded
    Python values; the marker selects the JSON wire codec, ``T`` drives
    validation."""

    class Event[S = Pending](Model[S, "Event[Fetched]"]):
        """Table model with a JSON payload stored as TEXT."""

        payload: Event.Col[Json[dict[str, object]]] = Text(nullable=False)

    event = Event(payload={"kind": "created", "count": 2})
    fetched = cast(
        "Event[Fetched]",
        decode_model_row(
            Event, {"payload": '{"kind":"created","count":2}'}, backend="sqlite"
        ),
    )
    _, encoded_event = encode_model_row(event, backend="sqlite")

    assert_eq(encoded_event, {"payload": '{"kind":"created","count":2}'})
    assert_eq(fetched.payload, {"kind": "created", "count": 2})

    # Logical validation checks the annotated shape (dict[str, object]); JSON
    # serializability is a wire-codec concern, so a non-serializable value is
    # accepted at construction and rejected only when encoded for storage.
    not_serializable = Event(payload={"bad": {object()}})
    with assert_raises(ModelValidationError):
        _ = encode_model_row(not_serializable, backend="sqlite")

    with assert_raises(ModelValidationError):
        _ = decode_model_row(Event, {"payload": "not json"}, backend="sqlite")


@test()
def json_marker_round_trips_rich_annotated_types() -> None:
    """``Json[T]`` encode/decode route through the column's pydantic adapter, so
    any type the annotation can validate also serializes and round-trips."""

    class Inner(BaseModel):
        x: int

    class ModelEvent[S = Pending](Model[S, "ModelEvent[Fetched]"]):
        """Json column annotated with a pydantic model."""

        payload: ModelEvent.Col[Json[Inner]] = Text(nullable=False)

    model_event = ModelEvent(payload=Inner(x=1))
    _, encoded_model = encode_model_row(model_event, backend="sqlite")
    assert_eq(encoded_model, {"payload": '{"x":1}'})
    fetched_model = cast(
        "ModelEvent[Fetched]",
        decode_model_row(ModelEvent, {"payload": '{"x":1}'}, backend="sqlite"),
    )
    assert_eq(fetched_model.payload, Inner(x=1))

    class WhenEvent[S = Pending](Model[S, "WhenEvent[Fetched]"]):
        """Json column annotated with a datetime."""

        when: WhenEvent.Col[Json[datetime]] = Text(nullable=False)

    moment = datetime(2026, 5, 31, 6, 30, 1, 987000, tzinfo=UTC)
    when_event = WhenEvent(when=moment)
    _, encoded_when = encode_model_row(when_event, backend="sqlite")
    assert_eq(encoded_when, {"when": '"2026-05-31T06:30:01.987000Z"'})
    fetched_when = cast(
        "WhenEvent[Fetched]",
        decode_model_row(
            WhenEvent, {"when": '"2026-05-31T06:30:01.987000Z"'}, backend="sqlite"
        ),
    )
    assert_eq(fetched_when.when, moment)


@test()
def json_decode_without_validation_returns_raw_decoded_value() -> None:
    """validate=False keeps the wire-only escape hatch: raw json.loads, no
    adapter coercion into the annotated type."""

    class Inner(BaseModel):
        x: int

    class ModelEvent[S = Pending](Model[S, "ModelEvent[Fetched]"]):
        """Json column annotated with a pydantic model."""

        payload: ModelEvent.Col[Json[Inner]] = Text(nullable=False)

    raw = cast(
        "ModelEvent[Fetched]",
        decode_model_row(
            ModelEvent, {"payload": '{"x":1}'}, backend="sqlite", validate=False
        ),
    )
    assert_eq(cast("object", raw.payload), {"x": 1})


@test()
def datetime_round_trips_through_iso_text_without_canonicalization() -> None:
    """A ``Col[datetime]`` over ``Text()`` delegates to pydantic: the value is
    serialized in its own offset (no forced UTC) at microsecond precision, and
    naive datetimes are allowed -- timezone policy is the user's logical type."""

    class AuditLog[S = Pending](Model[S, "AuditLog[Fetched]"]):
        """Table model with a timestamp stored as ISO text."""

        created_at: AuditLog.Col[datetime] = Text(nullable=False)

    source_timezone = timezone(timedelta(hours=5, minutes=30))
    source = datetime(2026, 5, 31, 12, 0, 1, 987654, tzinfo=source_timezone)
    audit_log = AuditLog(created_at=source)
    _, encoded_audit_log = encode_model_row(audit_log, backend="sqlite")

    # The Pending Model holds the raw validated datetime; encoding preserves the
    # offset and microseconds rather than canonicalizing to UTC milliseconds.
    assert_eq(audit_log.created_at, source)
    assert_eq(encoded_audit_log, {"created_at": "2026-05-31T12:00:01.987654+05:30"})

    fetched = cast(
        "AuditLog[Fetched]",
        decode_model_row(
            AuditLog,
            {"created_at": "2026-05-31T12:00:01.987654+05:30"},
            backend="sqlite",
        ),
    )
    assert_eq(fetched.created_at, source)

    # No AwareDatetime injection: a naive datetime is accepted and round-trips
    # naive (the user opts into awareness via the logical type).
    naive = datetime(2026, 5, 31, 12, 0, 1)  # noqa: DTZ001
    naive_log = AuditLog(created_at=naive)
    _, encoded_naive = encode_model_row(naive_log, backend="sqlite")
    assert_eq(encoded_naive, {"created_at": "2026-05-31T12:00:01"})


@test()
def uuid_logical_type_round_trips_as_text_and_blocks_like() -> None:
    """The ADR's first beneficiary: a ``Col[uuid.UUID]`` stored as ``Text()``
    round-trips through pydantic (string on the wire) and exposes no ``like``
    because its logical type is not ``str``."""

    class Account[S = Pending](Model[S, "Account[Fetched]"]):
        """Table model with a client-generated UUID primary key."""

        id: Account.Col[uuid.UUID] = Text(primary_key=True, default_factory=uuid.uuid4)

    value = uuid.UUID("12345678-1234-5678-1234-567812345678")
    account = Account(id=value)
    _, encoded = encode_model_row(account, backend="sqlite")
    assert_eq(encoded, {"id": str(value)})

    fetched = cast(
        "Account[Fetched]",
        decode_model_row(Account, {"id": str(value)}, backend="sqlite"),
    )
    assert_eq(fetched.id, value)

    with assert_raises(QueryConstructionError):
        _ = Account.id.like("1234%")


@test()
def external_value_failures_are_wrapped_in_model_validation_error() -> None:
    """Default factories and codecs do not leak third-party exceptions."""

    def broken_default() -> object:
        msg = "outside validation failure"
        raise ValueError(msg)

    class ExternalValue[S = Pending](Model[S, "ExternalValue[Fetched]"]):
        """Table model with an external default provider."""

        payload: ExternalValue.Col[Json[dict[str, int]]] = Text(
            default_factory=broken_default
        )

    with assert_raises(ModelValidationError):
        _ = ExternalValue()


@test()
def current_timestamp_default_declares_a_server_filled_generated_column() -> None:
    """``default=CurrentTimestamp`` is the server-default declaration.

    The marker routes to an internal Server Default: the column is omittable at
    construction (Missing until the database fills it) without writing
    ``default=MISSING``, yet an explicit value is still accepted. It must be a
    Generated Column and cannot also carry a Python factory.
    """

    class CreatedEvent[S = Pending](Model[S, "CreatedEvent[Fetched]"]):
        """Valid server-filled timestamp column stored as TEXT."""

        created_at: CreatedEvent.GenCol[datetime] = Text(default=CurrentTimestamp)
        name: CreatedEvent.Col[str] = Text(nullable=False)

    column = CreatedEvent.__snekql_columns__["created_at"]
    assert_true(column.server_default is CurrentTimestamp)
    assert_true(column.default is MISSING)

    # Omittable at construction: the database supplies the value.
    pending = CreatedEvent(name="first")
    assert_true(pending.created_at is MISSING)

    # An explicit value is still accepted.
    fixed = datetime(2020, 1, 1, tzinfo=UTC)
    explicit = CreatedEvent(name="second", created_at=fixed)
    assert_eq(explicit.created_at, fixed)

    with assert_raises(ModelDeclarationError):

        class NonGeneratedTimestamp[S = Pending](
            Model[S, "NonGeneratedTimestamp[Fetched]"]
        ):
            """A server default requires a generated (GenCol) column."""

            created_at: NonGeneratedTimestamp.Col[datetime] = Text(
                default=CurrentTimestamp,
            )

    with assert_raises(ModelDeclarationError):

        class TimestampWithFactory[S = Pending](
            Model[S, "TimestampWithFactory[Fetched]"],
        ):
            """CurrentTimestamp cannot be combined with a Python factory."""

            created_at: TimestampWithFactory.GenCol[datetime] = Text(
                default=CurrentTimestamp,
                default_factory=lambda: datetime(2026, 5, 31, tzinfo=UTC),
            )

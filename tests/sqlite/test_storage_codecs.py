"""SQLite storage type and value codec tests."""

from __future__ import annotations

import math
import uuid
from datetime import UTC, datetime, timedelta, timezone
from typing import cast

from pydantic import BaseModel, Json
from snektest import assert_eq, assert_false, assert_raises, assert_true, test

import snekql
from snekql._model_materialization import decode_model_row, encode_model_row
from snekql.sqlite import (
    PENDING_GENERATION,
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
def datetime_with_a_sub_minute_offset_is_rejected() -> None:
    """ISO-text serialization truncates UTC offsets to whole minutes, silently
    shifting the instant for historical sub-minute zones (e.g. an LMT offset of
    ``+03:06:52``). The codec refuses such datetimes with a domain error rather
    than corrupt them; whole-minute offsets and naive datetimes are unaffected."""

    class AuditLog[S = Pending](Model[S, "AuditLog[Fetched]"]):
        """Table model with a timestamp stored as ISO text."""

        created_at: AuditLog.Col[datetime] = Text(nullable=False)

    sub_minute = timezone(timedelta(hours=3, minutes=6, seconds=52))
    corrupting = datetime(2026, 5, 31, 12, 0, 1, tzinfo=sub_minute)
    with assert_raises(ModelValidationError):
        _ = encode_model_row(AuditLog(created_at=corrupting), backend="sqlite")

    # A whole-minute offset carrying the same wall time still round-trips.
    whole_minute = datetime(
        2026, 5, 31, 12, 0, 1, tzinfo=timezone(timedelta(hours=3, minutes=6))
    )
    _, encoded = encode_model_row(AuditLog(created_at=whole_minute), backend="sqlite")
    assert_eq(encoded, {"created_at": "2026-05-31T12:00:01+03:06"})


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

    def broken_default() -> Json[dict[str, int]]:
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
    construction (PendingGeneration until the database fills it) without writing
    ``default=PENDING_GENERATION``, yet an explicit value is still accepted. It must be a
    Generated Column and cannot also carry a Python factory.
    """

    class CreatedEvent[S = Pending](Model[S, "CreatedEvent[Fetched]"]):
        """Valid server-filled timestamp column stored as TEXT."""

        created_at: CreatedEvent.GenCol[datetime] = Text(default=CurrentTimestamp)
        name: CreatedEvent.Col[str] = Text(nullable=False)

    column = CreatedEvent.__snekql_columns__["created_at"]
    assert_true(column.server_default is CurrentTimestamp)
    assert_true(column.default is PENDING_GENERATION)

    # Omittable at construction: the database supplies the value.
    pending = CreatedEvent(name="first")
    assert_true(pending.created_at is PENDING_GENERATION)

    # An explicit value is still accepted.
    fixed = datetime(2020, 1, 1, tzinfo=UTC)
    explicit = CreatedEvent(name="second", created_at=fixed)
    assert_eq(explicit.created_at, fixed)

    with assert_raises(ModelDeclarationError):

        class NonGeneratedTimestamp[S = Pending](
            Model[S, "NonGeneratedTimestamp[Fetched]"]
        ):
            """A server default requires a generated (GenCol) column."""

            created_at: NonGeneratedTimestamp.Col[datetime] = Text(  # pyright: ignore[reportAssignmentType, reportUnknownVariableType]
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


@test()
def nullable_column_round_trips_none_for_every_storage_class() -> None:
    """A nullable column encodes ``None`` to SQL ``NULL`` and decodes it back,
    while a non-null column rejects ``NULL`` on the way in with a domain error."""

    class Profile[S = Pending](Model[S, "Profile[Fetched]"]):
        """Table model with one nullable column per SQLite storage class."""

        id: Profile.Col[int] = Integer(primary_key=True)
        rating: Profile.Col[float | None] = Real(nullable=True, default=None)
        nickname: Profile.Col[str | None] = Text(nullable=True, default=None)
        avatar: Profile.Col[bytes | None] = Blob(nullable=True, default=None)
        prefs: Profile.Col[Json[dict[str, int]] | None] = Text(
            nullable=True, default=None
        )

    profile = Profile(id=1)
    _, encoded = encode_model_row(profile, backend="sqlite")
    assert_eq(
        encoded,
        {"id": 1, "rating": None, "nickname": None, "avatar": None, "prefs": None},
    )

    fetched = cast(
        "Profile[Fetched]",
        decode_model_row(
            Profile,
            {"id": 1, "rating": None, "nickname": None, "avatar": None, "prefs": None},
            backend="sqlite",
        ),
    )
    assert_true(fetched.rating is None)
    assert_true(fetched.nickname is None)
    assert_true(fetched.avatar is None)
    assert_true(fetched.prefs is None)

    class Required[S = Pending](Model[S, "Required[Fetched]"]):
        """Non-null column whose decode must reject a ``NULL`` from the driver."""

        value: Required.Col[str] = Text(nullable=False)

    with assert_raises(ModelValidationError):
        _ = decode_model_row(Required, {"value": None}, backend="sqlite")


@test()
def integer_storage_round_trips_the_signed_64_bit_boundaries() -> None:
    """SQLite INTEGER is a signed 64-bit type; the extremes round-trip, and a
    value past the range fails with a domain error before the driver overflows."""

    class Counter[S = Pending](Model[S, "Counter[Fetched]"]):
        """Table model with a single INTEGER column."""

        value: Counter.Col[int] = Integer(nullable=False)

    for boundary in (-(2**63), 2**63 - 1):
        _, encoded = encode_model_row(Counter(value=boundary), backend="sqlite")
        assert_eq(encoded, {"value": boundary})

    # One past the signed 64-bit range: SQLite's driver raises a raw
    # ``OverflowError`` at bind time, so the codec rejects it first as a domain
    # error rather than letting persistence fail opaquely.
    with assert_raises(ModelValidationError):
        _ = encode_model_row(Counter(value=2**63), backend="sqlite")
    with assert_raises(ModelValidationError):
        _ = encode_model_row(Counter(value=-(2**63) - 1), backend="sqlite")


@test()
def non_finite_floats_fail_with_a_domain_error_before_persistence() -> None:
    """``nan``/``inf`` corrupt SQLite REAL storage (``nan`` silently becomes
    ``NULL``) and are rejected outright by MariaDB DOUBLE, so the codec refuses
    them with a domain error for a consistent cross-backend contract."""

    class Reading[S = Pending](Model[S, "Reading[Fetched]"]):
        """Table model with a single REAL column."""

        value: Reading.Col[float] = Real(nullable=False)

    for bad in (math.nan, math.inf, -math.inf):
        with assert_raises(ModelValidationError):
            _ = encode_model_row(Reading(value=bad), backend="sqlite")

    # Ordinary finite floats are untouched.
    _, encoded = encode_model_row(Reading(value=1.5), backend="sqlite")
    assert_eq(encoded, {"value": 1.5})


@test()
def large_text_blob_and_json_values_round_trip_unchanged() -> None:
    """Large payloads are passed through the codec verbatim; SQLite imposes no
    practical size ceiling below its 1 GB default limit."""

    class Document[S = Pending](Model[S, "Document[Fetched]"]):
        """Table model carrying sizable TEXT, BLOB, and JSON columns."""

        body: Document.Col[str] = Text(nullable=False)
        raw: Document.Col[bytes] = Blob(nullable=False)
        tags: Document.Col[Json[list[str]]] = Text(nullable=False)

    body = "x" * 1_000_000
    raw = b"\x00\xff" * 500_000
    tags = [f"tag-{i}" for i in range(10_000)]
    document = Document(body=body, raw=raw, tags=tags)
    _, encoded = encode_model_row(document, backend="sqlite")

    fetched = cast(
        "Document[Fetched]",
        decode_model_row(Document, encoded, backend="sqlite"),
    )
    assert_eq(fetched.body, body)
    assert_eq(fetched.raw, raw)
    assert_eq(fetched.tags, tags)


@test()
def json_codec_preserves_insertion_key_order_and_nested_values() -> None:
    """The JSON wire codec keeps the payload's key order (no sorting) and
    faithfully round-trips arbitrarily nested objects and arrays."""

    class Payload[S = Pending](Model[S, "Payload[Fetched]"]):
        """Table model with a free-form JSON object column."""

        data: Payload.Col[Json[dict[str, object]]] = Text(nullable=False)

    nested: dict[str, object] = {
        "b": 1,
        "a": {"d": [1, 2, {"deep": True}], "c": None},
        "z": ["x", {"y": 2}],
    }
    _, encoded = encode_model_row(Payload(data=nested), backend="sqlite")

    # Keys serialize in insertion order ("b" before "a"), not sorted.
    assert_eq(
        encoded,
        {"data": '{"b":1,"a":{"d":[1,2,{"deep":true}],"c":null},"z":["x",{"y":2}]}'},
    )

    fetched = cast(
        "Payload[Fetched]",
        decode_model_row(Payload, encoded, backend="sqlite"),
    )
    assert_eq(fetched.data, nested)

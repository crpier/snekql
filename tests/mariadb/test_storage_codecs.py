"""MariaDB storage codec and value family tests."""

from __future__ import annotations

import math
import uuid
from datetime import UTC, datetime, timedelta, timezone
from typing import Any

from pydantic import BaseModel, Json
from snektest import (
    assert_eq,
    assert_isinstance,
    assert_raises,
    assert_true,
    load_fixture,
    test,
)

from snekql import mariadb
from snekql.mariadb import (
    PENDING_GENERATION,
    CurrentTimestamp,
    Fetched,
    ModelDeclarationError,
    ModelValidationError,
    Pending,
    insert,
    select,
)
from tests.helpers import (
    TemporaryMariaDBServer,
    initialized_database,
    provide_mariadb_server,
)


def _config_from_server(server: TemporaryMariaDBServer) -> mariadb.Config:
    """Build a MariaDB config for the shared local test server."""

    return server.config()


@test()
def mariadb_storage_codecs_encode_and_decode_representative_values() -> None:
    """MariaDB columns expose backend-specific value codecs."""

    class Event[S = Pending](mariadb.Model[S, "Event[Fetched]"]):
        """Model used to bind MariaDB descriptors for direct codec checks."""

        flag: Event.Col[bool] = mariadb.Boolean(nullable=False)
        payload: Event.Col[dict[str, object]] = mariadb.Json(nullable=False)
        happened_at: Event.Col[datetime] = mariadb.DateTime(nullable=False)

    timestamp = datetime(2026, 1, 2, 3, 4, 5, 678901, tzinfo=UTC)

    assert_eq(Event.flag.encode(True, backend="mariadb"), 1)
    assert_eq(Event.flag.decode(0, backend="mariadb"), False)
    assert_eq(Event.payload.encode({"ok": True}, backend="mariadb"), '{"ok":true}')
    assert_eq(Event.payload.decode('{"ok":true}', backend="mariadb"), {"ok": True})
    assert_eq(
        Event.happened_at.encode(timestamp, backend="mariadb"),
        "2026-01-02 03:04:05.678",
    )
    assert_eq(
        Event.happened_at.decode("2026-01-02 03:04:05.678", backend="mariadb"),
        datetime(2026, 1, 2, 3, 4, 5, 678000, tzinfo=UTC),
    )


@test()
def mariadb_json_codec_round_trips_rich_annotated_types() -> None:
    """MariaDB Json codec routes through the column's pydantic adapter, so rich
    annotated types serialize, validate, and round-trip symmetrically."""

    class Inner(BaseModel):
        x: int

    class RichEvent[S = Pending](mariadb.Model[S, "RichEvent[Fetched]"]):
        """Json column annotated with a pydantic model."""

        payload: RichEvent.Col[Inner] = mariadb.Json(nullable=False)

    assert_eq(RichEvent.payload.encode(Inner(x=1), backend="mariadb"), '{"x":1}')
    assert_eq(RichEvent.payload.decode('{"x":1}', backend="mariadb"), Inner(x=1))
    # MariaDB hands JSON columns back as bytes; the adapter validates them too.
    assert_eq(RichEvent.payload.decode(b'{"x":1}', backend="mariadb"), Inner(x=1))
    assert_eq(
        RichEvent.payload.decode(b'{"x":1}', backend="mariadb", validate=False),
        {"x": 1},
    )


@test()
def mariadb_uuid_codec_round_trips_through_the_pydantic_scalar_path() -> None:
    """The native ``Uuid`` Column Type has no dedicated codec: it round-trips
    ``uuid.UUID`` through the shared pydantic scalar path (string on the wire)."""

    class Account[S = Pending](mariadb.Model[S, "Account[Fetched]"]):
        """Model binding a native MariaDB Uuid descriptor."""

        account_id: Account.Col[uuid.UUID] = mariadb.Uuid(nullable=False)

    value = uuid.UUID("12345678-1234-5678-1234-567812345678")
    assert_eq(Account.account_id.encode(value, backend="mariadb"), str(value))
    assert_eq(Account.account_id.decode(str(value), backend="mariadb"), value)


@test()
def mariadb_datetime_codec_decodes_native_driver_datetimes() -> None:
    """The MariaDB driver hands DATETIME columns back as ``datetime`` objects,
    not text; the codec normalizes naive values to UTC and leaves aware ones."""

    class Event[S = Pending](mariadb.Model[S, "Event[Fetched]"]):
        """Model binding a MariaDB DateTime descriptor for direct codec checks."""

        happened_at: Event.Col[datetime] = mariadb.DateTime(nullable=False)

    naive = datetime(2026, 1, 2, 3, 4, 5, 678000)  # noqa: DTZ001
    assert_eq(
        Event.happened_at.decode(naive, backend="mariadb"),
        datetime(2026, 1, 2, 3, 4, 5, 678000, tzinfo=UTC),
    )

    aware = datetime(
        2026, 1, 2, 3, 4, 5, 678000, tzinfo=timezone(timedelta(hours=5, minutes=30))
    )
    assert_eq(Event.happened_at.decode(aware, backend="mariadb"), aware)


@test()
def mariadb_datetime_codec_rejects_naive_datetimes_on_encode() -> None:
    """A native ``DateTime`` column stores UTC text with no offset. Encoding a
    naive datetime would force snekql to assume a timezone (previously the
    machine's local zone via ``astimezone``), so the same wall-clock value would
    land as a different instant depending on where the write ran. Reject naive
    input outright rather than guess; awareness is opt-in via the logical type."""

    class Event[S = Pending](mariadb.Model[S, "Event[Fetched]"]):
        """Model binding a MariaDB DateTime descriptor for direct codec checks."""

        happened_at: Event.Col[datetime] = mariadb.DateTime(nullable=False)

    naive = datetime(2026, 1, 2, 3, 4, 5, 678000)  # noqa: DTZ001
    with assert_raises(ModelValidationError):
        _ = Event.happened_at.encode(naive, backend="mariadb")

    # Aware datetimes are unaffected: they carry the offset needed to reduce to a
    # single unambiguous UTC instant.
    aware = datetime(
        2026, 1, 2, 3, 4, 5, 678000, tzinfo=timezone(timedelta(hours=5, minutes=30))
    )
    assert_eq(
        Event.happened_at.encode(aware, backend="mariadb"),
        "2026-01-01 21:34:05.678",
    )


@test()
def mariadb_server_defaults_require_generated_datetime_columns() -> None:
    """CurrentTimestamp keeps the existing generated-column declaration rules."""

    with assert_raises(ModelDeclarationError):

        class BadEvent[S = Pending](mariadb.Model[S, "BadEvent[Fetched]"]):
            """Invalid MariaDB model using a server default on a normal column."""

            created_at: BadEvent.Col[datetime] = mariadb.DateTime(  # pyright: ignore[reportAssignmentType, reportUnknownVariableType]
                default=CurrentTimestamp,
            )

    with assert_raises(ModelDeclarationError):

        class BadCounter[S = Pending](mariadb.Model[S, "BadCounter[Fetched]"]):
            """Invalid MariaDB model using auto increment outside a primary key."""

            count: BadCounter.Col[int] = mariadb.Integer(auto_increment=True)


@test()
def mariadb_nullable_columns_round_trip_none_and_reject_required_nulls() -> None:
    """Nullable MariaDB columns encode/decode ``None``; a non-null column rejects
    a ``NULL`` from the driver with a domain error."""

    class Profile[S = Pending](mariadb.Model[S, "Profile[Fetched]"]):
        """Model with a nullable column per representative MariaDB family."""

        rating: Profile.Col[float | None] = mariadb.Real(nullable=True, default=None)
        nickname: Profile.Col[str | None] = mariadb.Text(nullable=True, default=None)
        prefs: Profile.Col[dict[str, int] | None] = mariadb.Json(
            nullable=True, default=None
        )
        flag: Profile.Col[bool | None] = mariadb.Boolean(nullable=True, default=None)
        seen_at: Profile.Col[datetime | None] = mariadb.DateTime(
            nullable=True, default=None
        )

    for column in (
        Profile.rating,
        Profile.nickname,
        Profile.prefs,
        Profile.flag,
        Profile.seen_at,
    ):
        assert_true(column.encode(None, backend="mariadb") is None)
        assert_true(column.decode(None, backend="mariadb") is None)

    class Required[S = Pending](mariadb.Model[S, "Required[Fetched]"]):
        """Non-null column whose decode must reject a driver ``NULL``."""

        value: Required.Col[str] = mariadb.Text(nullable=False)

    with assert_raises(ModelValidationError):
        _ = Required.value.decode(None, backend="mariadb")


@test()
def mariadb_integer_codec_enforces_the_signed_64_bit_range() -> None:
    """MariaDB BIGINT is signed 64-bit; the extremes encode and values past the
    range fail with a domain error before reaching the driver."""

    class Counter[S = Pending](mariadb.Model[S, "Counter[Fetched]"]):
        """Model with a single BIGINT column."""

        value: Counter.Col[int] = mariadb.Integer(nullable=False)

    for boundary in (-(2**63), 2**63 - 1):
        assert_eq(Counter.value.encode(boundary, backend="mariadb"), boundary)

    with assert_raises(ModelValidationError):
        _ = Counter.value.encode(2**63, backend="mariadb")
    with assert_raises(ModelValidationError):
        _ = Counter.value.encode(-(2**63) - 1, backend="mariadb")


@test()
def mariadb_non_finite_floats_fail_with_a_domain_error() -> None:
    """MariaDB DOUBLE cannot store ``nan``/``inf``; the codec rejects them with a
    domain error, matching the SQLite contract."""

    class Reading[S = Pending](mariadb.Model[S, "Reading[Fetched]"]):
        """Model with a single DOUBLE column."""

        value: Reading.Col[float] = mariadb.Real(nullable=False)

    for bad in (math.nan, math.inf, -math.inf):
        with assert_raises(ModelValidationError):
            _ = Reading.value.encode(bad, backend="mariadb")

    assert_eq(Reading.value.encode(1.5, backend="mariadb"), 1.5)


@test()
def mariadb_json_codec_preserves_insertion_key_order() -> None:
    """The MariaDB Json wire codec keeps the payload's key order (no sorting) and
    round-trips nested values."""

    class Payload[S = Pending](mariadb.Model[S, "Payload[Fetched]"]):
        """Model with a free-form JSON object column."""

        data: Payload.Col[Json[dict[str, object]]] = mariadb.Json(nullable=False)

    nested: dict[str, object] = {"b": 1, "a": {"d": [1, 2], "c": None}}
    encoded = Payload.data.encode(nested, backend="mariadb")
    assert_eq(encoded, '{"b":1,"a":{"d":[1,2],"c":null}}')
    assert_eq(Payload.data.decode(encoded, backend="mariadb"), nested)


@test()
def mariadb_boolean_codec_normalizes_driver_tinyint_to_bool() -> None:
    """Boolean encodes to ``1``/``0`` and decodes the driver ``tinyint`` back to a
    real ``bool`` (not a bare ``int``), both nullable and non-null."""

    class Flagged[S = Pending](mariadb.Model[S, "Flagged[Fetched]"]):
        """Model with a non-null and a nullable BOOLEAN column."""

        enabled: Flagged.Col[bool] = mariadb.Boolean(nullable=False)
        verified: Flagged.Col[bool | None] = mariadb.Boolean(
            nullable=True, default=None
        )

    assert_eq(Flagged.enabled.encode(True, backend="mariadb"), 1)
    assert_eq(Flagged.enabled.encode(False, backend="mariadb"), 0)

    for driver_value in (0, 1):
        decoded = Flagged.enabled.decode(driver_value, backend="mariadb")
        assert_isinstance(decoded, bool)
        assert_eq(decoded, bool(driver_value))

    assert_true(Flagged.verified.encode(None, backend="mariadb") is None)
    assert_true(Flagged.verified.decode(None, backend="mariadb") is None)


@test()
def mariadb_oversized_text_and_blob_values_fail_with_a_domain_error() -> None:
    """MariaDB ``Text`` is ``VARCHAR(255)`` and ``Blob`` is ``BLOB`` (64 KiB);
    values past those limits are rejected at encode with a domain error rather
    than silently truncated by the driver. JSON has no practical ceiling."""

    class Document[S = Pending](mariadb.Model[S, "Document[Fetched]"]):
        """Model carrying length-bounded TEXT and BLOB columns plus JSON."""

        body: Document.Col[str] = mariadb.Text(nullable=False)
        raw: Document.Col[bytes] = mariadb.Blob(nullable=False)
        tags: Document.Col[Json[list[str]]] = mariadb.Json(nullable=False)

    # Boundary values encode unchanged.
    assert_eq(Document.body.encode("x" * 255, backend="mariadb"), "x" * 255)
    assert_eq(Document.raw.encode(b"\x00" * 65535, backend="mariadb"), b"\x00" * 65535)

    with assert_raises(ModelValidationError):
        _ = Document.body.encode("x" * 256, backend="mariadb")
    with assert_raises(ModelValidationError):
        _ = Document.raw.encode(b"\x00" * 65536, backend="mariadb")

    # JSON (LONGTEXT-backed) carries large payloads verbatim.
    big_tags = [f"tag-{i}" for i in range(10_000)]
    encoded = Document.tags.encode(big_tags, backend="mariadb")
    assert_eq(Document.tags.decode(encoded, backend="mariadb"), big_tags)


@test(mark="medium")
async def mariadb_value_families_round_trip_through_runtime() -> None:
    """MariaDB round trips the initial value families through a live database."""

    server = await load_fixture(provide_mariadb_server())

    class Event[S = Pending](mariadb.Model[S, "Event[Fetched]"]):
        """Model covering MariaDB value family round trips."""

        __tablename__ = "issue40_event_values"

        id: Event.GenCol[int] = mariadb.Integer(
            primary_key=True,
            auto_increment=True,
            default=PENDING_GENERATION,
        )
        account_id: Event.Col[uuid.UUID] = mariadb.Uuid(nullable=False)
        amount: Event.Col[float] = mariadb.Real(nullable=False)
        content: Event.Col[bytes] = mariadb.Blob(nullable=False)
        created_at: Event.GenCol[datetime] = mariadb.DateTime(
            default=CurrentTimestamp,
        )
        enabled: Event.Col[bool] = mariadb.Boolean(nullable=False)
        happened_at: Event.Col[datetime] = mariadb.DateTime(nullable=False)
        message: Event.Col[str] = mariadb.Text(nullable=False)
        payload: Event.Col[dict[str, Any]] = mariadb.Json(nullable=False)

    database = await initialized_database(_config_from_server(server), models=[Event])
    happened_at = datetime(2026, 1, 2, 3, 4, 5, 678901, tzinfo=UTC)
    account_id = uuid.uuid4()
    try:
        async with database.transaction() as tx:
            await tx.execute(
                insert(
                    Event(
                        account_id=account_id,
                        amount=12.5,
                        content=b"hello",
                        enabled=True,
                        happened_at=happened_at,
                        message="created",
                        payload={"count": 2, "ok": True},
                    )
                )
            )
            event = await tx.fetch_one(select(Event).all())
    finally:
        await database.close()

    assert_isinstance(event.id, int)
    assert_eq(event.account_id, account_id)
    assert_eq(event.amount, 12.5)
    assert_eq(event.content, b"hello")
    assert_isinstance(event.created_at, datetime)
    assert_eq(event.enabled, True)
    assert_eq(event.happened_at, datetime(2026, 1, 2, 3, 4, 5, 678000, tzinfo=UTC))
    assert_eq(event.message, "created")
    assert_eq(event.payload, {"count": 2, "ok": True})

"""MariaDB storage codec and value family tests."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel
from snektest import assert_eq, assert_isinstance, assert_raises, load_fixture, test

from snekql import (
    MISSING,
    CurrentTimestamp,
    Database,
    Fetched,
    ModelDeclarationError,
    Pending,
    insert,
    mariadb,
    select,
)
from tests.helpers import NULL_LOGGER, TemporaryMariaDBServer, provide_mariadb_server


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
def mariadb_server_defaults_require_generated_datetime_columns() -> None:
    """CurrentTimestamp keeps the existing generated-column declaration rules."""

    with assert_raises(ModelDeclarationError):

        class BadEvent[S = Pending](mariadb.Model[S, "BadEvent[Fetched]"]):
            """Invalid MariaDB model using a server default on a normal column."""

            created_at: BadEvent.Col[datetime] = mariadb.DateTime(
                server_default=CurrentTimestamp(),
            )

    with assert_raises(ModelDeclarationError):

        class BadCounter[S = Pending](mariadb.Model[S, "BadCounter[Fetched]"]):
            """Invalid MariaDB model using auto increment outside a primary key."""

            count: BadCounter.Col[int] = mariadb.Integer(auto_increment=True)


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
            default=MISSING,
        )
        amount: Event.Col[float] = mariadb.Real(nullable=False)
        content: Event.Col[bytes] = mariadb.Blob(nullable=False)
        created_at: Event.GenCol[datetime] = mariadb.DateTime(
            server_default=CurrentTimestamp(),
            default=MISSING,
        )
        enabled: Event.Col[bool] = mariadb.Boolean(nullable=False)
        happened_at: Event.Col[datetime] = mariadb.DateTime(nullable=False)
        message: Event.Col[str] = mariadb.Text(nullable=False)
        payload: Event.Col[dict[str, Any]] = mariadb.Json(nullable=False)

    database = await Database.initialize(
        _config_from_server(server), logger=NULL_LOGGER, models=[Event]
    )
    happened_at = datetime(2026, 1, 2, 3, 4, 5, 678901, tzinfo=UTC)
    try:
        async with database.transaction() as tx:
            await tx.execute(
                insert(
                    Event(
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

    assert event is not None
    assert_isinstance(event.id, int)
    assert_eq(event.amount, 12.5)
    assert_eq(event.content, b"hello")
    assert_isinstance(event.created_at, datetime)
    assert_eq(event.enabled, True)
    assert_eq(event.happened_at, datetime(2026, 1, 2, 3, 4, 5, 678000, tzinfo=UTC))
    assert_eq(event.message, "created")
    assert_eq(event.payload, {"count": 2, "ok": True})

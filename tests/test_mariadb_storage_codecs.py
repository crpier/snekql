"""MariaDB storage codec and value family tests."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from snektest import assert_eq, assert_isinstance, assert_raises, load_fixture, test

from snekql import (
    MISSING,
    CurrentTimestamp,
    Database,
    ModelDeclarationError,
    Pending,
    insert,
    mariadb,
    select,
)
from tests.logging_helpers import NULL_LOGGER
from tests.mariadb_server import TemporaryMariaDBServer, provide_mariadb_server


def _config_from_server(server: TemporaryMariaDBServer) -> mariadb.Config:
    """Build a MariaDB config for the shared local test server."""

    return server.config()


@test()
def mariadb_storage_codecs_encode_and_decode_representative_values() -> None:
    """MariaDB columns expose backend-specific value codecs."""

    class Event[S = Pending](mariadb.Model[S, "Event[object]"]):
        """Model used to bind MariaDB descriptors for direct codec checks."""

        flag: Event.Col[bool] = mariadb.Boolean(nullable=False)
        payload: Event.Col[dict[str, object]] = mariadb.Json(nullable=False)
        happened_at: Event.Col[datetime] = mariadb.DateTime(nullable=False)

    timestamp = datetime(2026, 1, 2, 3, 4, 5, 678901, tzinfo=UTC)

    assert_eq(Event.flag.encode_mariadb(True), 1)
    assert_eq(Event.flag.decode_mariadb(0), False)
    assert_eq(Event.payload.encode_mariadb({"ok": True}), '{"ok":true}')
    assert_eq(Event.payload.decode_mariadb('{"ok":true}'), {"ok": True})
    assert_eq(Event.happened_at.encode_mariadb(timestamp), "2026-01-02 03:04:05.678")
    assert_eq(
        Event.happened_at.decode_mariadb("2026-01-02 03:04:05.678"),
        datetime(2026, 1, 2, 3, 4, 5, 678000, tzinfo=UTC),
    )


@test()
def mariadb_server_defaults_require_generated_datetime_columns() -> None:
    """CurrentTimestamp keeps the existing generated-column declaration rules."""

    with assert_raises(ModelDeclarationError):

        class BadEvent[S = Pending](mariadb.Model[S, "BadEvent[object]"]):
            """Invalid MariaDB model using a server default on a normal column."""

            created_at: BadEvent.Col[datetime] = mariadb.DateTime(
                server_default=CurrentTimestamp(),
            )

    with assert_raises(ModelDeclarationError):

        class BadCounter[S = Pending](mariadb.Model[S, "BadCounter[object]"]):
            """Invalid MariaDB model using auto increment outside a primary key."""

            count: BadCounter.Col[int] = mariadb.Integer(auto_increment=True)


@test(mark="medium")
async def mariadb_value_families_round_trip_through_runtime() -> None:
    """MariaDB round trips the initial value families through a live database."""

    class Event[S = Pending](mariadb.Model[S, "Event[object]"]):
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

    server = await load_fixture(provide_mariadb_server())
    database = await Database.initialize(
        NULL_LOGGER, _config_from_server(server), models=[Event]
    )
    happened_at = datetime(2026, 1, 2, 3, 4, 5, 678901, tzinfo=UTC)
    try:
        async with database.transaction() as transaction:
            await transaction.execute(
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
            event = await transaction.fetch_one(select(Event).all())
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

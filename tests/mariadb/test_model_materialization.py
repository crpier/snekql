"""MariaDB Table Model materialization tests."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import cast

from snektest import assert_eq, assert_raises, test

from snekql import mariadb
from snekql._model_materialization import decode_model_row, encode_model_row
from snekql.mariadb import Fetched, Pending, select
from snekql.mariadb.query import materialize_mariadb_select_row


@test(mark="fast")
def mariadb_model_materialization_uses_one_backend_codec_path() -> None:
    """MariaDB Pending/Fetched Model conversion is handled by the materializer."""

    class Event[S = Pending](mariadb.Model[S, "Event[Fetched]"]):
        """MariaDB model used by materialization seam tests."""

        enabled: Event.Col[bool] = mariadb.Boolean(nullable=False)
        happened_at: Event.Col[datetime] = mariadb.DateTime(nullable=False)
        payload: Event.Col[dict[str, object]] = mariadb.Json(nullable=False)

    pending_event = Event(
        enabled=True,
        happened_at=datetime(2026, 1, 2, 3, 4, 5, 678901, tzinfo=UTC),
        payload={"ok": True},
    )
    model_class, encoded_row = encode_model_row(pending_event, backend="mariadb")
    fetched_event = cast(
        "Event[Fetched]",
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
def mariadb_model_materialization_asserts_database_row_shape() -> None:
    """MariaDB model materialization treats row-shape mismatch as invariant failure."""

    class Event[S = Pending](mariadb.Model[S, "Event[Fetched]"]):
        """MariaDB model used by row-shape checks."""

        enabled: Event.Col[bool] = mariadb.Boolean(nullable=False)

    with assert_raises(AssertionError):
        _ = decode_model_row(Event, {}, backend="mariadb")

    with assert_raises(AssertionError):
        _ = decode_model_row(Event, {"enabled": 1, "extra": 2}, backend="mariadb")


@test(mark="fast")
def mariadb_select_materialization_asserts_database_row_shape() -> None:
    """MariaDB select materialization treats row-shape mismatch as invariant failure."""

    class User[S = Pending](mariadb.Model[S, "User[Fetched]"]):
        """MariaDB model used by row-shape materialization checks."""

        email: User.Col[str] = mariadb.Text(nullable=False)

    query = select(User.email).all()

    with assert_raises(AssertionError):
        _ = materialize_mariadb_select_row(query, ())

    with assert_raises(AssertionError):
        _ = materialize_mariadb_select_row(query, ("a@example.com", "extra"))


@test(mark="fast")
def mariadb_min_max_decode_to_logical_type() -> None:
    """MIN/MAX over a MariaDB column decode through the column's full codec.

    F6's fix is backend-agnostic: the same wire->logical coercion that runs on
    SQLite must run on MariaDB too, so a ``datetime``/``bool`` aggregate carries
    its logical type rather than the raw driver wire value.
    """

    class Event[S = Pending](mariadb.Model[S, "Event[Fetched]"]):
        """MariaDB model exercising MIN/MAX logical decoding."""

        enabled: Event.Col[bool] = mariadb.Boolean(nullable=False)
        happened_at: Event.Col[datetime] = mariadb.DateTime(nullable=False)

    earliest = materialize_mariadb_select_row(
        select(Event.happened_at.min()).all(), ("2026-01-02 03:04:05.678",)
    )
    flag = materialize_mariadb_select_row(select(Event.enabled.max()).all(), (1,))

    assert_eq(earliest, datetime(2026, 1, 2, 3, 4, 5, 678000, tzinfo=UTC))
    assert_eq(flag, True)

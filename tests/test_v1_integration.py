"""V1 public integration tests against real SQLite databases."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone
from logging import Handler, LogRecord, getLogger
from pathlib import Path
from sqlite3 import connect
from tempfile import TemporaryDirectory
from typing import Literal

from snektest import assert_eq, assert_is_none, assert_raises, assert_true, test

from snekql import (
    MISSING,
    Boolean,
    CurrentTimestamp,
    Database,
    DatabaseClosedError,
    DatabaseCloseTimeoutError,
    DateTime,
    Fetched,
    Integer,
    Json,
    Model,
    Pending,
    PoolTimeoutError,
    SchemaError,
    SchemaVerificationError,
    Text,
    TransactionClosedError,
    delete,
    insert,
    select,
    update,
)

type DatabaseTarget = Path | Literal[":memory:"]


class V1Event[S = Pending](Model[S, "V1Event[Fetched]"]):
    """Integration model that exercises generated and encoded columns."""

    id: V1Event.GenCol[int] = Integer(
        primary_key=True,
        auto_increment=True,
        default=MISSING,
    )
    active: V1Event.Col[bool] = Boolean(nullable=False)
    created_at: V1Event.GenCol[datetime] = DateTime(
        server_default=CurrentTimestamp(),
        default=MISSING,
    )
    happened_at: V1Event.Col[datetime] = DateTime(nullable=False)
    name: V1Event.Col[str] = Text(nullable=False)
    payload: V1Event.Col[dict[str, object]] = Json(nullable=False)


class V1Lifecycle[S = Pending](Model[S, "V1Lifecycle[Fetched]"]):
    """Small model for transaction, pool, and close lifecycle integration."""

    id: V1Lifecycle.GenCol[int] = Integer(
        primary_key=True,
        auto_increment=True,
        default=MISSING,
    )
    name: V1Lifecycle.Col[str] = Text(nullable=False)


class _CollectingHandler(Handler):
    """Logging handler that stores schema warning records."""

    def __init__(self) -> None:
        super().__init__()
        self.records: list[LogRecord] = []

    def emit(self, record: LogRecord) -> None:
        self.records.append(record)


def _execute_sql(database_path: Path, sql: str) -> None:
    connection = connect(database_path)
    try:
        _ = connection.execute(sql)
        connection.commit()
    finally:
        connection.close()


async def _exercise_v1_runtime(database_target: DatabaseTarget) -> None:
    source_timezone = timezone(timedelta(hours=-4))
    happened_at = datetime(2026, 5, 31, 12, 30, 1, 987654, tzinfo=source_timezone)
    expected_happened_at = datetime(2026, 5, 31, 16, 30, 1, 987000, tzinfo=UTC)
    payload: dict[str, object] = {"kind": "created", "count": 2, "tags": ["v1"]}

    database = await Database.initialize(database=database_target, models=[V1Event])
    try:
        async with database.transaction() as transaction:
            insert_result = await transaction.execute(
                insert(
                    V1Event(
                        active=True,
                        happened_at=happened_at,
                        name="alpha",
                        payload=payload,
                    )
                )
            )
            await transaction.execute(
                insert(
                    V1Event(
                        active=False,
                        happened_at=happened_at,
                        name="beta",
                        payload={"kind": "ignored"},
                    )
                )
            )

            first_name = await transaction.fetch_one(
                select(V1Event.name).all().order_by(V1Event.id.asc()),
            )
            no_name = await transaction.fetch_one(select(V1Event.name).all().limit(0))
            fetched_event = await transaction.fetch_one(
                select(V1Event).where(V1Event.name.eq("alpha")),
            )
            update_result = await transaction.execute(
                update(V1Event)
                .set(V1Event.name.to("alpha-renamed"), V1Event.active.to(False))
                .where(V1Event.name.eq("alpha")),
            )
            delete_result = await transaction.execute(
                delete(V1Event).where(V1Event.name.eq("beta")),
            )
            remaining_names = await transaction.fetch_all(
                select(V1Event.name).all().order_by(V1Event.id.asc()),
            )
    finally:
        await database.close()

    assert_is_none(insert_result)
    assert_is_none(update_result)
    assert_is_none(delete_result)
    assert_eq(first_name, "alpha")
    assert_eq(no_name, None)
    if fetched_event is None:
        msg = "expected alpha event to be fetched"
        raise AssertionError(msg)
    event: V1Event[Fetched] = fetched_event
    assert_eq(event.id, 1)
    assert_true(event.active)
    assert_eq(event.happened_at, expected_happened_at)
    assert_eq(event.created_at.tzinfo, UTC)
    assert_eq(event.payload, payload)
    assert_eq(remaining_names, ["alpha-renamed"])


@test(mark="medium")
async def path_database_exercises_v1_runtime_and_schema_verification() -> None:
    """A pathlib.Path database creates schema, runs CRUD, and verifies on reopen."""

    with TemporaryDirectory() as directory:
        database_path = Path(directory) / "app.db"
        await _exercise_v1_runtime(database_path)

        database = await Database.initialize(database=database_path, models=[V1Event])
        await database.close()


@test(mark="medium")
async def memory_database_exercises_v1_runtime() -> None:
    """The exact :memory: database target supports the same public runtime flow."""

    await _exercise_v1_runtime(":memory:")


@test(mark="medium")
async def schema_policies_cover_duplicate_names_and_non_strict_drift() -> None:
    """Strict rejects drift, warn logs drift, and duplicate table names fail fast."""

    class DriftedEvent[S = Pending](Model[S, "DriftedEvent[object]"]):
        """Model whose existing table intentionally lacks SQLite STRICT."""

        name: DriftedEvent.Col[str] = Text(nullable=False)

    class DuplicateOne[S = Pending](Model[S, "DuplicateOne[object]"]):
        """First model with a duplicate resolved table name."""

        __tablename__ = "duplicate_event"
        name: DuplicateOne.Col[str] = Text(nullable=False)

    class DuplicateTwo[S = Pending](Model[S, "DuplicateTwo[object]"]):
        """Second model with a duplicate resolved table name."""

        __tablename__ = "duplicate_event"
        name: DuplicateTwo.Col[str] = Text(nullable=False)

    with TemporaryDirectory() as directory:
        database_path = Path(directory) / "app.db"
        _execute_sql(
            database_path,
            'CREATE TABLE "drifted_event" ("name" TEXT NOT NULL)',
        )

        with assert_raises(SchemaVerificationError):
            _ = await Database.initialize(database=database_path, models=[DriftedEvent])

        logger = getLogger("snekql")
        handler = _CollectingHandler()
        logger.addHandler(handler)
        try:
            database = await Database.initialize(
                database=database_path,
                models=[DriftedEvent],
                schema_policy="warn",
            )
            await database.close()
        finally:
            logger.removeHandler(handler)

        with assert_raises(SchemaError):
            _ = await Database.initialize(
                database=database_path,
                models=[DuplicateOne, DuplicateTwo],
            )

    assert_true(
        any(
            record.getMessage() == "schema drift detected" for record in handler.records
        )
    )


@test(mark="medium")
async def transactions_pool_and_close_lifecycle_are_integrated() -> None:
    """Transactions commit/roll back and close remains idempotent and retryable."""

    database = await Database.initialize(
        database=":memory:",
        models=[V1Lifecycle],
        pool_size=1,
        acquire_timeout=0.0,
    )
    transaction = database.transaction(timeout=0.0)
    try:
        async with database.transaction() as commit_transaction:
            await commit_transaction.execute(insert(V1Lifecycle(name="committed")))

        with assert_raises(ValueError):
            async with database.transaction() as rollback_transaction:
                await rollback_transaction.execute(
                    insert(V1Lifecycle(name="rolled-back")),
                )
                msg = "force rollback"
                raise ValueError(msg)

        async with database.transaction() as read_transaction:
            names = await read_transaction.fetch_all(
                select(V1Lifecycle.name).all().order_by(V1Lifecycle.id.asc()),
            )

        _ = await transaction.__aenter__()
        with assert_raises(PoolTimeoutError):
            async with database.transaction(timeout=0.0):
                pass
        with assert_raises(DatabaseCloseTimeoutError):
            await database.close()
        await transaction.__aexit__(None, None, None)

        with assert_raises(TransactionClosedError):
            _ = await transaction.fetch_all(select(V1Lifecycle).all())

        async with database.transaction(timeout=0.0):
            pass
    finally:
        await database.close()

    await database.close()
    with assert_raises(DatabaseClosedError):
        _ = database.transaction()
    assert_eq(names, ["committed"])

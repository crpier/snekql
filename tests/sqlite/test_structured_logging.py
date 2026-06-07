"""SQLite Query Runtime structured logging tests."""

from __future__ import annotations

from pathlib import Path
from sqlite3 import connect
from tempfile import TemporaryDirectory
from typing import Any, cast

from snektest import assert_eq, assert_raises, assert_true, test

from snekql import (
    MISSING,
    Database,
    ExecutionError,
    Fetched,
    Integer,
    Model,
    Pending,
    PoolTimeoutError,
    Text,
    insert,
    select,
)


class _RecordingStructuredLogger:
    """Structured logger fake that records event calls for assertions."""

    def __init__(self) -> None:
        self.events: list[tuple[str, str, dict[str, object]]] = []

    def debug(self, event: str, **fields: object) -> None:
        self.events.append(("debug", event, fields))

    def info(self, event: str, **fields: object) -> None:
        self.events.append(("info", event, fields))

    def warning(self, event: str, **fields: object) -> None:
        self.events.append(("warning", event, fields))

    def error(self, event: str, **fields: object) -> None:
        self.events.append(("error", event, fields))

    def find(self, event: str) -> dict[str, object]:
        """Return the first recorded event fields for the named event."""

        for _level, recorded_event, fields in self.events:
            if recorded_event == event:
                return fields
        msg = f"event not recorded: {event}"
        raise AssertionError(msg)

    def has(self, level: str, event: str) -> bool:
        """Return whether a level/event pair was recorded."""

        return any(
            recorded_level == level and recorded_event == event
            for recorded_level, recorded_event, _fields in self.events
        )


def _execute_sql(database_path: Path, sql: str) -> None:
    connection = connect(database_path)
    try:
        _ = connection.execute(sql)
        connection.commit()
    finally:
        connection.close()


@test()
def database_initialization_requires_a_logger() -> None:
    """The public initialization path requires explicit structured logging."""

    initialize = cast("Any", Database.initialize)

    with assert_raises(TypeError):
        _ = initialize(database=":memory:")

    with assert_raises(TypeError):
        _ = initialize(_RecordingStructuredLogger(), database=":memory:")


@test(mark="medium")
async def database_initialization_emits_structured_events() -> None:
    """Database initialization logs backend and schema startup context."""

    class User[S = Pending](Model[S, "User[Fetched]"]):
        """Table model used to observe schema startup logging."""

        id: User.GenCol[int] = Integer(
            primary_key=True,
            auto_increment=True,
            default=MISSING,
        )
        email: User.Col[str] = Text(nullable=False)

    logger = _RecordingStructuredLogger()
    with TemporaryDirectory() as directory:
        database_path = Path(directory) / "app.db"
        database = await Database.initialize(
            logger=logger,
            database=database_path,
            models=[User],
        )
        await database.close()

    started = logger.find("database initialization started")
    completed = logger.find("database initialization completed")
    created = logger.find("schema table created")

    assert_eq(started["backend"], "sqlite")
    assert_eq(started["model_count"], 1)
    assert_eq(started["table_names"], ("user",))
    assert_eq(completed["backend"], "sqlite")
    assert_eq(created["table_name"], "user")
    assert_true(logger.has("info", "database initialization started"))
    assert_true(logger.has("info", "database initialization completed"))


@test(mark="medium")
async def warn_schema_policy_uses_injected_structured_logger() -> None:
    """Warn schema verification reports drift through the supplied logger."""

    class User[S = Pending](Model[S, "User[Fetched]"]):
        """Table model used for warn policy drift logging."""

        email: User.Col[str] = Text(nullable=False)

    logger = _RecordingStructuredLogger()
    with TemporaryDirectory() as directory:
        database_path = Path(directory) / "app.db"
        _execute_sql(database_path, 'CREATE TABLE "user" ("email" TEXT NOT NULL)')

        database = await Database.initialize(
            logger=logger,
            database=database_path,
            models=[User],
            schema_policy="warn",
        )
        await database.close()

    drift = logger.find("schema drift detected")
    assert_eq(drift["table_name"], "user")
    assert_true(logger.has("warning", "schema drift detected"))


@test(mark="medium")
async def transaction_execution_emits_query_context() -> None:
    """Transaction logging includes SQL and params without redaction."""

    class User[S = Pending](Model[S, "User[Fetched]"]):
        """Table model used to observe query execution logging."""

        id: User.GenCol[int] = Integer(
            primary_key=True,
            auto_increment=True,
            default=MISSING,
        )
        email: User.Col[str] = Text(nullable=False)

    logger = _RecordingStructuredLogger()
    database = await Database.initialize(
        logger=logger,
        database=":memory:",
        models=[User],
    )
    try:
        async with database.transaction() as tx:
            await tx.execute(insert(User(email="secret@example.com")))
            row = await tx.fetch_one(
                select(User.email).where(User.email.eq("secret@example.com"))
            )
    finally:
        await database.close()

    assert_eq(row, "secret@example.com")
    write = next(
        fields
        for _level, event, fields in logger.events
        if event == "query executed" and fields["operation"] == "write"
    )
    select_event = next(
        fields
        for _level, event, fields in logger.events
        if event == "query executed" and fields["operation"] == "fetch_one"
    )

    assert_eq(write["params"], ("secret@example.com",))
    assert_eq(select_event["params"], ("secret@example.com",))
    assert_true(logger.has("debug", "transaction begin"))
    assert_true(logger.has("debug", "transaction commit"))


@test(mark="medium")
async def query_failure_emits_structured_error_context() -> None:
    """Execution failures log SQL and params before raising ExecutionError."""

    class User[S = Pending](Model[S, "User[Fetched]"]):
        """Table model with a unique field used to force a write failure."""

        email: User.Col[str] = Text(nullable=False, unique=True)

    logger = _RecordingStructuredLogger()
    database = await Database.initialize(
        logger=logger,
        database=":memory:",
        models=[User],
    )
    try:
        async with database.transaction() as tx:
            await tx.execute(insert(User(email="duplicate@example.com")))
            with assert_raises(ExecutionError):
                await tx.execute(insert(User(email="duplicate@example.com")))
    finally:
        await database.close()

    failure = logger.find("query failed")
    assert_eq(failure["operation"], "write")
    assert_eq(failure["params"], ("duplicate@example.com",))
    assert_true(logger.has("error", "query failed"))


@test(mark="medium")
async def pool_timeout_emits_structured_warning() -> None:
    """Pool acquisition timeouts are logged while preserving the public error."""

    logger = _RecordingStructuredLogger()
    database = await Database.initialize(
        logger=logger,
        database=":memory:",
        acquire_timeout=0.0,
        pool_size=1,
    )
    try:
        async with database.transaction():
            with assert_raises(PoolTimeoutError):
                async with database.transaction(timeout=0.0):
                    pass
    finally:
        await database.close()

    timeout = logger.find("connection acquisition timed out")
    assert_eq(timeout["backend"], "sqlite")
    assert_eq(timeout["timeout"], 0.0)
    assert_true(logger.has("warning", "connection acquisition timed out"))

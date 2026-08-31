"""SQLite Query Runtime stdlib logging tests.

snekql logs through the stdlib ``logging`` hierarchy rooted at the ``snekql``
logger. These tests attach a recording handler to that logger and assert on the
rendered messages and levels, mirroring how an application consumes snekql logs.
"""

from __future__ import annotations

import logging
from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path
from sqlite3 import connect
from tempfile import TemporaryDirectory
from typing import Any, cast

from snektest import assert_eq, assert_raises, assert_true, test

from snekql.sqlite import (
    PENDING_GENERATION,
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
from tests.helpers import initialized_database, migrate_models


class _RecordingHandler(logging.Handler):
    """Logging handler that keeps every record for assertions."""

    def __init__(self) -> None:
        super().__init__()
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)

    def messages(self, level: int) -> list[str]:
        """Return rendered messages recorded at exactly the given level."""

        return [
            record.getMessage() for record in self.records if record.levelno == level
        ]

    def has(self, level: int, fragment: str) -> bool:
        """Return whether a record at the level contains the fragment."""

        return any(fragment in message for message in self.messages(level))

    def find(self, level: int, fragment: str) -> str:
        """Return the first rendered message at the level containing fragment."""

        for message in self.messages(level):
            if fragment in message:
                return message
        msg = f"no {logging.getLevelName(level)} message contained {fragment!r}"
        raise AssertionError(msg)


@contextmanager
def _capture_snekql_logs() -> Generator[_RecordingHandler]:
    """Capture all ``snekql`` log records at DEBUG for the block's duration."""

    logger = logging.getLogger("snekql")
    handler = _RecordingHandler()
    previous_level = logger.level
    logger.addHandler(handler)
    logger.setLevel(logging.DEBUG)
    try:
        yield handler
    finally:
        logger.setLevel(previous_level)
        logger.removeHandler(handler)


def _execute_sql(database_path: Path, sql: str) -> None:
    connection = connect(database_path)
    try:
        _ = connection.execute(sql)
        connection.commit()
    finally:
        connection.close()


@test()
def database_initialization_takes_no_logger() -> None:
    """The public initialization path no longer accepts a logger argument."""

    initialize = cast("Any", Database.initialize)

    with assert_raises(TypeError):
        _ = initialize(database=":memory:", logger=object())


@test(mark="medium")
async def lifecycle_verbs_emit_events() -> None:
    """Initialization, migrate, and verify log backend and schema context."""

    class User[S = Pending](Model[S, "User[Fetched]"]):
        """Table model used to observe lifecycle logging."""

        id: User.GenCol[int] = Integer(
            primary_key=True,
            auto_increment=True,
            default=PENDING_GENERATION,
        )
        email: User.Col[str] = Text(nullable=False)

    with _capture_snekql_logs() as logs, TemporaryDirectory() as directory:
        database_path = Path(directory) / "app.db"
        database = await Database.initialize(database=database_path)
        await migrate_models(database, [User])
        await database.verify([User])
        await database.close()

    init_started = logs.find(logging.INFO, "database initialization started")
    migrate_started = logs.find(logging.INFO, "database migrate started")
    migrate_completed = logs.find(logging.INFO, "database migrate completed")
    applied = logs.find(logging.DEBUG, "applied")
    verify_completed = logs.find(logging.INFO, "database verify completed")
    verified = logs.find(logging.DEBUG, "verified")

    assert_true("sqlite" in init_started)
    assert_true("sqlite" in migrate_started)
    assert_true("migration(s)" in migrate_completed)
    assert_true("migration" in applied and "applied" in applied)
    assert_true("'user'" in verify_completed)
    assert_true("'user'" in verified and "verified" in verified)


@test(mark="medium")
async def warn_verify_policy_logs_drift() -> None:
    """Verify under the warn policy reports drift as a warning record."""

    class User[S = Pending](Model[S, "User[Fetched]"]):
        """Table model used for warn policy drift logging."""

        email: User.Col[str] = Text(nullable=False)

    with _capture_snekql_logs() as logs, TemporaryDirectory() as directory:
        database_path = Path(directory) / "app.db"
        _execute_sql(database_path, 'CREATE TABLE "user" ("email" TEXT NOT NULL)')

        database = await Database.initialize(database=database_path)
        await database.verify([User], policy="warn")
        await database.close()

    drift = logs.find(logging.WARNING, "schema drift detected")
    assert_true("'user'" in drift)


@test(mark="medium")
async def transaction_execution_logs_query_context() -> None:
    """Transaction logging includes SQL and params without redaction."""

    class User[S = Pending](Model[S, "User[Fetched]"]):
        """Table model used to observe query execution logging."""

        id: User.GenCol[int] = Integer(
            primary_key=True,
            auto_increment=True,
            default=PENDING_GENERATION,
        )
        email: User.Col[str] = Text(nullable=False)

    with _capture_snekql_logs() as logs:
        database = await initialized_database(
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
    write = logs.find(logging.DEBUG, "write executed")
    fetched = logs.find(logging.DEBUG, "fetch_one executed")
    assert_true("secret@example.com" in write)
    assert_true("secret@example.com" in fetched)
    assert_true(logs.has(logging.DEBUG, "transaction begin"))
    assert_true(logs.has(logging.DEBUG, "transaction commit"))


@test(mark="medium")
async def query_failure_logs_error_context() -> None:
    """Execution failures log SQL and params before raising ExecutionError."""

    class User[S = Pending](Model[S, "User[Fetched]"]):
        """Table model with a unique field used to force a write failure."""

        email: User.Col[str] = Text(nullable=False, unique=True)

    with _capture_snekql_logs() as logs:
        database = await initialized_database(
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

    failure = logs.find(logging.ERROR, "write query failed")
    assert_true("duplicate@example.com" in failure)


@test(mark="medium")
async def pool_timeout_logs_warning() -> None:
    """Pool acquisition timeouts are logged while preserving the public error."""

    with _capture_snekql_logs() as logs:
        database = await Database.initialize(
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

    timeout = logs.find(logging.WARNING, "connection acquisition timed out")
    assert_true("sqlite" in timeout)

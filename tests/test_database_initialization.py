"""Database initialization and schema verification tests."""

from __future__ import annotations

from logging import Handler, LogRecord, getLogger
from pathlib import Path
from sqlite3 import connect
from tempfile import TemporaryDirectory
from typing import Any, cast

from snektest import assert_eq, assert_raises, assert_true, test

from snekql import (
    MISSING,
    Database,
    DatabaseRuntimeError,
    Integer,
    Model,
    Pending,
    SchemaError,
    SchemaVerificationError,
    Text,
)


def _execute_sql(database_path: Path, sql: str) -> None:
    connection = connect(database_path)
    try:
        _ = connection.execute(sql)
        connection.commit()
    finally:
        connection.close()


def _fetch_create_table(database_path: Path, table_name: str) -> str:
    connection = connect(database_path)
    try:
        cursor = connection.execute(
            "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = ?",
            (table_name,),
        )
        row = cursor.fetchone()
        assert row is not None
        value = row[0]
        assert isinstance(value, str)
        return value
    finally:
        connection.close()


def _table_exists(database_path: Path, table_name: str) -> bool:
    connection = connect(database_path)
    try:
        cursor = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
            (table_name,),
        )
        return cursor.fetchone() is not None
    finally:
        connection.close()


class _CollectingHandler(Handler):
    """Logging handler that stores records for assertions."""

    def __init__(self) -> None:
        super().__init__()
        self.records: list[LogRecord] = []

    def emit(self, record: LogRecord) -> None:
        self.records.append(record)


@test(mark="medium")
async def initialize_creates_missing_strict_tables() -> None:
    """Initialization creates deterministic quoted STRICT tables."""

    class User[S = Pending](Model[S, "User[object]"]):
        """Table model used for schema creation."""

        id: User.GenCol[int] = Integer(
            primary_key=True,
            auto_increment=True,
            default=MISSING,
        )
        email: User.Col[str] = Text(nullable=False)

    with TemporaryDirectory() as directory:
        database_path = Path(directory) / "app.db"
        database = await Database.initialize(database=database_path, models=[User])
        await database.close()

        create_table = _fetch_create_table(database_path, "user")

    expected_sql = (
        'CREATE TABLE "user" ("id" INTEGER PRIMARY KEY AUTOINCREMENT, '
        + '"email" TEXT NOT NULL) STRICT'
    )
    assert_eq(create_table, expected_sql)


@test(mark="medium")
async def initialize_accepts_only_path_objects_and_exact_memory_string() -> None:
    """Only pathlib.Path and the exact in-memory database string are accepted."""

    initialize = cast(Any, Database.initialize)

    class OtherPath:
        """Path-like object that is intentionally not pathlib.Path."""

        def __fspath__(self) -> str:
            return "app.db"

    with assert_raises(TypeError):
        _ = await initialize("app.db")

    with assert_raises(DatabaseRuntimeError):
        _ = await Database.initialize(database=cast(Any, "app.db"))

    with assert_raises(DatabaseRuntimeError):
        _ = await Database.initialize(database=cast(Any, "sqlite:///app.db"))

    with assert_raises(DatabaseRuntimeError):
        _ = await Database.initialize(database=cast(Any, b"app.db"))

    with assert_raises(DatabaseRuntimeError):
        _ = await Database.initialize(database=cast(Any, OtherPath()))

    database = await Database.initialize(database=":memory:")
    await database.close()


@test(mark="medium")
async def initialize_verifies_existing_tables_after_controlled_normalization() -> None:
    """Equivalent snekql DDL with formatting differences verifies cleanly."""

    class User[S = Pending](Model[S, "User[object]"]):
        """Table model used for existing schema verification."""

        id: User.GenCol[int] = Integer(
            primary_key=True,
            auto_increment=True,
            default=MISSING,
        )
        email: User.Col[str] = Text(nullable=False)

    with TemporaryDirectory() as directory:
        database_path = Path(directory) / "app.db"
        existing_sql = (
            'CREATE TABLE "user" (\n'
            + '    "id" INTEGER PRIMARY KEY AUTOINCREMENT,\n'
            + '    "email" TEXT NOT NULL\n'
            + ") STRICT"
        )
        _execute_sql(database_path, existing_sql)

        database = await Database.initialize(database=database_path, models=[User])
        await database.close()

        create_table = _fetch_create_table(database_path, "user")

    assert_true("STRICT" in create_table)


@test(mark="medium")
async def strict_schema_policy_raises_on_schema_drift() -> None:
    """Strict schema verification rejects existing non-STRICT tables."""

    class User[S = Pending](Model[S, "User[object]"]):
        """Table model used for drift detection."""

        email: User.Col[str] = Text(nullable=False)

    with TemporaryDirectory() as directory:
        database_path = Path(directory) / "app.db"
        _execute_sql(database_path, 'CREATE TABLE "user" ("email" TEXT NOT NULL)')

        with assert_raises(SchemaVerificationError):
            _ = await Database.initialize(database=database_path, models=[User])


@test(mark="medium")
async def warn_schema_policy_logs_drift_and_continues() -> None:
    """Warn schema verification reports drift without blocking startup."""

    class User[S = Pending](Model[S, "User[object]"]):
        """Table model used for warn policy drift detection."""

        email: User.Col[str] = Text(nullable=False)

    logger = getLogger("snekql")
    handler = _CollectingHandler()
    logger.addHandler(handler)
    try:
        with TemporaryDirectory() as directory:
            database_path = Path(directory) / "app.db"
            _execute_sql(database_path, 'CREATE TABLE "user" ("email" TEXT NOT NULL)')

            database = await Database.initialize(
                database=database_path,
                models=[User],
                schema_policy="warn",
            )
            await database.close()
    finally:
        logger.removeHandler(handler)

    assert_true(
        any(
            record.getMessage() == "schema drift detected" for record in handler.records
        )
    )


@test(mark="medium")
async def duplicate_resolved_table_names_are_rejected() -> None:
    """Initialization rejects duplicate table names before schema setup."""

    class User[S = Pending](Model[S, "User[object]"]):
        """First model for duplicate table detection."""

        __tablename__ = "account"
        email: User.Col[str] = Text(nullable=False)

    class Account[S = Pending](Model[S, "Account[object]"]):
        """Second model with the same resolved table name."""

        email: Account.Col[str] = Text(nullable=False)

    with TemporaryDirectory() as directory:
        database_path = Path(directory) / "app.db"
        with assert_raises(SchemaError):
            _ = await Database.initialize(
                database=database_path,
                models=[User, Account],
            )


@test(mark="medium")
async def schema_setup_rolls_back_created_tables_on_strict_drift() -> None:
    """Schema setup is transactional for create plus verification failure."""

    class CreatedFirst[S = Pending](Model[S, "CreatedFirst[object]"]):
        """Missing table that should be rolled back."""

        email: CreatedFirst.Col[str] = Text(nullable=False)

    class ExistingDrift[S = Pending](Model[S, "ExistingDrift[object]"]):
        """Existing drift table that aborts initialization."""

        email: ExistingDrift.Col[str] = Text(nullable=False)

    with TemporaryDirectory() as directory:
        database_path = Path(directory) / "app.db"
        _execute_sql(
            database_path,
            'CREATE TABLE "existing_drift" ("email" TEXT NOT NULL)',
        )

        with assert_raises(SchemaVerificationError):
            _ = await Database.initialize(
                database=database_path,
                models=[CreatedFirst, ExistingDrift],
            )

        assert_true(not _table_exists(database_path, "created_first"))

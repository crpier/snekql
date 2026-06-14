"""SQLite Database initialization and schema verification tests."""

from __future__ import annotations

from pathlib import Path
from sqlite3 import connect
from tempfile import TemporaryDirectory
from typing import Any, ClassVar, cast

from snektest import assert_eq, assert_raises, assert_true, test

from snekql import (
    MISSING,
    Database,
    DatabaseRuntimeError,
    Fetched,
    Index,
    Integer,
    Model,
    Pending,
    SchemaError,
    SchemaVerificationError,
    Text,
    sqlite,
)
from snekql.sqlite.schema import initialize_sqlite_schema
from tests.helpers import NULL_LOGGER


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


def _fetch_create_indexes(database_path: Path, table_name: str) -> list[str]:
    connection = connect(database_path)
    try:
        cursor = connection.execute(
            """
            SELECT sql FROM sqlite_master
            WHERE type = 'index' AND tbl_name = ?
            ORDER BY rowid
            """,
            (table_name,),
        )
        values: list[str] = []
        for row in cursor.fetchall():
            value = row[0]
            assert isinstance(value, str)
            values.append(value)
        return values
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


class _RecordingStructuredLogger:
    """Structured logger fake that stores event calls for assertions."""

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


class _SchemaCursor:
    """Cursor fake that records whether schema startup closes it."""

    def __init__(self, *, fetchone_row: tuple[object, ...] | None = None) -> None:
        self.closed: bool = False
        self.fetchone_row: tuple[object, ...] | None = fetchone_row

    async def fetchone(self) -> tuple[object, ...] | None:
        return self.fetchone_row

    async def fetchall(self) -> list[tuple[object, ...]]:
        return []

    async def close(self) -> None:
        self.closed = True


class _SchemaConnection:
    """Connection fake that returns close-observable cursors for every statement."""

    def __init__(self) -> None:
        self.cursors: list[_SchemaCursor] = []

    async def execute(
        self,
        sql: str,
        params: tuple[object, ...] = (),
    ) -> _SchemaCursor:
        _ = params
        cursor = _SchemaCursor()
        self.cursors.append(cursor)
        if "sqlite_master WHERE type = 'table'" in sql:
            cursor = _SchemaCursor(fetchone_row=None)
            self.cursors[-1] = cursor
        return cursor


@test(mark="medium")
async def initialize_creates_missing_strict_tables() -> None:
    """Initialization creates deterministic quoted STRICT tables."""

    class User[S = Pending](Model[S, "User[Fetched]"]):
        """Table model used for schema creation."""

        id: User.GenCol[int] = Integer(
            primary_key=True,
            auto_increment=True,
            default=MISSING,
        )
        email: User.Col[str] = Text(nullable=False)

    with TemporaryDirectory() as directory:
        database_path = Path(directory) / "app.db"
        database = await Database.initialize(
            logger=NULL_LOGGER, database=database_path, models=[User]
        )
        await database.close()

        create_table = _fetch_create_table(database_path, "user")

    expected_sql = (
        'CREATE TABLE "user" ("id" INTEGER PRIMARY KEY AUTOINCREMENT, '
        '"email" TEXT NOT NULL) STRICT'
    )
    assert_eq(create_table, expected_sql)


@test(mark="medium")
async def initialize_emits_foreign_key_constraints_only_when_enabled() -> None:
    """`foreign_key=True` renders a REFERENCES constraint; soft refs do not."""

    class User[S = Pending](Model[S, "User[Fetched]"]):
        """Referenced table whose primary key anchors the constraint."""

        id: User.GenCol[int] = Integer(
            primary_key=True,
            auto_increment=True,
            default=MISSING,
        )
        email: User.Col[str] = Text(nullable=False)

    class Order[S = Pending](Model[S, "Order[Fetched]"]):
        """Table with an enforced and a typed-only reference to ``User``."""

        id: Order.GenCol[int] = Integer(
            primary_key=True,
            auto_increment=True,
            default=MISSING,
        )
        user_id: Order.FKCol[User, int] = Integer(foreign_key=True)
        soft_user_id: Order.FKCol[User, int] = Integer(nullable=False)
        note: Order.Col[str] = Text(nullable=False)

    with TemporaryDirectory() as directory:
        database_path = Path(directory) / "app.db"
        database = await Database.initialize(
            logger=NULL_LOGGER, database=database_path, models=[User, Order]
        )
        await database.close()

        create_table = _fetch_create_table(database_path, "order")

    expected_sql = (
        'CREATE TABLE "order" ("id" INTEGER PRIMARY KEY AUTOINCREMENT, '
        '"user_id" INTEGER, "soft_user_id" INTEGER NOT NULL, '
        '"note" TEXT NOT NULL, '
        'FOREIGN KEY ("user_id") REFERENCES "user" ("id")) STRICT'
    )
    assert_eq(create_table, expected_sql)


@test(mark="medium")
async def strict_schema_policy_raises_when_a_foreign_key_constraint_is_missing() -> (
    None
):
    """An existing table lacking a managed FK constraint is strict-policy drift."""

    class User[S = Pending](Model[S, "User[Fetched]"]):
        """Referenced table for foreign-key drift detection."""

        id: User.GenCol[int] = Integer(
            primary_key=True,
            auto_increment=True,
            default=MISSING,
        )

    class Order[S = Pending](Model[S, "Order[Fetched]"]):
        """Table whose model declares a constraint absent from the database."""

        id: Order.GenCol[int] = Integer(
            primary_key=True,
            auto_increment=True,
            default=MISSING,
        )
        user_id: Order.FKCol[User, int] = Integer(foreign_key=True)

    with TemporaryDirectory() as directory:
        database_path = Path(directory) / "app.db"
        order_sql = (
            'CREATE TABLE "order" ("id" INTEGER PRIMARY KEY AUTOINCREMENT, '
            '"user_id" INTEGER) STRICT'
        )
        _execute_sql(
            database_path,
            'CREATE TABLE "user" ("id" INTEGER PRIMARY KEY AUTOINCREMENT) STRICT',
        )
        _execute_sql(database_path, order_sql)

        with assert_raises(SchemaVerificationError):
            _ = await Database.initialize(
                logger=NULL_LOGGER, database=database_path, models=[User, Order]
            )


@test(mark="medium")
async def initialize_accepts_sqlite_config_object() -> None:
    """SQLite configuration objects select the SQLite runtime explicitly."""

    class User[S = Pending](sqlite.Model[S, "User[Fetched]"]):
        """Table model used for SQLite config initialization."""

        id: User.GenCol[int] = sqlite.Integer(
            primary_key=True,
            auto_increment=True,
            default=MISSING,
        )
        email: User.Col[str] = sqlite.Text(nullable=False)

    with TemporaryDirectory() as directory:
        database_path = Path(directory) / "app.db"
        config = sqlite.Config(database=database_path, pool_size=2)
        database = await Database.initialize(config, logger=NULL_LOGGER, models=[User])
        await database.close()

        create_table = _fetch_create_table(database_path, "user")

    expected_sql = (
        'CREATE TABLE "user" ("id" INTEGER PRIMARY KEY AUTOINCREMENT, '
        '"email" TEXT NOT NULL) STRICT'
    )
    assert_eq(create_table, expected_sql)


@test(mark="medium")
async def initialize_rejects_mixed_sqlite_config_and_legacy_database() -> None:
    """A backend config cannot be combined with legacy database arguments."""

    with TemporaryDirectory() as directory:
        database_path = Path(directory) / "app.db"
        config = sqlite.Config(database=database_path)

        initialize = cast("Any", Database.initialize)

        with assert_raises(DatabaseRuntimeError):
            _ = await initialize(config, logger=NULL_LOGGER, database=database_path)


@test(mark="medium")
async def initialize_creates_column_unique_indexes_after_tables() -> None:
    """Column unique declarations create separate deterministic unique indexes."""

    class User[S = Pending](Model[S, "User[Fetched]"]):
        """Table model with a unique public identifier."""

        email: User.Col[str] = Text(nullable=False, unique=True)
        status: User.Col[str] = Text(nullable=False)

    with TemporaryDirectory() as directory:
        database_path = Path(directory) / "app.db"
        database = await Database.initialize(
            logger=NULL_LOGGER, database=database_path, models=[User]
        )
        await database.close()

        create_table = _fetch_create_table(database_path, "user")
        create_indexes = _fetch_create_indexes(database_path, "user")

    assert_eq(
        create_table,
        'CREATE TABLE "user" ("email" TEXT NOT NULL, "status" TEXT NOT NULL) STRICT',
    )
    assert_eq(
        create_indexes,
        ['CREATE UNIQUE INDEX "ux_user_email" ON "user" ("email")'],
    )


@test(mark="medium")
async def initialize_creates_table_indexes_in_declaration_order() -> None:
    """Table index declarations create deterministic index SQL after uniques."""

    class User[S = Pending](Model[S, "User[Fetched]"]):
        """Table model with single and composite table indexes."""

        email: User.Col[str] = Text(nullable=False, unique=True)
        status: User.Col[str] = Text(nullable=False)
        tenant_id: User.Col[int] = Integer(nullable=False)

        __indexes__: ClassVar[list[Index[Any]]] = [
            Index(status),
            Index(tenant_id, email, unique=True),
            Index(tenant_id, name="ix_user_tenant_custom"),
        ]

    with TemporaryDirectory() as directory:
        database_path = Path(directory) / "app.db"
        database = await Database.initialize(
            logger=NULL_LOGGER, database=database_path, models=[User]
        )
        await database.close()

        create_indexes = _fetch_create_indexes(database_path, "user")

    assert_eq(
        create_indexes,
        [
            'CREATE UNIQUE INDEX "ux_user_email" ON "user" ("email")',
            'CREATE INDEX "ix_user_status" ON "user" ("status")',
            'CREATE UNIQUE INDEX "ux_user_tenant_id_email" ON "user" ("tenant_id", "email")',
            'CREATE INDEX "ix_user_tenant_custom" ON "user" ("tenant_id")',
        ],
    )


@test(mark="medium")
async def initialize_accepts_only_path_objects_and_exact_memory_string() -> None:
    """Only pathlib.Path and the exact in-memory database string are accepted."""

    initialize = cast("Any", Database.initialize)

    class OtherPath:
        """Path-like object that is intentionally not pathlib.Path."""

        def __fspath__(self) -> str:
            return "app.db"

    with assert_raises(DatabaseRuntimeError):
        _ = await initialize(logger=NULL_LOGGER, database="app.db")

    with assert_raises(DatabaseRuntimeError):
        _ = await Database.initialize(
            logger=NULL_LOGGER, database=cast("Any", "app.db")
        )

    with assert_raises(DatabaseRuntimeError):
        _ = await Database.initialize(
            logger=NULL_LOGGER, database=cast("Any", "sqlite:///app.db")
        )

    with assert_raises(DatabaseRuntimeError):
        _ = await Database.initialize(
            logger=NULL_LOGGER, database=cast("Any", b"app.db")
        )

    with assert_raises(DatabaseRuntimeError):
        _ = await Database.initialize(
            logger=NULL_LOGGER, database=cast("Any", OtherPath())
        )

    database = await Database.initialize(logger=NULL_LOGGER, database=":memory:")
    await database.close()


@test(mark="medium")
async def initialize_verifies_existing_tables_after_controlled_normalization() -> None:
    """Equivalent snekql DDL with formatting differences verifies cleanly."""

    class User[S = Pending](Model[S, "User[Fetched]"]):
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
            '    "id" INTEGER PRIMARY KEY AUTOINCREMENT,\n'
            '    "email" TEXT NOT NULL\n'
            ") STRICT"
        )
        _execute_sql(database_path, existing_sql)

        database = await Database.initialize(
            logger=NULL_LOGGER, database=database_path, models=[User]
        )
        await database.close()

        create_table = _fetch_create_table(database_path, "user")

    assert_true("STRICT" in create_table)


@test(mark="medium")
async def strict_schema_policy_raises_on_index_drift() -> None:
    """Strict schema verification rejects missing managed indexes."""

    class User[S = Pending](Model[S, "User[Fetched]"]):
        """Table model requiring an index for verification."""

        email: User.Col[str] = Text(nullable=False, unique=True)

    with TemporaryDirectory() as directory:
        database_path = Path(directory) / "app.db"
        _execute_sql(
            database_path, 'CREATE TABLE "user" ("email" TEXT NOT NULL) STRICT'
        )

        with assert_raises(SchemaVerificationError):
            _ = await Database.initialize(
                logger=NULL_LOGGER, database=database_path, models=[User]
            )


@test(mark="medium")
async def duplicate_resolved_index_names_are_rejected() -> None:
    """Initialization rejects duplicate index names across configured models."""

    class User[S = Pending](Model[S, "User[Fetched]"]):
        """First model using an explicit index name."""

        email: User.Col[str] = Text(nullable=False)
        __indexes__: ClassVar[list[Index[Any]]] = [
            Index(email, name="ix_conflict"),
        ]

    class Account[S = Pending](Model[S, "Account[Fetched]"]):
        """Second model reusing the explicit index name."""

        email: Account.Col[str] = Text(nullable=False)
        __indexes__: ClassVar[list[Index[Any]]] = [
            Index(email, name="ix_conflict"),
        ]

    with TemporaryDirectory() as directory:
        database_path = Path(directory) / "app.db"
        with assert_raises(SchemaError):
            _ = await Database.initialize(
                logger=NULL_LOGGER,
                database=database_path,
                models=[User, Account],
            )


@test(mark="medium")
async def strict_schema_policy_raises_on_schema_drift() -> None:
    """Strict schema verification rejects existing non-STRICT tables."""

    class User[S = Pending](Model[S, "User[Fetched]"]):
        """Table model used for drift detection."""

        email: User.Col[str] = Text(nullable=False)

    with TemporaryDirectory() as directory:
        database_path = Path(directory) / "app.db"
        _execute_sql(database_path, 'CREATE TABLE "user" ("email" TEXT NOT NULL)')

        with assert_raises(SchemaVerificationError):
            _ = await Database.initialize(
                logger=NULL_LOGGER, database=database_path, models=[User]
            )


@test(mark="medium")
async def warn_schema_policy_logs_drift_and_continues() -> None:
    """Warn schema verification reports drift without blocking startup."""

    class User[S = Pending](Model[S, "User[Fetched]"]):
        """Table model used for warn policy drift detection."""

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

    assert_true(
        any(
            level == "warning" and event == "schema drift detected"
            for level, event, _fields in logger.events
        )
    )


@test(mark="medium")
async def duplicate_resolved_table_names_are_rejected() -> None:
    """Initialization rejects duplicate table names before schema setup."""

    class User[S = Pending](Model[S, "User[Fetched]"]):
        """First model for duplicate table detection."""

        __tablename__ = "account"
        email: User.Col[str] = Text(nullable=False)

    class Account[S = Pending](Model[S, "Account[Fetched]"]):
        """Second model with the same resolved table name."""

        email: Account.Col[str] = Text(nullable=False)

    with TemporaryDirectory() as directory:
        database_path = Path(directory) / "app.db"
        with assert_raises(SchemaError):
            _ = await Database.initialize(
                logger=NULL_LOGGER,
                database=database_path,
                models=[User, Account],
            )


@test(mark="medium")
async def schema_setup_rolls_back_created_tables_on_strict_drift() -> None:
    """Schema setup is transactional for create plus verification failure."""

    class CreatedFirst[S = Pending](Model[S, "CreatedFirst[Fetched]"]):
        """Missing table that should be rolled back."""

        email: CreatedFirst.Col[str] = Text(nullable=False)

    class ExistingDrift[S = Pending](Model[S, "ExistingDrift[Fetched]"]):
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
                logger=NULL_LOGGER,
                database=database_path,
                models=[CreatedFirst, ExistingDrift],
            )

        assert_true(not _table_exists(database_path, "created_first"))


@test(mark="fast")
async def schema_startup_closes_ddl_and_control_cursors() -> None:
    """SQLite schema startup closes cursors returned by DDL/control statements."""

    class User[S = Pending](Model[S, "User[Fetched]"]):
        """Model used to force BEGIN, DDL, metadata fetch, and COMMIT."""

        email: User.Col[str] = Text(nullable=False)

    connection = _SchemaConnection()

    await initialize_sqlite_schema(
        cast("Any", connection),
        [User],
        "strict",
        logger=NULL_LOGGER,
    )

    assert connection.cursors
    assert_true(all(cursor.closed for cursor in connection.cursors))

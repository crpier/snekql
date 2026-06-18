"""MariaDB schema startup and drift verification tests."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, ClassVar, cast

from snektest import (
    AsyncFixture,
    assert_eq,
    assert_raises,
    assert_true,
    load_fixture,
    test,
)

from snekql import mariadb
from snekql.mariadb import (
    MISSING,
    Database,
    Fetched,
    Index,
    Pending,
    SchemaError,
    SchemaPolicy,
    SchemaVerificationError,
    StructuredLogger,
)
from snekql.model import Table
from tests.helpers import NULL_LOGGER, TemporaryMariaDBServer, provide_mariadb_server


@dataclass(frozen=True)
class _DatabaseSession:
    """Initialized database plus the backing MariaDB server fixture."""

    database: Database
    server: TemporaryMariaDBServer


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


async def _fetch_index_rows(
    server: TemporaryMariaDBServer, table_name: str
) -> list[tuple[str, str, str]]:
    """Fetch non-primary index metadata from MariaDB information_schema."""

    result = await server.run_sql(
        f"""
        SELECT INDEX_NAME, NON_UNIQUE, GROUP_CONCAT(COLUMN_NAME ORDER BY SEQ_IN_INDEX)
        FROM INFORMATION_SCHEMA.STATISTICS
        WHERE TABLE_SCHEMA = DATABASE()
          AND TABLE_NAME = '{table_name}'
          AND INDEX_NAME <> 'PRIMARY'
        GROUP BY INDEX_NAME, NON_UNIQUE
        ORDER BY INDEX_NAME
        """,
    )
    lines = [line for line in result.stdout.splitlines() if line]
    return [cast("tuple[str, str, str]", tuple(line.split("\t"))) for line in lines[1:]]


async def database_session(
    models: Sequence[type[Table[Any]]] = (),
    *,
    logger: StructuredLogger = NULL_LOGGER,
    schema_policy: SchemaPolicy = "strict",
    setup_sql: Sequence[str] = (),
) -> AsyncFixture[_DatabaseSession]:
    """Provide an initialized MariaDB Database and close it after the test."""

    server = await load_fixture(provide_mariadb_server())
    for sql in setup_sql:
        _ = await server.run_sql(sql)
    database = await Database.initialize(
        server.config(),
        logger=logger,
        models=models,
        schema_policy=schema_policy,
    )
    try:
        yield _DatabaseSession(database=database, server=server)
    finally:
        await database.close()


@test(mark="medium")
async def mariadb_schema_creates_column_unique_indexes() -> None:
    """MariaDB startup creates column unique indexes."""

    class User[S = Pending](mariadb.Model[S, "User[Fetched]"]):
        """Table model with a MariaDB column unique index."""

        __tablename__ = "issue39_user_column_unique_indexes"

        id: User.GenCol[int] = mariadb.Integer(
            primary_key=True,
            auto_increment=True,
            default=MISSING,
        )
        email: User.Col[str] = mariadb.Text(nullable=False, unique=True)

    session = await load_fixture(database_session([User]))

    assert_eq(
        await _fetch_index_rows(session.server, "issue39_user_column_unique_indexes"),
        [("ux_issue39_user_column_unique_indexes_email", "0", "email")],
    )


@test(mark="medium")
async def mariadb_schema_creates_table_indexes() -> None:
    """MariaDB startup creates declared table indexes."""

    class User[S = Pending](mariadb.Model[S, "User[Fetched]"]):
        """Table model with MariaDB table indexes."""

        __tablename__ = "issue39_user_table_indexes"

        id: User.GenCol[int] = mariadb.Integer(
            primary_key=True,
            auto_increment=True,
            default=MISSING,
        )
        email: User.Col[str] = mariadb.Text(nullable=False)
        status: User.Col[str] = mariadb.Text(nullable=False)
        tenant_id: User.Col[int] = mariadb.Integer(nullable=False)

        __indexes__: ClassVar[list[Index[Any]]] = [
            Index(status),
            Index(tenant_id, email, unique=True),
        ]

    session = await load_fixture(database_session([User]))

    assert_eq(
        await _fetch_index_rows(session.server, "issue39_user_table_indexes"),
        [
            ("ix_issue39_user_table_indexes_status", "1", "status"),
            ("ux_issue39_user_table_indexes_tenant_id_email", "0", "tenant_id,email"),
        ],
    )


@test(mark="medium")
async def mariadb_schema_rejects_duplicate_index_names_before_mutation() -> None:
    """Duplicate resolved index names are rejected before creating tables."""

    server = await load_fixture(provide_mariadb_server())

    class User[S = Pending](mariadb.Model[S, "User[Fetched]"]):
        """First model using a duplicate index name."""

        __tablename__ = "issue39_duplicate_user"
        email: User.Col[str] = mariadb.Text(nullable=False)
        __indexes__: ClassVar[list[Index[Any]]] = [Index(email, name="ix_duplicate")]

    class Org[S = Pending](mariadb.Model[S, "Org[Fetched]"]):
        """Second model using a duplicate index name."""

        __tablename__ = "issue39_duplicate_org"
        name: Org.Col[str] = mariadb.Text(nullable=False)
        __indexes__: ClassVar[list[Index[Any]]] = [Index(name, name="ix_duplicate")]

    with assert_raises(SchemaError):
        _ = await Database.initialize(
            server.config(), logger=NULL_LOGGER, models=[User, Org]
        )

    result = await server.run_sql(
        """
        SELECT COUNT(*)
        FROM INFORMATION_SCHEMA.TABLES
        WHERE TABLE_SCHEMA = DATABASE()
          AND TABLE_NAME IN ('issue39_duplicate_user', 'issue39_duplicate_org')
        """,
    )
    assert_eq(result.stdout.splitlines()[-1], "0")


@test(mark="medium")
async def mariadb_strict_schema_policy_raises_on_table_drift() -> None:
    """Strict MariaDB schema verification rejects existing table drift."""

    server = await load_fixture(provide_mariadb_server())

    class User[S = Pending](mariadb.Model[S, "User[Fetched]"]):
        """Model that expects more columns than the existing table."""

        __tablename__ = "issue39_table_drift"
        id: User.GenCol[int] = mariadb.Integer(
            primary_key=True,
            auto_increment=True,
            default=MISSING,
        )
        email: User.Col[str] = mariadb.Text(nullable=False)

    _ = await server.run_sql("CREATE TABLE issue39_table_drift (`email` VARCHAR(255))")

    with assert_raises(SchemaVerificationError):
        _ = await Database.initialize(
            server.config(), logger=NULL_LOGGER, models=[User]
        )


@test(mark="medium")
async def mariadb_strict_schema_policy_raises_on_index_drift() -> None:
    """Strict MariaDB schema verification rejects missing managed indexes."""

    server = await load_fixture(provide_mariadb_server())

    class User[S = Pending](mariadb.Model[S, "User[Fetched]"]):
        """Model that expects a unique index absent from the existing table."""

        __tablename__ = "issue39_index_drift"
        email: User.Col[str] = mariadb.Text(nullable=False, unique=True)

    _ = await server.run_sql(
        "CREATE TABLE issue39_index_drift (`email` VARCHAR(255) NOT NULL)"
    )

    with assert_raises(SchemaVerificationError):
        _ = await Database.initialize(
            server.config(), logger=NULL_LOGGER, models=[User]
        )


@test(mark="medium")
async def mariadb_warn_schema_policy_logs_drift_and_continues() -> None:
    """Warn policy logs MariaDB schema drift without rejecting startup."""

    class User[S = Pending](mariadb.Model[S, "User[Fetched]"]):
        """Model used for warn-policy drift verification."""

        __tablename__ = "issue39_warn_drift"
        id: User.GenCol[int] = mariadb.Integer(
            primary_key=True,
            auto_increment=True,
            default=MISSING,
        )
        email: User.Col[str] = mariadb.Text(nullable=False)

    logger = _RecordingStructuredLogger()
    _session = await load_fixture(
        database_session(
            [User],
            logger=logger,
            schema_policy="warn",
            setup_sql=["CREATE TABLE issue39_warn_drift (`email` VARCHAR(255))"],
        )
    )

    warnings = [
        fields
        for level, event, fields in logger.events
        if level == "warning" and event == "schema drift detected"
    ]
    assert_eq(len(warnings), 1)
    assert_eq(warnings[0]["table_name"], "issue39_warn_drift")


@test(mark="medium")
async def mariadb_reordered_columns_verify_semantically() -> None:
    """A live table whose columns are in a different order is not drift."""

    class User[S = Pending](mariadb.Model[S, "User[Fetched]"]):
        """Model verified against a semantically equal, reordered live table."""

        __tablename__ = "issue119_reordered"
        id: User.GenCol[int] = mariadb.Integer(
            primary_key=True,
            auto_increment=True,
            default=MISSING,
        )
        email: User.Col[str] = mariadb.Text(nullable=False)

    # Columns declared in the opposite order to the model: semantically identical.
    create_sql = (
        "CREATE TABLE issue119_reordered ("
        "`email` VARCHAR(255) CHARACTER SET utf8mb4 COLLATE utf8mb4_bin NOT NULL, "
        "`id` BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY"
        ") ENGINE=InnoDB"
    )
    session = await load_fixture(database_session([User], setup_sql=[create_sql]))

    assert_eq(
        await _fetch_index_rows(session.server, "issue119_reordered"),
        [],
    )


@test(mark="medium")
async def mariadb_strict_drift_error_names_the_divergent_column() -> None:
    """A column whose nullability diverges is named precisely in the error."""

    server = await load_fixture(provide_mariadb_server())

    class User[S = Pending](mariadb.Model[S, "User[Fetched]"]):
        """Model whose email is NOT NULL while the live column is nullable."""

        __tablename__ = "issue119_column_drift"
        id: User.GenCol[int] = mariadb.Integer(
            primary_key=True,
            auto_increment=True,
            default=MISSING,
        )
        email: User.Col[str] = mariadb.Text(nullable=False)

    create_sql = (
        "CREATE TABLE issue119_column_drift ("
        "`id` BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY, "
        "`email` VARCHAR(255) CHARACTER SET utf8mb4 COLLATE utf8mb4_bin"
        ") ENGINE=InnoDB"
    )
    _ = await server.run_sql(create_sql)

    with assert_raises(SchemaVerificationError) as raised:
        _ = await Database.initialize(
            server.config(), logger=NULL_LOGGER, models=[User]
        )

    message = str(raised.exception)
    assert_true("'email'" in message)
    assert_true("nullable" in message)

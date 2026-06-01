"""MariaDB schema startup and drift verification tests."""

from __future__ import annotations

from logging import Handler, LogRecord, getLogger
from typing import Any, ClassVar, cast

from snektest import assert_eq, assert_raises, load_fixture, test

from snekql import (
    MISSING,
    Database,
    Index,
    Pending,
    SchemaError,
    SchemaVerificationError,
    mariadb,
)
from tests.mariadb_server import MariaDBServer, provide_mariadb_server


class _CollectingHandler(Handler):
    """Logging handler that stores records for assertions."""

    def __init__(self) -> None:
        super().__init__()
        self.records: list[LogRecord] = []

    def emit(self, record: LogRecord) -> None:
        self.records.append(record)


def _config_from_server(server: MariaDBServer) -> mariadb.Config:
    """Build a MariaDB config for the shared local test server."""

    return mariadb.Config(
        database=server.database,
        host=server.host,
        port=server.port,
        user=server.user,
    )


def _fetch_index_rows(
    server: MariaDBServer, table_name: str
) -> list[tuple[str, str, str]]:
    """Fetch non-primary index metadata from MariaDB information_schema."""

    result = server.run_sql(
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


@test(mark="medium")
async def mariadb_schema_creates_unique_and_table_indexes() -> None:
    """MariaDB startup creates column unique indexes and table indexes."""

    class User[S = Pending](mariadb.Model[S, "User[object]"]):
        """Table model with MariaDB indexes."""

        __tablename__ = "issue39_user_indexes"

        id: User.GenCol[int] = mariadb.Integer(
            primary_key=True,
            auto_increment=True,
            default=MISSING,
        )
        email: User.Col[str] = mariadb.Text(nullable=False, unique=True)
        status: User.Col[str] = mariadb.Text(nullable=False)
        tenant_id: User.Col[int] = mariadb.Integer(nullable=False)

        __indexes__: ClassVar[list[Index[Any]]] = [
            Index(status),
            Index(tenant_id, email, unique=True),
        ]

    server = load_fixture(provide_mariadb_server())
    database = await Database.initialize(_config_from_server(server), models=[User])
    await database.close()

    assert_eq(
        _fetch_index_rows(server, "issue39_user_indexes"),
        [
            ("ix_issue39_user_indexes_status", "1", "status"),
            ("ux_issue39_user_indexes_email", "0", "email"),
            ("ux_issue39_user_indexes_tenant_id_email", "0", "tenant_id,email"),
        ],
    )


@test(mark="medium")
async def mariadb_schema_rejects_duplicate_index_names_before_mutation() -> None:
    """Duplicate resolved index names are rejected before creating tables."""

    class User[S = Pending](mariadb.Model[S, "User[object]"]):
        """First model using a duplicate index name."""

        __tablename__ = "issue39_duplicate_user"
        email: User.Col[str] = mariadb.Text(nullable=False)
        __indexes__: ClassVar[list[Index[Any]]] = [Index(email, name="ix_duplicate")]

    class Org[S = Pending](mariadb.Model[S, "Org[object]"]):
        """Second model using a duplicate index name."""

        __tablename__ = "issue39_duplicate_org"
        name: Org.Col[str] = mariadb.Text(nullable=False)
        __indexes__: ClassVar[list[Index[Any]]] = [Index(name, name="ix_duplicate")]

    server = load_fixture(provide_mariadb_server())

    with assert_raises(SchemaError):
        _ = await Database.initialize(_config_from_server(server), models=[User, Org])

    result = server.run_sql(
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

    class User[S = Pending](mariadb.Model[S, "User[object]"]):
        """Model that expects more columns than the existing table."""

        __tablename__ = "issue39_table_drift"
        id: User.GenCol[int] = mariadb.Integer(
            primary_key=True,
            auto_increment=True,
            default=MISSING,
        )
        email: User.Col[str] = mariadb.Text(nullable=False)

    server = load_fixture(provide_mariadb_server())
    _ = server.run_sql("CREATE TABLE issue39_table_drift (`email` VARCHAR(255))")

    with assert_raises(SchemaVerificationError):
        _ = await Database.initialize(_config_from_server(server), models=[User])


@test(mark="medium")
async def mariadb_strict_schema_policy_raises_on_index_drift() -> None:
    """Strict MariaDB schema verification rejects missing managed indexes."""

    class User[S = Pending](mariadb.Model[S, "User[object]"]):
        """Model that expects a unique index absent from the existing table."""

        __tablename__ = "issue39_index_drift"
        email: User.Col[str] = mariadb.Text(nullable=False, unique=True)

    server = load_fixture(provide_mariadb_server())
    _ = server.run_sql(
        "CREATE TABLE issue39_index_drift (`email` VARCHAR(255) NOT NULL)"
    )

    with assert_raises(SchemaVerificationError):
        _ = await Database.initialize(_config_from_server(server), models=[User])


@test(mark="medium")
async def mariadb_warn_schema_policy_logs_drift_and_continues() -> None:
    """Warn policy logs MariaDB schema drift without rejecting startup."""

    class User[S = Pending](mariadb.Model[S, "User[object]"]):
        """Model used for warn-policy drift verification."""

        __tablename__ = "issue39_warn_drift"
        id: User.GenCol[int] = mariadb.Integer(
            primary_key=True,
            auto_increment=True,
            default=MISSING,
        )
        email: User.Col[str] = mariadb.Text(nullable=False)

    server = load_fixture(provide_mariadb_server())
    _ = server.run_sql("CREATE TABLE issue39_warn_drift (`email` VARCHAR(255))")
    logger = getLogger("snekql")
    handler = _CollectingHandler()
    logger.addHandler(handler)
    try:
        database = await Database.initialize(
            _config_from_server(server),
            models=[User],
            schema_policy="warn",
        )
        await database.close()
    finally:
        logger.removeHandler(handler)

    assert_eq(len(handler.records), 1)
    assert_eq(handler.records[0].getMessage(), "schema drift detected")

"""MariaDB schema startup and drift verification tests."""

from __future__ import annotations

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
from tests.logging_helpers import NULL_LOGGER
from tests.mariadb_server import TemporaryMariaDBServer, provide_mariadb_server


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


def _config_from_server(server: TemporaryMariaDBServer) -> mariadb.Config:
    """Build a MariaDB config for the shared local test server."""

    return server.config()


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


@test(mark="medium")
async def mariadb_schema_creates_unique_and_table_indexes() -> None:
    """MariaDB startup creates column unique indexes and table indexes."""

    server = await load_fixture(provide_mariadb_server())

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

    database = await Database.initialize(
        NULL_LOGGER, _config_from_server(server), models=[User]
    )
    await database.close()

    assert_eq(
        await _fetch_index_rows(server, "issue39_user_indexes"),
        [
            ("ix_issue39_user_indexes_status", "1", "status"),
            ("ux_issue39_user_indexes_email", "0", "email"),
            ("ux_issue39_user_indexes_tenant_id_email", "0", "tenant_id,email"),
        ],
    )


@test(mark="medium")
async def mariadb_schema_rejects_duplicate_index_names_before_mutation() -> None:
    """Duplicate resolved index names are rejected before creating tables."""

    server = await load_fixture(provide_mariadb_server())

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

    with assert_raises(SchemaError):
        _ = await Database.initialize(
            NULL_LOGGER, _config_from_server(server), models=[User, Org]
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

    class User[S = Pending](mariadb.Model[S, "User[object]"]):
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
            NULL_LOGGER, _config_from_server(server), models=[User]
        )


@test(mark="medium")
async def mariadb_strict_schema_policy_raises_on_index_drift() -> None:
    """Strict MariaDB schema verification rejects missing managed indexes."""

    server = await load_fixture(provide_mariadb_server())

    class User[S = Pending](mariadb.Model[S, "User[object]"]):
        """Model that expects a unique index absent from the existing table."""

        __tablename__ = "issue39_index_drift"
        email: User.Col[str] = mariadb.Text(nullable=False, unique=True)

    _ = await server.run_sql(
        "CREATE TABLE issue39_index_drift (`email` VARCHAR(255) NOT NULL)"
    )

    with assert_raises(SchemaVerificationError):
        _ = await Database.initialize(
            NULL_LOGGER, _config_from_server(server), models=[User]
        )


@test(mark="medium")
async def mariadb_warn_schema_policy_logs_drift_and_continues() -> None:
    """Warn policy logs MariaDB schema drift without rejecting startup."""

    server = await load_fixture(provide_mariadb_server())

    class User[S = Pending](mariadb.Model[S, "User[object]"]):
        """Model used for warn-policy drift verification."""

        __tablename__ = "issue39_warn_drift"
        id: User.GenCol[int] = mariadb.Integer(
            primary_key=True,
            auto_increment=True,
            default=MISSING,
        )
        email: User.Col[str] = mariadb.Text(nullable=False)

    _ = await server.run_sql("CREATE TABLE issue39_warn_drift (`email` VARCHAR(255))")
    logger = _RecordingStructuredLogger()
    database = await Database.initialize(
        logger,
        _config_from_server(server),
        models=[User],
        schema_policy="warn",
    )
    await database.close()

    warnings = [
        fields
        for level, event, fields in logger.events
        if level == "warning" and event == "schema drift detected"
    ]
    assert_eq(len(warnings), 1)
    assert_eq(warnings[0]["table_name"], "issue39_warn_drift")

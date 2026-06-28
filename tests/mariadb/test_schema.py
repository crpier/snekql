"""MariaDB schema startup and drift verification tests."""

from __future__ import annotations

import logging
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
    PENDING_GENERATION,
    Database,
    Fetched,
    Index,
    Pending,
    SchemaError,
    SchemaPolicy,
    SchemaVerificationError,
)
from snekql.model import Table
from tests.helpers import (
    TemporaryMariaDBServer,
    capture_snekql_logs,
    migrate_models,
    provide_mariadb_server,
)


@dataclass(frozen=True)
class _DatabaseSession:
    """Initialized database plus the backing MariaDB server fixture."""

    database: Database
    server: TemporaryMariaDBServer


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
    schema_policy: SchemaPolicy = "strict",
    setup_sql: Sequence[str] = (),
) -> AsyncFixture[_DatabaseSession]:
    """Provide an initialized MariaDB Database and close it after the test."""

    server = await load_fixture(provide_mariadb_server())
    for sql in setup_sql:
        _ = await server.run_sql(sql)
    database = await Database.initialize(server.config())
    try:
        if setup_sql:
            # The table already exists: verify the live schema against the models.
            await database.verify(models, policy=schema_policy)
        elif models:
            # Build the schema by replaying the scaffolded migration chain.
            await migrate_models(database, models)
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
            default=PENDING_GENERATION,
        )
        email: User.Col[str] = mariadb.Text(nullable=False, unique=True)

    session = await load_fixture(database_session([User]))

    assert_eq(
        await _fetch_index_rows(session.server, "issue39_user_column_unique_indexes"),
        [("ux_issue39_user_column_unique_indexes_email", "0", "email")],
    )


@test(mark="medium")
async def mariadb_schema_creates_column_non_unique_indexes() -> None:
    """MariaDB startup creates column ``index=True`` non-unique indexes."""

    class User[S = Pending](mariadb.Model[S, "User[Fetched]"]):
        """Table model with a MariaDB column non-unique index."""

        __tablename__ = "issue146_user_column_non_unique_indexes"

        id: User.GenCol[int] = mariadb.Integer(
            primary_key=True,
            auto_increment=True,
            default=PENDING_GENERATION,
        )
        status: User.Col[str] = mariadb.Text(nullable=False, index=True)

    session = await load_fixture(database_session([User]))

    assert_eq(
        await _fetch_index_rows(
            session.server,
            "issue146_user_column_non_unique_indexes",
        ),
        [("ix_issue146_user_column_non_unique_indexes_status", "1", "status")],
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
            default=PENDING_GENERATION,
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

    database = await Database.initialize(server.config())
    try:
        with assert_raises(SchemaError):
            await database.verify([User, Org])
    finally:
        await database.close()

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
            default=PENDING_GENERATION,
        )
        email: User.Col[str] = mariadb.Text(nullable=False)

    _ = await server.run_sql("CREATE TABLE issue39_table_drift (`email` VARCHAR(255))")

    database = await Database.initialize(server.config())
    try:
        with assert_raises(SchemaVerificationError):
            await database.verify([User])
    finally:
        await database.close()


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

    database = await Database.initialize(server.config())
    try:
        with assert_raises(SchemaVerificationError):
            await database.verify([User])
    finally:
        await database.close()


@test(mark="medium")
async def mariadb_warn_schema_policy_logs_drift_and_continues() -> None:
    """Warn policy logs MariaDB schema drift without rejecting startup."""

    class User[S = Pending](mariadb.Model[S, "User[Fetched]"]):
        """Model used for warn-policy drift verification."""

        __tablename__ = "issue39_warn_drift"
        id: User.GenCol[int] = mariadb.Integer(
            primary_key=True,
            auto_increment=True,
            default=PENDING_GENERATION,
        )
        email: User.Col[str] = mariadb.Text(nullable=False)

    with capture_snekql_logs() as logs:
        _ = await load_fixture(
            database_session(
                [User],
                schema_policy="warn",
                setup_sql=["CREATE TABLE issue39_warn_drift (`email` VARCHAR(255))"],
            )
        )

    drift_warnings = [
        message
        for message in logs.messages(logging.WARNING)
        if "schema drift detected" in message
    ]
    assert_eq(len(drift_warnings), 1)
    assert_true("issue39_warn_drift" in drift_warnings[0])


@test(mark="medium")
async def mariadb_reordered_columns_verify_semantically() -> None:
    """A live table whose columns are in a different order is not drift."""

    class User[S = Pending](mariadb.Model[S, "User[Fetched]"]):
        """Model verified against a semantically equal, reordered live table."""

        __tablename__ = "issue119_reordered"
        id: User.GenCol[int] = mariadb.Integer(
            primary_key=True,
            auto_increment=True,
            default=PENDING_GENERATION,
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
async def mariadb_boolean_tinyint_alias_verifies_clean() -> None:
    """``BOOLEAN`` is a ``TINYINT(1)`` alias; either spelling is not drift."""

    class Flag[S = Pending](mariadb.Model[S, "Flag[Fetched]"]):
        """Model whose boolean column is migrated as the underlying TINYINT(1)."""

        __tablename__ = "issue58_boolean_alias"
        id: Flag.GenCol[int] = mariadb.Integer(
            primary_key=True,
            auto_increment=True,
            default=PENDING_GENERATION,
        )
        active: Flag.Col[bool] = mariadb.Boolean(nullable=False)

    # MariaDB normalizes BOOLEAN to TINYINT(1); the hand-written DDL spells the
    # underlying type, which information_schema still reports as DATA_TYPE
    # 'tinyint', matching the model's expected shape.
    create_sql = (
        "CREATE TABLE issue58_boolean_alias ("
        "`id` BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY, "
        "`active` TINYINT(1) NOT NULL"
        ") ENGINE=InnoDB"
    )
    session = await load_fixture(database_session([Flag], setup_sql=[create_sql]))

    assert_eq(await _fetch_index_rows(session.server, "issue58_boolean_alias"), [])


@test(mark="medium")
async def mariadb_json_longtext_alias_verifies_clean() -> None:
    """``JSON`` is a ``LONGTEXT`` alias; either spelling is not drift."""

    class Doc[S = Pending](mariadb.Model[S, "Doc[Fetched]"]):
        """Model whose JSON column is migrated as the underlying LONGTEXT."""

        __tablename__ = "issue58_json_alias"
        id: Doc.GenCol[int] = mariadb.Integer(
            primary_key=True,
            auto_increment=True,
            default=PENDING_GENERATION,
        )
        payload: Doc.JsonCol[dict[str, object]] = mariadb.Json(nullable=False)

    # MariaDB implements JSON as LONGTEXT with a json_valid CHECK; the CHECK is
    # invisible to verification and DATA_TYPE reads back 'longtext' for both
    # spellings, so the LONGTEXT-spelled column is not drift.
    create_sql = (
        "CREATE TABLE issue58_json_alias ("
        "`id` BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY, "
        "`payload` LONGTEXT NOT NULL"
        ") ENGINE=InnoDB"
    )
    session = await load_fixture(database_session([Doc], setup_sql=[create_sql]))

    assert_eq(await _fetch_index_rows(session.server, "issue58_json_alias"), [])


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
            default=PENDING_GENERATION,
        )
        email: User.Col[str] = mariadb.Text(nullable=False)

    create_sql = (
        "CREATE TABLE issue119_column_drift ("
        "`id` BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY, "
        "`email` VARCHAR(255) CHARACTER SET utf8mb4 COLLATE utf8mb4_bin"
        ") ENGINE=InnoDB"
    )
    _ = await server.run_sql(create_sql)

    database = await Database.initialize(server.config())
    try:
        with assert_raises(SchemaVerificationError) as raised:
            await database.verify([User])
    finally:
        await database.close()

    message = str(raised.exception)
    assert_true("'email'" in message)
    assert_true("nullable" in message)

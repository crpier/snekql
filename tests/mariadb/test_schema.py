"""MariaDB schema startup and drift verification tests."""

from __future__ import annotations

import logging
from collections.abc import AsyncGenerator, Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any, ClassVar, cast

from snektest import (
    assert_eq,
    assert_raises,
    assert_true,
    fixture,
    load_fixture,
    test,
)

from snekql import mariadb
from snekql.mariadb import (
    PENDING_GENERATION,
    Database,
    Fetched,
    ForeignKey,
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


async def _fetch_column_data_type(
    server: TemporaryMariaDBServer, table_name: str, column_name: str
) -> str:
    """Fetch a column's normalized ``INFORMATION_SCHEMA.DATA_TYPE``."""

    result = await server.run_sql(
        f"""
        SELECT DATA_TYPE
        FROM INFORMATION_SCHEMA.COLUMNS
        WHERE TABLE_SCHEMA = DATABASE()
          AND TABLE_NAME = '{table_name}'
          AND COLUMN_NAME = '{column_name}'
        """,
    )
    lines = [line for line in result.stdout.splitlines() if line]
    return lines[1]


@fixture
async def database_session(
    models: Sequence[type[Table[Any]]] = (),
    *,
    schema_policy: SchemaPolicy = "strict",
    setup_sql: Sequence[str] = (),
) -> AsyncGenerator[_DatabaseSession]:
    """Provide an initialized MariaDB Database and close it after the test."""

    server = await load_fixture(provide_mariadb_server())
    for sql in setup_sql:
        _ = await server.run_sql(sql)
    database = await Database.initialize(server.config())
    try:
        if setup_sql:
            # The table already exists: verify the live schema against the models.
            await database.verify(cast("Any", models), policy=schema_policy)
        elif models:
            # Build the schema by replaying the scaffolded migration chain.
            await migrate_models(database, models)
        yield _DatabaseSession(database=database, server=server)
    finally:
        await database.close()


@test(mark="medium")
async def mariadb_model_foreign_key_verifies_without_implicit_index_drift() -> None:
    """MariaDB's required FK backing index is not an unexpected managed index."""

    class User[S = Pending](mariadb.Model[S, "User[Fetched]"]):
        """Referenced table."""

        __tablename__ = "issue253_fk_user"
        id: User.Col[int] = mariadb.Integer(primary_key=True)

    class Order[S = Pending](mariadb.Model[S, "Order[Fetched]"]):
        """Table with an enforced foreign key but no declared index."""

        __tablename__ = "issue253_fk_order"
        user_id: Order.FKCol[User, int] = ForeignKey(User.id, nullable=False)

    session = await load_fixture(database_session([User, Order]))

    result = await session.database.verify([User, Order])

    assert_eq(result.issues, ())


@test(mark="medium")
async def mariadb_foreign_key_action_drift_is_reported() -> None:
    """MariaDB compares managed referential actions semantically."""

    server = await load_fixture(provide_mariadb_server())

    class User[S = Pending](mariadb.Model[S, "User[Fetched]"]):
        """Referenced table."""

        __tablename__ = "issue253_action_user"
        id: User.Col[int] = mariadb.Integer(primary_key=True)

    class Order[S = Pending](mariadb.Model[S, "Order[Fetched]"]):
        """Model requiring cascading deletes."""

        __tablename__ = "issue253_action_order"
        user_id: Order.FKCol[User, int] = ForeignKey(
            User.id,
            nullable=False,
            on_delete="CASCADE",
        )

    _ = await server.run_sql(
        "CREATE TABLE issue253_action_user "
        "(id BIGINT NOT NULL PRIMARY KEY) ENGINE=InnoDB"
    )
    _ = await server.run_sql(
        "CREATE TABLE issue253_action_order (user_id BIGINT NOT NULL, "
        "FOREIGN KEY (user_id) REFERENCES issue253_action_user(id)) ENGINE=InnoDB"
    )
    database = await Database.initialize(server.config())
    try:
        with assert_raises(SchemaVerificationError) as raised:
            await database.verify([User, Order])
    finally:
        await database.close()

    assert_true("CASCADE" in str(raised.exception))
    assert_true("NO ACTION" in str(raised.exception))


@test(mark="medium")
async def mariadb_missing_managed_foreign_key_is_reported() -> None:
    """A model FK absent from the MariaDB catalog is strict drift."""

    server = await load_fixture(provide_mariadb_server())

    class User[S = Pending](mariadb.Model[S, "User[Fetched]"]):
        """Referenced table."""

        __tablename__ = "issue253_missing_fk_user"
        id: User.Col[int] = mariadb.Integer(primary_key=True)

    class Order[S = Pending](mariadb.Model[S, "Order[Fetched]"]):
        """Model whose managed FK is absent from the live table."""

        __tablename__ = "issue253_missing_fk_order"
        user_id: Order.FKCol[User, int] = ForeignKey(User.id, nullable=False)

    _ = await server.run_sql(
        "CREATE TABLE issue253_missing_fk_user "
        "(id BIGINT NOT NULL PRIMARY KEY) ENGINE=InnoDB"
    )
    _ = await server.run_sql(
        "CREATE TABLE issue253_missing_fk_order (user_id BIGINT NOT NULL) ENGINE=InnoDB"
    )
    database = await Database.initialize(server.config())
    try:
        with assert_raises(SchemaVerificationError) as raised:
            await database.verify([User, Order])
    finally:
        await database.close()

    assert_true("foreign key on column 'user_id'" in str(raised.exception))
    assert_true("is missing" in str(raised.exception))


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
async def mariadb_integer_signedness_drift_is_reported() -> None:
    """A live unsigned integer differs from snekql's signed Integer storage."""

    server = await load_fixture(provide_mariadb_server())

    class Counter[S = Pending](mariadb.Model[S, "Counter[Fetched]"]):
        """Model expecting a signed BIGINT."""

        __tablename__ = "issue253_signedness"
        value: Counter.Col[int] = mariadb.Integer(nullable=False)

    _ = await server.run_sql(
        "CREATE TABLE issue253_signedness "
        "(value BIGINT UNSIGNED NOT NULL) ENGINE=InnoDB"
    )
    database = await Database.initialize(server.config())
    try:
        with assert_raises(SchemaVerificationError) as raised:
            await database.verify([Counter])
    finally:
        await database.close()

    assert_true("unsigned expected False, found True" in str(raised.exception))


@test(mark="medium")
async def mariadb_datetime_precision_drift_is_reported() -> None:
    """A seconds-only DATETIME differs from snekql's millisecond precision."""

    server = await load_fixture(provide_mariadb_server())

    class Event[S = Pending](mariadb.Model[S, "Event[Fetched]"]):
        """Model expecting DATETIME(3)."""

        __tablename__ = "issue253_datetime_precision"
        happened_at: Event.Col[datetime] = mariadb.DateTime(nullable=False)

    _ = await server.run_sql(
        "CREATE TABLE issue253_datetime_precision "
        "(happened_at DATETIME NOT NULL) ENGINE=InnoDB"
    )
    database = await Database.initialize(server.config())
    try:
        with assert_raises(SchemaVerificationError) as raised:
            await database.verify([Event])
    finally:
        await database.close()

    assert_true("datetime precision expected 3, found 0" in str(raised.exception))


@test(mark="medium")
async def mariadb_supported_server_default_drift_is_reported() -> None:
    """A literal default cannot satisfy the `CurrentTimestamp` model marker."""

    server = await load_fixture(provide_mariadb_server())

    class Event[S = Pending](mariadb.Model[S, "Event[Fetched]"]):
        """Model requiring MariaDB's millisecond server clock."""

        __tablename__ = "issue253_server_default"
        created_at: Event.GenCol[datetime] = mariadb.DateTime(
            default=mariadb.CurrentTimestamp
        )

    _ = await server.run_sql(
        "CREATE TABLE issue253_server_default "
        "(created_at DATETIME(3) NOT NULL DEFAULT '2000-01-01 00:00:00.000') "
        "ENGINE=InnoDB"
    )
    database = await Database.initialize(server.config())
    try:
        with assert_raises(SchemaVerificationError) as raised:
            await database.verify([Event])
    finally:
        await database.close()

    assert_true("server default" in str(raised.exception))
    assert_true("CurrentTimestamp" in str(raised.exception))


@test(mark="medium")
async def mariadb_supported_server_default_is_normalized() -> None:
    """MariaDB's catalog-normalized `NOW(3)` satisfies `CurrentTimestamp`."""

    server = await load_fixture(provide_mariadb_server())

    class Event[S = Pending](mariadb.Model[S, "Event[Fetched]"]):
        """Model requiring MariaDB's millisecond server clock."""

        __tablename__ = "issue253_normalized_default"
        created_at: Event.GenCol[datetime] = mariadb.DateTime(
            default=mariadb.CurrentTimestamp
        )

    _ = await server.run_sql(
        "CREATE TABLE issue253_normalized_default "
        "(created_at DATETIME(3) NOT NULL DEFAULT NOW(3)) ENGINE=InnoDB"
    )
    database = await Database.initialize(server.config())
    try:
        result = await database.verify([Event])
    finally:
        await database.close()

    assert_eq(result.issues, ())


@test(mark="medium")
async def mariadb_decimal_precision_drift_is_reported() -> None:
    """Strict MariaDB schema verification compares Decimal precision and scale."""

    server = await load_fixture(provide_mariadb_server())

    class Price[S = Pending](mariadb.Model[S, "Price[Fetched]"]):
        """Model whose live decimal scale differs."""

        __tablename__ = "native_decimal_drift"
        amount: Price.Col[Decimal] = mariadb.Decimal(5, 2, nullable=False)

    _ = await server.run_sql(
        "CREATE TABLE native_decimal_drift (`amount` DECIMAL(5,3) NOT NULL) ENGINE=InnoDB"
    )

    database = await Database.initialize(server.config())
    try:
        with assert_raises(SchemaVerificationError) as raised:
            await database.verify([Price])
    finally:
        await database.close()

    assert_true("decimal(5,2)" in str(raised.exception))
    assert_true("decimal(5,3)" in str(raised.exception))


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
async def mariadb_index_prefix_length_drift_is_reported() -> None:
    """A prefix index cannot satisfy a model index over the complete value."""

    server = await load_fixture(provide_mariadb_server())

    class User[S = Pending](mariadb.Model[S, "User[Fetched]"]):
        """Model requiring a full-column email index."""

        __tablename__ = "issue253_index_prefix"
        email: User.Col[str] = mariadb.Text(nullable=False, index=True)

    _ = await server.run_sql(
        "CREATE TABLE issue253_index_prefix "
        "(email VARCHAR(255) CHARACTER SET utf8mb4 COLLATE utf8mb4_bin NOT NULL, "
        "INDEX ix_issue253_index_prefix_email (email(10))) ENGINE=InnoDB"
    )
    database = await Database.initialize(server.config())
    try:
        with assert_raises(SchemaVerificationError) as raised:
            await database.verify([User])
    finally:
        await database.close()

    assert_true("prefix lengths expected [None], found [10]" in str(raised.exception))


@test(mark="medium")
async def mariadb_index_type_drift_is_reported() -> None:
    """A FULLTEXT index cannot satisfy the model's ordinary BTREE index."""

    server = await load_fixture(provide_mariadb_server())

    class User[S = Pending](mariadb.Model[S, "User[Fetched]"]):
        """Model requiring an ordinary email index."""

        __tablename__ = "issue253_index_type"
        email: User.Col[str] = mariadb.Text(nullable=False, index=True)

    _ = await server.run_sql(
        "CREATE TABLE issue253_index_type "
        "(email VARCHAR(255) CHARACTER SET utf8mb4 COLLATE utf8mb4_bin NOT NULL, "
        "FULLTEXT INDEX ix_issue253_index_type_email (email)) ENGINE=InnoDB"
    )
    database = await Database.initialize(server.config())
    try:
        with assert_raises(SchemaVerificationError) as raised:
            await database.verify([User])
    finally:
        await database.close()

    assert_true(
        "index type expected 'BTREE', found 'FULLTEXT'" in str(raised.exception)
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

    # The migration author writes the BOOLEAN alias; MariaDB stores it as
    # TINYINT(1) and information_schema reports DATA_TYPE 'tinyint', the same
    # class the model's Boolean column expects. Reaching past the fixture means
    # the strict verify accepted the alias.
    create_sql = (
        "CREATE TABLE issue58_boolean_alias ("
        "`id` BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY, "
        "`active` BOOLEAN NOT NULL"
        ") ENGINE=InnoDB"
    )
    session = await load_fixture(database_session([Flag], setup_sql=[create_sql]))

    # The BOOLEAN spelling was normalized away to its underlying class, which is
    # exactly why strict verify above did not report drift.
    assert_eq(
        await _fetch_column_data_type(
            session.server, "issue58_boolean_alias", "active"
        ),
        "tinyint",
    )


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

    # The migration author writes the JSON alias; MariaDB implements it as
    # LONGTEXT with a json_valid CHECK (the CHECK is invisible to verification)
    # and DATA_TYPE reads back 'longtext', the class the model's Json column
    # expects. Reaching past the fixture means the strict verify accepted it.
    create_sql = (
        "CREATE TABLE issue58_json_alias ("
        "`id` BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY, "
        "`payload` JSON NOT NULL"
        ") ENGINE=InnoDB"
    )
    session = await load_fixture(database_session([Doc], setup_sql=[create_sql]))

    # The JSON spelling was normalized away to its underlying class, which is
    # exactly why strict verify above did not report drift.
    assert_eq(
        await _fetch_column_data_type(session.server, "issue58_json_alias", "payload"),
        "longtext",
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

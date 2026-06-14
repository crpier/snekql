"""MariaDB engine-setting application: InnoDB, collation, and enforcement."""

from __future__ import annotations

from snektest import assert_eq, assert_raises, assert_true, load_fixture, test

from snekql import (
    MISSING,
    Database,
    ExecutionError,
    Fetched,
    ForeignKey,
    Pending,
    SchemaVerificationError,
    insert,
    mariadb,
)
from tests.helpers import NULL_LOGGER, TemporaryMariaDBServer, provide_mariadb_server


async def _scalar(server: TemporaryMariaDBServer, sql: str) -> str:
    """Return the single scalar value of a one-row query via the CLI."""

    result = await server.run_sql(sql)
    lines = [line for line in result.stdout.splitlines() if line]
    return lines[-1] if len(lines) > 1 else ""


@test(mark="medium")
async def created_tables_use_innodb_and_binary_text_collation() -> None:
    """Fresh MariaDB tables are InnoDB with case-sensitive utf8mb4_bin text."""

    class User[S = Pending](mariadb.Model[S, "User[Fetched]"]):
        """Table whose engine and text collation are inspected."""

        __tablename__ = "issue96_engine_collation"

        id: User.GenCol[int] = mariadb.Integer(
            primary_key=True,
            auto_increment=True,
            default=MISSING,
        )
        email: User.Col[str] = mariadb.Text(nullable=False)

    server = await load_fixture(provide_mariadb_server())
    database = await Database.initialize(
        server.config(), logger=NULL_LOGGER, models=[User]
    )
    await database.close()

    engine = await _scalar(
        server,
        """
        SELECT ENGINE FROM INFORMATION_SCHEMA.TABLES
        WHERE TABLE_SCHEMA = DATABASE()
          AND TABLE_NAME = 'issue96_engine_collation'
        """,
    )
    collation = await _scalar(
        server,
        """
        SELECT COLLATION_NAME FROM INFORMATION_SCHEMA.COLUMNS
        WHERE TABLE_SCHEMA = DATABASE()
          AND TABLE_NAME = 'issue96_engine_collation'
          AND COLUMN_NAME = 'email'
        """,
    )

    assert_eq(engine, "InnoDB")
    assert_eq(collation, "utf8mb4_bin")


@test(mark="medium")
async def unique_text_columns_compare_case_sensitively() -> None:
    """utf8mb4_bin gives SQLite-like case-sensitive uniqueness on MariaDB."""

    class Account[S = Pending](mariadb.Model[S, "Account[Fetched]"]):
        """Table with a unique, case-sensitive text column."""

        __tablename__ = "issue96_case_sensitive"

        id: Account.GenCol[int] = mariadb.Integer(
            primary_key=True,
            auto_increment=True,
            default=MISSING,
        )
        name: Account.Col[str] = mariadb.Text(nullable=False, unique=True)

    server = await load_fixture(provide_mariadb_server())
    database = await Database.initialize(
        server.config(), logger=NULL_LOGGER, models=[Account]
    )
    try:
        async with database.transaction() as tx:
            await tx.execute(insert(Account(name="Alice")))
            await tx.execute(insert(Account(name="alice")))
    finally:
        await database.close()

    count = await _scalar(
        server,
        "SELECT COUNT(*) FROM issue96_case_sensitive",
    )
    assert_eq(count, "2")


@test(mark="medium")
async def inserting_a_row_that_violates_a_foreign_key_is_rejected() -> None:
    """foreign_key_checks plus InnoDB enforce the emitted FK constraint."""

    class Parent[S = Pending](mariadb.Model[S, "Parent[Fetched]"]):
        """Referenced table."""

        __tablename__ = "issue96_fk_parent"

        id: Parent.GenCol[int] = mariadb.Integer(
            primary_key=True,
            auto_increment=True,
            default=MISSING,
        )

    class Child[S = Pending](mariadb.Model[S, "Child[Fetched]"]):
        """Table whose parent_id is an enforced foreign key."""

        __tablename__ = "issue96_fk_child"

        id: Child.GenCol[int] = mariadb.Integer(
            primary_key=True,
            auto_increment=True,
            default=MISSING,
        )
        parent_id: Child.FKCol[Parent, int] = ForeignKey(Parent.id, nullable=False)

    server = await load_fixture(provide_mariadb_server())
    database = await Database.initialize(
        server.config(), logger=NULL_LOGGER, models=[Parent, Child]
    )
    try:
        with assert_raises(ExecutionError):
            async with database.transaction() as tx:
                await tx.execute(insert(Child(parent_id=999)))
    finally:
        await database.close()


@test(mark="medium")
async def strict_policy_rejects_a_non_innodb_existing_table() -> None:
    """A MyISAM table cannot enforce foreign keys, so it is strict-policy drift."""

    class User[S = Pending](mariadb.Model[S, "User[Fetched]"]):
        """Model whose columns match the existing non-InnoDB table."""

        __tablename__ = "issue96_myisam_drift"

        id: User.GenCol[int] = mariadb.Integer(
            primary_key=True,
            auto_increment=True,
            default=MISSING,
        )

    server = await load_fixture(provide_mariadb_server())
    create_myisam_sql = (
        "CREATE TABLE issue96_myisam_drift "
        "(`id` BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY) ENGINE=MyISAM"
    )
    _ = await server.run_sql(create_myisam_sql)

    with assert_raises(SchemaVerificationError):
        _ = await Database.initialize(
            server.config(), logger=NULL_LOGGER, models=[User]
        )


@test(mark="medium")
async def reinitialization_verifies_managed_tables_without_drift() -> None:
    """Re-opening snekql-created tables under strict policy reports no drift."""

    class User[S = Pending](mariadb.Model[S, "User[Fetched]"]):
        """Table created on the first init and verified on the second."""

        __tablename__ = "issue96_reverify"

        id: User.GenCol[int] = mariadb.Integer(
            primary_key=True,
            auto_increment=True,
            default=MISSING,
        )
        email: User.Col[str] = mariadb.Text(nullable=False, unique=True)

    server = await load_fixture(provide_mariadb_server())

    first = await Database.initialize(
        server.config(), logger=NULL_LOGGER, models=[User]
    )
    await first.close()

    # A clean strict re-verification proves the InnoDB + utf8mb4_bin signature
    # round-trips through information_schema without false drift.
    second = await Database.initialize(
        server.config(), logger=NULL_LOGGER, models=[User]
    )
    await second.close()

    assert_true(True)

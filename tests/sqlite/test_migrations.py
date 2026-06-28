"""SQLite imperative migrate/verify, history recording, and idempotent re-run tests."""

from __future__ import annotations

from pathlib import Path
from sqlite3 import connect
from tempfile import TemporaryDirectory

from snektest import assert_eq, assert_raises, assert_true, test

from snekql.sqlite import (
    PENDING_GENERATION,
    Database,
    Fetched,
    Integer,
    MigrationError,
    Model,
    Pending,
    SchemaVerificationError,
    Text,
)

_CREATE_USER_MIGRATION = (
    'CREATE TABLE "user" ("id" INTEGER PRIMARY KEY AUTOINCREMENT, '
    '"email" TEXT NOT NULL) STRICT'
)

# A body that fails at execution time: ALTER of a table no prior migration
# created. SQLite raises an operational error the runner reports as MigrationError.
_FAILING_MIGRATION = 'ALTER TABLE "missing" ADD COLUMN "x" INTEGER'

_CREATE_LATER_MIGRATION = 'CREATE TABLE "later" ("id" INTEGER PRIMARY KEY) STRICT'


def _fetch_applied_names(database_path: Path) -> list[str]:
    connection = connect(database_path)
    try:
        cursor = connection.execute("SELECT name FROM snekql_migrations ORDER BY name")
        return [str(row[0]) for row in cursor.fetchall()]
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


@test(mark="medium")
async def migrate_creates_table_and_records_history() -> None:
    """db.migrate runs a body against the database and records its name."""

    with TemporaryDirectory() as directory:
        database_path = Path(directory) / "app.db"
        database = await Database.initialize(database=database_path)
        await database.migrate({"001_create_user": _CREATE_USER_MIGRATION})
        await database.close()

        assert_true(_table_exists(database_path, "user"))
        assert_eq(_fetch_applied_names(database_path), ["001_create_user"])


@test(mark="medium")
async def initialize_does_no_schema_work() -> None:
    """Connect-only initialization creates neither tables nor the history table."""

    with TemporaryDirectory() as directory:
        database_path = Path(directory) / "app.db"
        database = await Database.initialize(database=database_path)
        await database.close()

        assert_true(not _table_exists(database_path, "user"))
        assert_true(not _table_exists(database_path, "snekql_migrations"))


@test(mark="medium")
async def re_migrating_does_not_reapply_recorded_migration() -> None:
    """A second migrate of an already-applied name neither re-runs nor re-records it."""

    migrations = {"001_create_user": _CREATE_USER_MIGRATION}
    with TemporaryDirectory() as directory:
        database_path = Path(directory) / "app.db"
        database = await Database.initialize(database=database_path)
        await database.migrate(migrations)
        await database.migrate(migrations)
        await database.close()

        assert_eq(_fetch_applied_names(database_path), ["001_create_user"])


@test(mark="medium")
async def new_pending_migration_applies_only_itself() -> None:
    """A migration appended on a later migrate applies while earlier ones are skipped."""

    with TemporaryDirectory() as directory:
        database_path = Path(directory) / "app.db"
        database = await Database.initialize(database=database_path)
        await database.migrate({"001_create_user": _CREATE_USER_MIGRATION})
        await database.migrate(
            {
                "001_create_user": _CREATE_USER_MIGRATION,
                "002_add_age": 'ALTER TABLE "user" ADD COLUMN "age" INTEGER',
            },
        )
        await database.close()

        assert_eq(
            _fetch_applied_names(database_path),
            ["001_create_user", "002_add_age"],
        )


@test(mark="medium")
async def verify_passes_against_migration_created_schema() -> None:
    """Verification passes when the migration-built schema matches the models."""

    class User[S = Pending](Model[S, "User[Fetched]"]):
        """Model whose DDL matches the create-user migration body."""

        id: User.GenCol[int] = Integer(
            primary_key=True, auto_increment=True, default=PENDING_GENERATION
        )
        email: User.Col[str] = Text(nullable=False)

    with TemporaryDirectory() as directory:
        database_path = Path(directory) / "app.db"
        database = await Database.initialize(database=database_path)
        await database.migrate({"001_create_user": _CREATE_USER_MIGRATION})
        await database.verify([User])
        await database.close()

        assert_eq(_fetch_applied_names(database_path), ["001_create_user"])


@test(mark="medium")
async def verify_fails_when_a_model_has_no_migration() -> None:
    """Under strict, a model whose table no migration created is reported as drift."""

    class User[S = Pending](Model[S, "User[Fetched]"]):
        """Model whose table is never created because migrations own creation."""

        id: User.GenCol[int] = Integer(
            primary_key=True, auto_increment=True, default=PENDING_GENERATION
        )
        email: User.Col[str] = Text(nullable=False)

    create_other = 'CREATE TABLE "other" ("id" INTEGER PRIMARY KEY) STRICT'
    with TemporaryDirectory() as directory:
        database_path = Path(directory) / "app.db"
        database = await Database.initialize(database=database_path)
        await database.migrate({"001_other": create_other})
        try:
            with assert_raises(SchemaVerificationError):
                await database.verify([User])
        finally:
            await database.close()


@test(mark="medium")
async def failing_migration_leaves_partial_chain_state() -> None:
    """A mid-chain failure halts: earlier objects/history persist, later ones never run.

    SQLite DDL auto-commits per statement, so the first body's table and its
    history row survive the failure while the failing and following bodies leave
    nothing — the documented backend-neutral partial-failure guarantee.
    """

    migrations = {
        "001_create_user": _CREATE_USER_MIGRATION,
        "002_break": _FAILING_MIGRATION,
        "003_later": _CREATE_LATER_MIGRATION,
    }
    with TemporaryDirectory() as directory:
        database_path = Path(directory) / "app.db"
        database = await Database.initialize(database=database_path)
        try:
            with assert_raises(MigrationError):
                await database.migrate(migrations)
        finally:
            await database.close()

        assert_true(_table_exists(database_path, "user"))
        assert_true(not _table_exists(database_path, "later"))
        assert_eq(_fetch_applied_names(database_path), ["001_create_user"])


@test(mark="medium")
async def fixed_retry_resumes_from_the_failure_point() -> None:
    """Replacing the failing body and re-migrating applies only the still-pending bodies."""

    failing = {
        "001_create_user": _CREATE_USER_MIGRATION,
        "002_break": _FAILING_MIGRATION,
        "003_later": _CREATE_LATER_MIGRATION,
    }
    fixed = {
        "001_create_user": _CREATE_USER_MIGRATION,
        "002_break": 'ALTER TABLE "user" ADD COLUMN "status" TEXT',
        "003_later": _CREATE_LATER_MIGRATION,
    }
    with TemporaryDirectory() as directory:
        database_path = Path(directory) / "app.db"
        database = await Database.initialize(database=database_path)
        with assert_raises(MigrationError):
            await database.migrate(failing)
        await database.migrate(fixed)
        await database.close()

        assert_true(_table_exists(database_path, "later"))
        assert_eq(
            _fetch_applied_names(database_path),
            ["001_create_user", "002_break", "003_later"],
        )


@test(mark="medium")
async def replica_init_then_verify_catches_a_forgotten_migration() -> None:
    """An init -> verify replica path fails fast when a migration was not applied."""

    class User[S = Pending](Model[S, "User[Fetched]"]):
        """Model whose table the replica expects an earlier deploy to have created."""

        id: User.GenCol[int] = Integer(
            primary_key=True, auto_increment=True, default=PENDING_GENERATION
        )
        email: User.Col[str] = Text(nullable=False)

    with TemporaryDirectory() as directory:
        database_path = Path(directory) / "app.db"
        # Replica boots against a database where the migration never ran.
        database = await Database.initialize(database=database_path)
        try:
            with assert_raises(SchemaVerificationError):
                await database.verify([User])
        finally:
            await database.close()

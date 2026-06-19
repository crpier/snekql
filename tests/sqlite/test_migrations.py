"""SQLite migration apply, history recording, and idempotent re-run tests."""

from __future__ import annotations

from pathlib import Path
from sqlite3 import connect
from tempfile import TemporaryDirectory

from snektest import assert_eq, assert_raises, assert_true, test

from snekql.sqlite import (
    MISSING,
    Database,
    Fetched,
    Integer,
    Model,
    Pending,
    SchemaVerificationError,
    Text,
)

_CREATE_USER_MIGRATION = (
    'CREATE TABLE "user" ("id" INTEGER PRIMARY KEY AUTOINCREMENT, '
    '"email" TEXT NOT NULL) STRICT'
)


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
async def migration_creates_table_and_records_history() -> None:
    """A migration body runs against the database and its name is recorded."""

    with TemporaryDirectory() as directory:
        database_path = Path(directory) / "app.db"
        database = await Database.initialize(
            database=database_path,
            migrations={"001_create_user": _CREATE_USER_MIGRATION},
        )
        await database.close()

        assert_true(_table_exists(database_path, "user"))
        assert_eq(_fetch_applied_names(database_path), ["001_create_user"])


@test(mark="medium")
async def reinitializing_does_not_reapply_recorded_migration() -> None:
    """Re-running an already-applied migration is skipped, not re-executed."""

    migrations = {"001_create_user": _CREATE_USER_MIGRATION}
    with TemporaryDirectory() as directory:
        database_path = Path(directory) / "app.db"
        first = await Database.initialize(database=database_path, migrations=migrations)
        await first.close()

        second = await Database.initialize(
            database=database_path, migrations=migrations
        )
        await second.close()

        assert_eq(_fetch_applied_names(database_path), ["001_create_user"])


@test(mark="medium")
async def new_pending_migration_applies_only_itself() -> None:
    """A migration appended on a later startup applies while earlier ones are skipped."""

    with TemporaryDirectory() as directory:
        database_path = Path(directory) / "app.db"
        first = await Database.initialize(
            database=database_path,
            migrations={"001_create_user": _CREATE_USER_MIGRATION},
        )
        await first.close()

        second = await Database.initialize(
            database=database_path,
            migrations={
                "001_create_user": _CREATE_USER_MIGRATION,
                "002_add_age": 'ALTER TABLE "user" ADD COLUMN "age" INTEGER',
            },
        )
        await second.close()

        assert_eq(
            _fetch_applied_names(database_path),
            ["001_create_user", "002_add_age"],
        )


@test(mark="medium")
async def models_verify_against_migration_created_schema() -> None:
    """Drift verification still runs after migrations and passes on a matching schema."""

    class User[S = Pending](Model[S, "User[Fetched]"]):
        """Model whose DDL matches the create-user migration body."""

        id: User.GenCol[int] = Integer(
            primary_key=True, auto_increment=True, default=MISSING
        )
        email: User.Col[str] = Text(nullable=False)

    with TemporaryDirectory() as directory:
        database_path = Path(directory) / "app.db"
        database = await Database.initialize(
            database=database_path,
            models=[User],
            migrations={"001_create_user": _CREATE_USER_MIGRATION},
        )
        await database.close()

        assert_eq(_fetch_applied_names(database_path), ["001_create_user"])


@test(mark="medium")
async def standalone_migrate_applies_without_full_initialize() -> None:
    """Database.migrate applies pending bodies and records history with no models."""

    with TemporaryDirectory() as directory:
        database_path = Path(directory) / "app.db"
        await Database.migrate(
            database=database_path,
            migrations={"001_create_user": _CREATE_USER_MIGRATION},
        )

        assert_true(_table_exists(database_path, "user"))
        assert_eq(_fetch_applied_names(database_path), ["001_create_user"])


@test(mark="medium")
async def standalone_migrate_is_idempotent() -> None:
    """A second standalone migrate of the same name neither re-runs nor re-records it."""

    migrations = {"001_create_user": _CREATE_USER_MIGRATION}
    with TemporaryDirectory() as directory:
        database_path = Path(directory) / "app.db"
        await Database.migrate(database=database_path, migrations=migrations)
        await Database.migrate(database=database_path, migrations=migrations)

        assert_eq(_fetch_applied_names(database_path), ["001_create_user"])


@test(mark="medium")
async def initialize_does_not_reapply_standalone_migration() -> None:
    """A migration applied standalone is recorded once and verified by a later initialize."""

    class User[S = Pending](Model[S, "User[Fetched]"]):
        """Model whose DDL matches the create-user migration body."""

        id: User.GenCol[int] = Integer(
            primary_key=True, auto_increment=True, default=MISSING
        )
        email: User.Col[str] = Text(nullable=False)

    migrations = {"001_create_user": _CREATE_USER_MIGRATION}
    with TemporaryDirectory() as directory:
        database_path = Path(directory) / "app.db"
        await Database.migrate(database=database_path, migrations=migrations)
        database = await Database.initialize(
            database=database_path,
            models=[User],
            migrations=migrations,
        )
        await database.close()

        assert_eq(_fetch_applied_names(database_path), ["001_create_user"])


@test(mark="medium")
async def model_without_matching_migration_fails_strict() -> None:
    """Under strict, a model whose table no migration created is reported as drift."""

    class User[S = Pending](Model[S, "User[Fetched]"]):
        """Model whose table is never created because migrations own creation."""

        id: User.GenCol[int] = Integer(
            primary_key=True, auto_increment=True, default=MISSING
        )
        email: User.Col[str] = Text(nullable=False)

    create_other = 'CREATE TABLE "other" ("id" INTEGER PRIMARY KEY) STRICT'
    with TemporaryDirectory() as directory:
        database_path = Path(directory) / "app.db"
        with assert_raises(SchemaVerificationError):
            _ = await Database.initialize(
                database=database_path,
                models=[User],
                migrations={"001_other": create_other},
            )

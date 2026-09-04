"""SQLite imperative migrate/verify, history recording, and idempotent re-run tests."""

from __future__ import annotations

from pathlib import Path
from sqlite3 import IntegrityError, OperationalError, connect
from tempfile import TemporaryDirectory
from threading import Event as ThreadEvent
from typing import Any, cast

import anyio
import anyio.lowlevel
from snektest import assert_eq, assert_raises, assert_true, test

from snekql.examples.basic import MIGRATIONS as EXAMPLE_MIGRATIONS
from snekql.examples.basic import User as ExampleUser
from snekql.sqlite import (
    PENDING_GENERATION,
    Config,
    Database,
    Fetched,
    Integer,
    MigrationDeclarationError,
    MigrationError,
    MigrationHistoryError,
    MigrationLockTimeoutError,
    MigrationResult,
    Model,
    Pending,
    SchemaVerificationError,
    Text,
)
from snekql.sqlite.runtime import SQLiteRuntime

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
        exists = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' "
            "AND name = 'snekql_migrations'"
        ).fetchone()
        if exists is None:
            return []
        cursor = connection.execute("SELECT name FROM snekql_migrations ORDER BY name")
        return [str(row[0]) for row in cursor.fetchall()]
    finally:
        connection.close()


def _fetch_history(database_path: Path) -> list[tuple[int, str, str]]:
    connection = connect(database_path)
    try:
        cursor = connection.execute(
            "SELECT position, name, checksum FROM snekql_migrations ORDER BY position"
        )
        return [
            (int(position), str(name), str(checksum))
            for position, name, checksum in cursor.fetchall()
        ]
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


def _schema_sql(database_path: Path) -> list[tuple[str, str, str]]:
    connection = connect(database_path)
    try:
        cursor = connection.execute(
            "SELECT type, name, sql FROM sqlite_master "
            "WHERE name != 'snekql_migrations' AND name NOT LIKE 'sqlite_%' "
            "ORDER BY type, name"
        )
        return [(str(kind), str(name), str(sql)) for kind, name, sql in cursor]
    finally:
        connection.close()


def _create_v1_history(database_path: Path, names: tuple[str, ...]) -> None:
    connection = connect(database_path)
    try:
        connection.execute(
            'CREATE TABLE "snekql_migrations" '
            '("name" TEXT PRIMARY KEY NOT NULL, "applied_at" TEXT NOT NULL) STRICT'
        )
        connection.executemany(
            "INSERT INTO snekql_migrations (name, applied_at) VALUES (?, ?)",
            [(name, "2026-08-31T00:00:00.000Z") for name in names],
        )
        connection.commit()
    finally:
        connection.close()


@test(mark="medium")
async def migrate_creates_table_and_records_history() -> None:
    """A fresh migrate returns status and records ordered checksummed history."""

    with TemporaryDirectory() as directory:
        database_path = Path(directory) / "app.db"
        database = await Database.initialize(database=database_path)
        result = await database.migrate({"001_create_user": _CREATE_USER_MIGRATION})
        await database.close()

        assert_eq(
            result,
            MigrationResult(
                applied=("001_create_user",),
                already_applied=(),
                legacy_adopted=False,
            ),
        )
        assert_true(_table_exists(database_path, "user"))
        assert_eq(
            _fetch_history(database_path),
            [
                (
                    1,
                    "001_create_user",
                    "11d280da4ab2db04e6e351274977b836c517e13f5a3a363b468a1257eed8437a",
                )
            ],
        )


@test(mark="medium")
async def bundled_sqlite_migrations_execute_and_verify() -> None:
    """The public example's immutable one-statement bodies are executable."""

    database = await Database.initialize(database=":memory:")
    try:
        await database.migrate(EXAMPLE_MIGRATIONS)
        await database.verify_migrations(EXAMPLE_MIGRATIONS)
        await database.verify([ExampleUser])
    finally:
        await database.close()


@test(mark="medium")
async def fresh_replay_and_incremental_upgrade_converge_on_sqlite() -> None:
    """Applying one prefix first yields the same final SQLite schema."""

    with TemporaryDirectory() as directory_name:
        directory = Path(directory_name)
        fresh_path = directory / "fresh.db"
        incremental_path = directory / "incremental.db"

        fresh = await Database.initialize(database=fresh_path)
        await fresh.migrate(EXAMPLE_MIGRATIONS)
        await fresh.verify([ExampleUser])
        await fresh.close()

        incremental = await Database.initialize(database=incremental_path)
        first_name, first_body = next(iter(EXAMPLE_MIGRATIONS.items()))
        await incremental.migrate({first_name: first_body})
        await incremental.migrate(EXAMPLE_MIGRATIONS)
        await incremental.verify_migrations(EXAMPLE_MIGRATIONS)
        await incremental.verify([ExampleUser])
        await incremental.close()

        assert_eq(_schema_sql(fresh_path), _schema_sql(incremental_path))


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
async def empty_declarations_still_inspect_history() -> None:
    """An empty chain succeeds only while Migration History is also empty."""

    with TemporaryDirectory() as directory:
        database_path = Path(directory) / "app.db"
        database = await Database.initialize(database=database_path)

        result = await database.migrate({})
        assert_eq(
            result,
            MigrationResult(
                applied=(),
                already_applied=(),
                legacy_adopted=False,
            ),
        )
        await database.migrate({"001_create_user": _CREATE_USER_MIGRATION})
        with assert_raises(MigrationHistoryError):
            await database.migrate({})
        await database.close()


@test(mark="medium")
async def empty_verification_does_not_create_history() -> None:
    """Read-only verification accepts absent empty history without mutation."""

    with TemporaryDirectory() as directory:
        database_path = Path(directory) / "app.db"
        database = await Database.initialize(database=database_path)

        await database.verify_migrations({})
        await database.close()

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
async def edited_applied_body_is_rejected() -> None:
    """An applied name cannot hide a changed exact SQL body."""

    with TemporaryDirectory() as directory:
        database_path = Path(directory) / "app.db"
        database = await Database.initialize(database=database_path)
        await database.migrate({"001_create_user": _CREATE_USER_MIGRATION})

        with assert_raises(MigrationHistoryError):
            await database.migrate({"001_create_user": f"{_CREATE_USER_MIGRATION} "})
        await database.close()


@test(mark="medium")
async def migration_declaration_is_snapshotted_before_connection_wait() -> None:
    """Caller mutation after the first backend await cannot change the plan."""

    migrations = {"001_create_user": _CREATE_USER_MIGRATION}
    with TemporaryDirectory() as directory:
        database_path = Path(directory) / "app.db"
        database = await Database.initialize(database=database_path, pool_size=1)
        started = anyio.Event()
        results: list[MigrationResult] = []

        async def migrate() -> None:
            started.set()
            results.append(await database.migrate(migrations))

        async with anyio.create_task_group() as task_group, database.transaction():
            task_group.start_soon(migrate)
            await started.wait()
            await anyio.lowlevel.checkpoint()
            migrations["002_late"] = _CREATE_LATER_MIGRATION
        await database.close()

        assert_eq(results[0].applied, ("001_create_user",))
        assert_true(not _table_exists(database_path, "later"))


@test(mark="medium")
async def invalid_declaration_fails_before_connection_acquisition() -> None:
    """Synchronous validation does not wait for an exhausted pool."""

    with TemporaryDirectory() as directory:
        database = await Database.initialize(
            database=Path(directory) / "app.db",
            pool_size=1,
        )
        try:
            async with database.transaction():
                with assert_raises(MigrationDeclarationError):
                    await database.migrate({"": "SELECT 1"})
                with assert_raises(MigrationDeclarationError):
                    await database.migrate(
                        {},
                        adopt_legacy=1,  # ty: ignore[invalid-argument-type]
                    )
        finally:
            await database.close()


@test(mark="medium")
async def verify_migrations_accepts_the_exact_applied_head() -> None:
    """Read-only Migration verification succeeds at the declaration head."""

    migrations = {"001_create_user": _CREATE_USER_MIGRATION}
    with TemporaryDirectory() as directory:
        database_path = Path(directory) / "app.db"
        database = await Database.initialize(database=database_path)
        await database.migrate(migrations)

        result = await database.verify_migrations(migrations)
        await database.close()

        assert_eq(result, None)
        assert_eq(_fetch_applied_names(database_path), ["001_create_user"])


@test(mark="medium")
async def non_empty_legacy_history_requires_explicit_adoption() -> None:
    """Ordinary migration never guesses order or bodies for v1 history."""

    with TemporaryDirectory() as directory:
        database_path = Path(directory) / "app.db"
        _create_v1_history(database_path, ("001_create_user",))
        database = await Database.initialize(database=database_path)

        with assert_raises(MigrationHistoryError):
            await database.migrate({"001_create_user": _CREATE_USER_MIGRATION})
        await database.close()

        connection = connect(database_path)
        try:
            columns = [
                str(row[1])
                for row in connection.execute(
                    'PRAGMA table_info("snekql_migrations")'
                ).fetchall()
            ]
        finally:
            connection.close()
        assert_eq(columns, ["name", "applied_at"])


@test(mark="medium")
async def legacy_staging_object_collisions_fail_as_history_errors() -> None:
    """Case variants and views cannot collide with SQLite's adoption staging name."""

    with TemporaryDirectory() as directory:
        for index, staging_sql in enumerate(
            (
                'CREATE VIEW "_snekql_migrations_v1" AS SELECT 1 AS value',
                'CREATE TABLE "_SNEKQL_MIGRATIONS_V1" ("value" INTEGER)',
            )
        ):
            database_path = Path(directory) / f"collision_{index}.db"
            _create_v1_history(database_path, ("001_create_user",))
            connection = connect(database_path)
            connection.execute(staging_sql)
            connection.commit()
            connection.close()
            database = await Database.initialize(database=database_path)

            with assert_raises(MigrationHistoryError):
                await database.migrate(
                    {"001_create_user": _CREATE_USER_MIGRATION},
                    adopt_legacy=True,
                )
            await database.close()


@test(mark="medium")
async def empty_legacy_history_upgrades_without_adoption() -> None:
    """An empty v1 table carries no unprovable historical claims."""

    with TemporaryDirectory() as directory:
        database_path = Path(directory) / "app.db"
        _create_v1_history(database_path, ())
        database = await Database.initialize(database=database_path)

        result = await database.migrate({})
        await database.close()

        assert_eq(
            result,
            MigrationResult(
                applied=(),
                already_applied=(),
                legacy_adopted=False,
            ),
        )
        assert_eq(_fetch_history(database_path), [])


@test(mark="medium")
async def explicit_legacy_adoption_baselines_the_declared_prefix() -> None:
    """Consent assigns v2 positions and checksums from the current declaration."""

    migrations = {
        "001_create_user": _CREATE_USER_MIGRATION,
        "002_add_age": 'ALTER TABLE "user" ADD COLUMN "age" INTEGER',
    }
    with TemporaryDirectory() as directory:
        database_path = Path(directory) / "app.db"
        _create_v1_history(database_path, ("001_create_user",))
        connection = connect(database_path)
        try:
            connection.execute(_CREATE_USER_MIGRATION)
            connection.commit()
        finally:
            connection.close()
        database = await Database.initialize(database=database_path)

        result = await database.migrate(migrations, adopt_legacy=True)
        await database.close()

        assert_eq(
            result,
            MigrationResult(
                applied=("002_add_age",),
                already_applied=("001_create_user",),
                legacy_adopted=True,
            ),
        )
        assert_eq(
            [name for _, name, _ in _fetch_history(database_path)],
            ["001_create_user", "002_add_age"],
        )


@test(mark="medium")
async def migration_verification_rejects_legacy_history_without_mutation() -> None:
    """Read-only verification never upgrades or adopts a v1 table."""

    with TemporaryDirectory() as directory:
        database_path = Path(directory) / "app.db"
        _create_v1_history(database_path, ("001_create_user",))
        database = await Database.initialize(database=database_path)

        with assert_raises(MigrationHistoryError):
            await database.verify_migrations(
                {"001_create_user": _CREATE_USER_MIGRATION}
            )
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
async def concurrent_runners_apply_a_non_idempotent_migration_once() -> None:
    """`BEGIN IMMEDIATE` serializes history inspection with the migration write."""

    with TemporaryDirectory() as directory:
        database_path = Path(directory) / "app.db"
        first = await Database.initialize(database=database_path)
        second = await Database.initialize(database=database_path)
        results: list[MigrationResult] = []

        async def migrate(database: Database) -> None:
            results.append(
                await database.migrate({"001_create_user": _CREATE_USER_MIGRATION})
            )

        try:
            async with anyio.create_task_group() as task_group:
                task_group.start_soon(migrate, first)
                task_group.start_soon(migrate, second)
        finally:
            await first.close()
            await second.close()

        assert_eq(
            {result.applied for result in results},
            {(), ("001_create_user",)},
        )
        assert_eq(
            {result.already_applied for result in results},
            {(), ("001_create_user",)},
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
        try:
            with assert_raises(MigrationError):
                await database.migrate(failing)
            await database.migrate(fixed)
        finally:
            await database.close()

        assert_true(_table_exists(database_path, "later"))
        assert_eq(
            _fetch_applied_names(database_path),
            ["001_create_user", "002_break", "003_later"],
        )


@test(mark="medium")
async def multi_statement_body_is_rejected_leaving_no_partial_object() -> None:
    """Stacked SQLite statements are invalid before connection acquisition."""

    multi_statement = (
        f'{_CREATE_USER_MIGRATION}; ALTER TABLE "missing" ADD COLUMN "x" INTEGER'
    )
    with TemporaryDirectory() as directory:
        database_path = Path(directory) / "app.db"
        database = await Database.initialize(database=database_path)
        try:
            with assert_raises(MigrationDeclarationError):
                await database.migrate({"001_multi": multi_statement})
        finally:
            await database.close()

        assert_true(not _table_exists(database_path, "user"))
        assert_eq(_fetch_applied_names(database_path), [])


@test(mark="medium")
async def trigger_body_with_internal_semicolons_is_one_statement() -> None:
    """SQLite trigger grammar is accepted without splitting on semicolons."""

    trigger_sql = (
        'CREATE TRIGGER "normalize_user_email" AFTER INSERT ON "user" '
        'BEGIN UPDATE "user" SET "email" = lower(NEW."email") '
        'WHERE "id" = NEW."id"; END'
    )
    with TemporaryDirectory() as directory:
        database_path = Path(directory) / "app.db"
        database = await Database.initialize(database=database_path)

        result = await database.migrate(
            {
                "001_create_user": _CREATE_USER_MIGRATION,
                "002_normalize_email": trigger_sql,
            }
        )
        await database.close()

        assert_eq(
            result.applied,
            ("001_create_user", "002_normalize_email"),
        )
        assert_true(_table_exists(database_path, "user"))


@test(mark="medium")
async def connection_scoped_sqlite_bodies_are_rejected() -> None:
    """Bodies cannot escape the owned persistent main-database transaction."""

    invalid_bodies = (
        "BEGIN",
        "COMMIT",
        "ROLLBACK",
        "SAVEPOINT migration",
        "RELEASE migration",
        "VACUUM",
        "ATTACH DATABASE ':memory:' AS other",
        "DETACH DATABASE other",
        "PRAGMA foreign_keys = OFF",
        "EXPLAIN PRAGMA foreign_keys",
        "EXPLAIN ATTACH DATABASE ':memory:' AS other",
        "CREATE TEMP TABLE transient (id INTEGER)",
        "CREATE TABLE temp.transient (id INTEGER)",
        'CREATE TABLE "temp".transient (id INTEGER)',
        "CREATE TABLE [temp].transient (id INTEGER)",
        "CREATE TABLE 'temp'.transient (id INTEGER)",
        "CREATE VIRTUAL TABLE temp.transient USING fts5(body)",
        "UPDATE OR IGNORE temp.transient SET id = 1",
        "WITH value AS (SELECT 1) UPDATE temp.transient SET id = 1",
        "WITH value AS (SELECT 1) DELETE FROM temp.transient",
        "WITH value AS (SELECT 1) INSERT INTO temp.transient VALUES (1)",
        (
            'WITH first AS (SELECT 1), "update" AS (SELECT 2) '
            "UPDATE temp.transient SET id = 1"
        ),
    )
    with TemporaryDirectory() as directory:
        database = await Database.initialize(database=Path(directory) / "app.db")
        try:
            for index, body in enumerate(invalid_bodies):
                with assert_raises(MigrationDeclarationError):
                    await database.migrate({f"{index:03}_invalid": body})
        finally:
            await database.close()


@test(mark="medium")
async def temp_aliases_and_history_named_columns_remain_valid() -> None:
    """Restriction checks distinguish SQL targets from aliases and columns."""

    migrations = {
        "001_create_app": (
            'CREATE TABLE "app" ('
            '"id" INTEGER PRIMARY KEY, '
            '"snekql_migrations" INTEGER NOT NULL, '
            '"value" INTEGER NOT NULL'
            ") STRICT"
        ),
        "002_read_named_column": ('UPDATE "app" SET "value" = "snekql_migrations"'),
        "003_write_named_column": ('UPDATE "app" SET "snekql_migrations" = 1'),
        "004_temp_alias": 'UPDATE "app" AS temp SET "value" = temp."id"',
    }
    with TemporaryDirectory() as directory:
        database = await Database.initialize(database=Path(directory) / "app.db")

        result = await database.migrate(migrations)
        await database.close()

        assert_eq(result.applied, tuple(migrations))


@test(mark="medium")
async def migration_body_cannot_mutate_owned_history() -> None:
    """SQLite's authorizer keeps raw bodies away from Migration History."""

    migrations = {"001_create_user": _CREATE_USER_MIGRATION}
    with TemporaryDirectory() as directory:
        database_path = Path(directory) / "app.db"
        database = await Database.initialize(database=database_path)
        await database.migrate(migrations)

        corrupting_bodies = (
            'DELETE FROM "snekql_migrations"',
            'ALTER TABLE "snekql_migrations" ADD COLUMN "extra" TEXT',
            (
                'CREATE TRIGGER "corrupt_history" BEFORE INSERT '
                'ON "snekql_migrations" BEGIN SELECT RAISE(IGNORE); END'
            ),
        )
        for body in corrupting_bodies:
            with assert_raises(MigrationError):
                await database.migrate({**migrations, "002_corrupt_history": body})
        result = await database.migrate(
            {
                **migrations,
                "002_corrupt_history": _CREATE_LATER_MIGRATION,
            }
        )
        await database.close()

        assert_eq(result.applied, ("002_corrupt_history",))
        assert_eq(
            _fetch_applied_names(database_path),
            ["001_create_user", "002_corrupt_history"],
        )


@test(mark="medium")
async def sqlite_body_rolls_back_when_history_insert_fails() -> None:
    """A persistent body and its v2 history row commit or roll back together."""

    create_items = 'CREATE TABLE "item" ("id" INTEGER PRIMARY KEY) STRICT'
    migrations = {"001_create_items": create_items}
    with TemporaryDirectory() as directory:
        database_path = Path(directory) / "app.db"
        database = await Database.initialize(database=database_path, pool_size=1)
        await database.migrate(migrations)
        runtime = cast("SQLiteRuntime", database.runtime)
        pooled_connection = await runtime.connection_pool.acquire(
            runtime.acquire_timeout
        )
        original_execute = pooled_connection.execute

        def fail_history_insert(sql: str, *args: object, **kwargs: object) -> Any:
            if sql.startswith('INSERT INTO "snekql_migrations"'):
                msg = "blocked history insert"
                raise OperationalError(msg)
            return original_execute(sql, *args, **kwargs)

        cast("Any", pooled_connection).execute = fail_history_insert
        await runtime.connection_pool.release(pooled_connection)

        with assert_raises(MigrationHistoryError):
            await database.migrate(
                {
                    **migrations,
                    "002_insert_item": 'INSERT INTO "item" ("id") VALUES (1)',
                }
            )
        pooled_connection = await runtime.connection_pool.acquire(
            runtime.acquire_timeout
        )
        cast("Any", pooled_connection).execute = original_execute
        await runtime.connection_pool.release(pooled_connection)
        await database.close()

        connection = connect(database_path)
        try:
            item_count = int(
                connection.execute('SELECT COUNT(*) FROM "item"').fetchone()[0]
            )
        finally:
            connection.close()
        assert_eq(item_count, 0)


@test(mark="medium")
async def cancellation_rolls_back_and_restores_the_sqlite_connection() -> None:
    """Cancellation cannot return an owned transaction or authorizer to the pool."""

    with TemporaryDirectory() as directory:
        database_path = Path(directory) / "app.db"
        database = await Database.initialize(database=database_path, pool_size=1)
        runtime = cast("SQLiteRuntime", database.runtime)
        connection = await runtime.connection_pool.acquire(runtime.acquire_timeout)
        statement_started = ThreadEvent()
        allow_statement_to_finish = ThreadEvent()

        def block_migration() -> int:
            statement_started.set()
            _ = allow_statement_to_finish.wait(timeout=5)
            return 1

        await connection.create_function("block_migration", 0, block_migration)
        await runtime.connection_pool.release(connection)
        cancel_scope = anyio.CancelScope()
        migration_finished = anyio.Event()

        async def run_cancelled_migration() -> None:
            with cancel_scope:
                await database.migrate({"001_cancelled": "SELECT block_migration()"})
            migration_finished.set()

        async with anyio.create_task_group() as task_group:
            task_group.start_soon(run_cancelled_migration)
            with anyio.fail_after(5):
                while not statement_started.is_set():
                    await anyio.lowlevel.checkpoint()
            cancel_scope.cancel()
            allow_statement_to_finish.set()
            await migration_finished.wait()

        result = await database.migrate({"001_cancelled": _CREATE_LATER_MIGRATION})
        await database.close()

        assert_eq(result.applied, ("001_cancelled",))
        assert_true(_table_exists(database_path, "later"))


@test(mark="medium")
async def commit_failure_rolls_back_before_sqlite_connection_reuse() -> None:
    """A failed commit leaves neither the body nor its history row behind."""

    with TemporaryDirectory() as directory:
        database_path = Path(directory) / "app.db"
        database = await Database.initialize(database=database_path, pool_size=1)
        runtime = cast("SQLiteRuntime", database.runtime)
        connection = await runtime.connection_pool.acquire(runtime.acquire_timeout)
        original_commit = connection.commit

        async def fail_commit() -> None:
            msg = "database is locked"
            raise OperationalError(msg)

        cast("Any", connection).commit = fail_commit
        await runtime.connection_pool.release(connection)

        with assert_raises(OperationalError):
            await database.migrate({"001_commit": _CREATE_LATER_MIGRATION})
        assert_true(not _table_exists(database_path, "later"))
        assert_eq(_fetch_applied_names(database_path), [])

        connection = await runtime.connection_pool.acquire(runtime.acquire_timeout)
        cast("Any", connection).commit = original_commit
        await runtime.connection_pool.release(connection)
        result = await database.migrate({"001_commit": _CREATE_LATER_MIGRATION})
        await database.close()

        assert_eq(result.applied, ("001_commit",))


@test(mark="medium")
async def cancellation_during_sqlite_writer_lock_acquisition_discards_connection() -> (
    None
):
    """A cancelled queued `BEGIN IMMEDIATE` can never later enter the idle pool."""

    with TemporaryDirectory() as directory:
        database_path = Path(directory) / "app.db"
        database = await Database.initialize(database=database_path, pool_size=1)
        holder = connect(database_path, isolation_level=None)
        holder.execute("BEGIN IMMEDIATE")
        cancel_scope = anyio.CancelScope()
        migration_started = anyio.Event()
        migration_finished = anyio.Event()

        async def run_cancelled_migration() -> None:
            with cancel_scope:
                migration_started.set()
                await database.migrate({"001_cancelled_begin": _CREATE_LATER_MIGRATION})
            migration_finished.set()

        try:
            async with anyio.create_task_group() as task_group:
                task_group.start_soon(run_cancelled_migration)
                await migration_started.wait()
                await anyio.sleep(0.01)
                cancel_scope.cancel()
                holder.rollback()
                await migration_finished.wait()

            result = await database.migrate(
                {"001_cancelled_begin": _CREATE_LATER_MIGRATION}
            )
        finally:
            holder.close()
            await database.close()

        assert_eq(result.applied, ("001_cancelled_begin",))


@test(mark="medium")
async def exhausted_sqlite_writer_lock_budget_uses_migration_lock_error() -> None:
    """Migration lock exhaustion is distinct from body execution failure."""

    with TemporaryDirectory() as directory:
        database_path = Path(directory) / "app.db"
        database = await Database.initialize(
            Config(database=database_path, busy_max_retries=0)
        )
        runtime = cast("SQLiteRuntime", database.runtime)
        connection = await runtime.connection_pool.acquire(runtime.acquire_timeout)
        cursor = await connection.execute("PRAGMA busy_timeout = 0")
        await cursor.close()
        await runtime.connection_pool.release(connection)
        holder = connect(database_path, isolation_level=None)
        holder.execute("BEGIN IMMEDIATE")

        try:
            with assert_raises(MigrationLockTimeoutError):
                await database.migrate({"001_blocked": _CREATE_LATER_MIGRATION})
        finally:
            holder.rollback()
            holder.close()
            await database.close()

        assert_eq(_fetch_applied_names(database_path), [])


@test(mark="medium")
async def unknown_sqlite_history_objects_fail_closed() -> None:
    """Views and triggers cannot impersonate package-owned Migration History."""

    with TemporaryDirectory() as directory:
        view_path = Path(directory) / "view.db"
        connection = connect(view_path)
        connection.execute(
            'CREATE VIEW "snekql_migrations" AS '
            'SELECT 1 AS position, "001" AS name, printf("%064d", 0) AS checksum'
        )
        connection.commit()
        connection.close()
        database = await Database.initialize(database=view_path)
        with assert_raises(MigrationHistoryError):
            await database.verify_migrations({})
        with assert_raises(MigrationHistoryError):
            await database.migrate({})
        await database.close()

        trigger_path = Path(directory) / "trigger.db"
        database = await Database.initialize(database=trigger_path)
        await database.migrate({})
        await database.close()
        connection = connect(trigger_path)
        connection.execute(
            'CREATE TRIGGER "ignore_history" BEFORE INSERT '
            'ON "snekql_migrations" BEGIN SELECT RAISE(IGNORE); END'
        )
        connection.commit()
        connection.close()
        database = await Database.initialize(database=trigger_path)
        with assert_raises(MigrationHistoryError):
            await database.migrate({"001_later": _CREATE_LATER_MIGRATION})
        await database.close()
        assert_true(not _table_exists(trigger_path, "later"))


@test(mark="medium")
async def sqlite_history_ddl_rejects_nul_extended_checksums() -> None:
    """The database enforces exactly 64 lowercase checksum bytes."""

    with TemporaryDirectory() as directory:
        database_path = Path(directory) / "app.db"
        database = await Database.initialize(database=database_path)
        await database.migrate({})
        await database.close()

        connection = connect(database_path)
        try:
            with assert_raises(IntegrityError):
                connection.execute(
                    "INSERT INTO snekql_migrations "
                    "(position, name, checksum, applied_at) VALUES (?, ?, ?, ?)",
                    (1, "001", f"{'a' * 64}\x00BAD", "2026-08-31T00:00:00.000Z"),
                )
        finally:
            connection.close()


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

"""SQLite migration bodies are atomic SQL units with one history identity."""

import asyncio
from collections.abc import AsyncGenerator, Iterable
from pathlib import Path
from unittest.mock import patch

from aiosqlite import Connection, Cursor
from anyio import CancelScope, Event, TemporaryDirectory, fail_after, sleep_forever
from snektest import Param, assert_eq, assert_raises, fixture, load_fixture, test

from snekql import sqlite


@fixture
async def provide_database() -> AsyncGenerator[sqlite.Database]:
    async with (
        TemporaryDirectory() as directory,
        await sqlite.Database.initialize(
            sqlite.Config(database=Path(directory) / "units.db", pool_size=1)
        ) as database,
    ):
        yield database


@test(mark="medium")
async def multiple_statements_share_one_history_identity() -> None:
    """One named body creates and populates a table, and reruns skip the whole body."""
    database = await load_fixture(provide_database())
    migrations = {
        "001_entries": "CREATE TABLE entries (id INTEGER PRIMARY KEY); INSERT INTO entries VALUES (1);"
    }

    result = await database.migrate(migrations)
    assert_eq(result.applied, ("001_entries",))
    await database.verify_migrations(migrations)
    repeated = await database.migrate(migrations)
    assert_eq(repeated.already_applied, ("001_entries",))
    async with database.transaction() as transaction:
        rows = await transaction.fetch_all(sqlite.raw("SELECT id FROM entries"))
    assert_eq(rows, [{"id": 1}])


@test(mark="medium")
async def tokenless_garbage_is_not_silently_skipped() -> None:
    """A malformed later segment must not be treated as an empty SQL statement."""
    database = await load_fixture(provide_database())

    with assert_raises(sqlite.MigrationError):
        await database.migrate({"unit": "CREATE TABLE entries (id INTEGER); 123;"})
    await database.verify_migrations({})


@test(mark="medium")
async def mid_body_failure_rolls_back_schema_data_history() -> None:
    """A later syntax/runtime failure leaves only previously committed units."""
    database = await load_fixture(provide_database())
    base = {
        "001": "CREATE TABLE entries (id INTEGER PRIMARY KEY); INSERT INTO entries VALUES (1);"
    }
    await database.migrate(base)

    with assert_raises(sqlite.MigrationError):
        await database.migrate(
            base
            | {
                "002": "INSERT INTO entries VALUES (2); ALTER TABLE entries ADD COLUMN note TEXT; INSERT INTO missing VALUES (3);"
            }
        )

    await database.verify_migrations(base)
    async with database.transaction() as transaction:
        rows = await transaction.fetch_all(sqlite.raw("SELECT * FROM entries"))
    assert_eq(rows, [{"id": 1}])


@test(mark="medium")
async def trigger_body_preserves_internal_semicolons() -> None:
    """Trigger statements and CASE END do not split the surrounding migration unit."""
    database = await load_fixture(provide_database())
    body = """
        ; -- empty statements and comments are harmless
        CREATE TABLE entries (id INTEGER PRIMARY KEY, body TEXT);
        /* ; END; */ CREATE TABLE audit (body TEXT);
        CREATE TRIGGER record_entry AFTER INSERT ON entries BEGIN
            UPDATE entries SET body = CASE WHEN NEW.body = 'a;b'
                THEN 'quoted;''value' ELSE NEW.body END WHERE id = NEW.id;
            INSERT INTO audit VALUES ('END; -- not a comment');
        END;
        INSERT INTO entries VALUES (1, 'a;b');
        -- final comment without a following statement
    """

    await database.migrate({"unit": body})
    async with database.transaction() as transaction:
        rows = await transaction.fetch_all(
            sqlite.raw(
                "SELECT entries.body, audit.body AS audit FROM entries CROSS JOIN audit"
            )
        )
    assert_eq(rows, [{"body": "quoted;'value", "audit": "END; -- not a comment"}])


@test(
    [
        Param(value=sql, name=name)
        for name, sql in [
            ("commit", "COMMIT"),
            ("begin", "BEGIN"),
            ("rollback", "ROLLBACK"),
            ("savepoint", "SAVEPOINT nested"),
            ("release", "RELEASE nested"),
            ("pragma", "PRAGMA foreign_keys = OFF"),
            ("explain-pragma", "EXPLAIN PRAGMA foreign_keys"),
            ("attach", "ATTACH ':memory:' AS other"),
            ("detach", "DETACH other"),
            ("vacuum", "VACUUM"),
            ("temporary", "CREATE TEMP TABLE scratch (id INTEGER)"),
            ("temp-schema", "CREATE TABLE temp.scratch (id INTEGER)"),
            (
                "incomplete-trigger",
                "CREATE TRIGGER unfinished AFTER INSERT ON entries BEGIN SELECT 1;",
            ),
            ("incomplete-string", "INSERT INTO entries VALUES ('unfinished"),
            ("incomplete-comment", "/* unfinished"),
        ]
    ],
    mark="medium",
)
async def unsafe_later_statement_is_rejected_before_io(statement: str) -> None:
    """Every segment is checked before a closed database can be acquired."""
    database = await load_fixture(provide_database())
    await database.close()

    with assert_raises(sqlite.MigrationDeclarationError):
        await database.migrate(
            {"unit": f"CREATE TABLE entries (id INTEGER); {statement}"}
        )


@test(mark="medium")
async def later_history_mutation_is_denied() -> None:
    """The authorizer stays active for every statement, not just the first."""
    database = await load_fixture(provide_database())

    with assert_raises(sqlite.MigrationError):
        await database.migrate(
            {
                "unit": "CREATE TABLE entries (id INTEGER); DELETE FROM snekql_migrations;"
            }
        )
    await database.verify_migrations({})


@test(mark="medium")
async def exact_body_checksum_includes_statement_separators() -> None:
    """Equivalent statement lists cannot hide edits to the recorded SQL body."""
    database = await load_fixture(provide_database())
    body = "CREATE TABLE entries (id INTEGER); INSERT INTO entries VALUES (1);"
    await database.migrate({"unit": body})

    with assert_raises(sqlite.MigrationHistoryError):
        await database.verify_migrations({"unit": body.replace("; ", ";\n")})


@fixture
async def provide_rebuilt_database() -> AsyncGenerator[sqlite.Database]:
    """Rebuild a populated child table without disabling foreign-key enforcement."""
    database = await load_fixture(provide_database())
    await database.migrate(
        {
            "001_initial": """
            CREATE TABLE parent (id INTEGER PRIMARY KEY);
            CREATE TABLE child (id INTEGER PRIMARY KEY, parent_id INTEGER NOT NULL,
                label TEXT NOT NULL, FOREIGN KEY (parent_id) REFERENCES parent(id));
            CREATE UNIQUE INDEX child_label ON child(label);
            INSERT INTO parent VALUES (1);
            INSERT INTO child VALUES (1, 1, 'original');
        """,
            "002_rebuild": """
            CREATE TABLE child_new (id INTEGER PRIMARY KEY, parent_id INTEGER NOT NULL,
                label TEXT NOT NULL, note TEXT NOT NULL DEFAULT 'added',
                FOREIGN KEY (parent_id) REFERENCES parent(id));
            INSERT INTO child_new (id, parent_id, label) SELECT id, parent_id, label FROM child;
            DROP TABLE child;
            ALTER TABLE child_new RENAME TO child;
            CREATE UNIQUE INDEX child_label ON child(label);
        """,
        }
    )
    yield database


@test(mark="medium")
async def rebuild_preserves_data() -> None:
    """Copy/drop/rename runs as one migration and retains the existing rows."""
    database = await load_fixture(provide_rebuilt_database())

    async with database.transaction() as transaction:
        rows = await transaction.fetch_all(sqlite.raw("SELECT * FROM child"))
    assert_eq(rows, [{"id": 1, "parent_id": 1, "label": "original", "note": "added"}])


@test(mark="medium")
async def rebuild_restores_unique_index() -> None:
    """An explicitly recreated index retains its enforcement after the rebuild."""
    database = await load_fixture(provide_rebuilt_database())

    with assert_raises(sqlite.ExecutionError):
        async with database.transaction() as transaction:
            await transaction.execute(
                sqlite.raw(
                    "INSERT INTO child (id, parent_id, label) VALUES (2, 1, 'original')"
                )
            )


@test(mark="medium")
async def rebuild_preserves_foreign_key_enforcement() -> None:
    """Renaming the rebuilt child table does not lose its reference to the parent."""
    database = await load_fixture(provide_rebuilt_database())

    with assert_raises(sqlite.ExecutionError):
        async with database.transaction() as transaction:
            await transaction.execute(
                sqlite.raw(
                    "INSERT INTO child (id, parent_id, label) VALUES (2, 999, 'other')"
                )
            )


@test(mark="medium")
async def deferred_foreign_key_failure_rolls_back_unit() -> None:
    """Even a constraint checked at commit rolls back schema, data, and history."""
    database = await load_fixture(provide_database())
    body = """
        CREATE TABLE parent (id INTEGER PRIMARY KEY);
        CREATE TABLE child (parent_id INTEGER REFERENCES parent(id) DEFERRABLE INITIALLY DEFERRED);
        INSERT INTO child VALUES (999);
    """

    with assert_raises(sqlite.MigrationError):
        await database.migrate({"unit": body})
    await database.verify_migrations({})
    async with database.transaction() as transaction:
        rows = await transaction.fetch_all(
            sqlite.raw(
                "SELECT name FROM sqlite_schema WHERE name IN ('parent', 'child')"
            )
        )
    assert_eq(rows, [])


@test(mark="medium")
async def unqualified_temporary_table_cannot_be_renamed() -> None:
    """Allowing SQLite's internal rename bookkeeping cannot permit temp-table DDL."""
    database = await load_fixture(provide_database())
    async with database.transaction() as transaction:
        await transaction.execute(sqlite.raw("CREATE TEMP TABLE scratch (id INTEGER)"))

    with assert_raises(sqlite.MigrationError):
        await database.migrate(
            {
                "unit": "CREATE TABLE entries (id INTEGER); ALTER TABLE scratch RENAME TO moved;"
            }
        )
    await database.verify_migrations({})


@test(
    [Param(value="native", name="native"), Param(value="scope", name="scope")],
    [
        Param(value="before", name="before-execute"),
        Param(value="after", name="after-execute"),
    ],
    mark="medium",
)
async def cancellation_between_statements_rolls_back_unit(
    mode: str, stage: str
) -> None:
    """Interrupted driver calls cannot commit earlier statements or retain history."""
    database = await load_fixture(provide_database())
    base = {
        "001": "CREATE TABLE entries (id INTEGER PRIMARY KEY); INSERT INTO entries VALUES (7);"
    }
    await database.migrate(base)
    unit = "ALTER TABLE entries ADD COLUMN note TEXT; INSERT INTO entries (id) VALUES (1); INSERT INTO entries (id) VALUES (2);"
    started = Event()
    scope = CancelScope()
    native_execute = Connection.execute

    async def paused_execute(
        self: Connection, sql: str, parameters: Iterable[object] = ()
    ) -> Cursor:
        target = sql.strip() == "INSERT INTO entries (id) VALUES (2);"
        if target and stage == "before":
            started.set()
            await sleep_forever()
        cursor = await native_execute(self, sql, parameters)
        if target and stage == "after":
            try:
                started.set()
                await sleep_forever()
            finally:
                with CancelScope(shield=True):
                    await cursor.close()
        return cursor

    async def migrate() -> None:
        with scope:
            await database.migrate(base | {"002": unit})

    with patch.object(Connection, "execute", paused_execute), fail_after(2):
        migrating = asyncio.create_task(migrate())
        try:
            await started.wait()
            if mode == "native":
                migrating.cancel()
                with assert_raises(asyncio.CancelledError):
                    await migrating
            else:
                scope.cancel()
                await migrating
        finally:
            migrating.cancel()
            with CancelScope(shield=True):
                await asyncio.gather(migrating, return_exceptions=True)

    await database.verify_migrations(base)
    async with database.transaction() as transaction:
        rows = await transaction.fetch_all(sqlite.raw("SELECT * FROM entries"))
    assert_eq(rows, [{"id": 7}])
    result = await database.migrate(base | {"002": unit})
    assert_eq(result.applied, ("002",))


@test(mark="medium")
async def comments_cannot_hide_intervening_sql() -> None:
    """Separate block comments must not swallow the statement between them."""
    database = await load_fixture(provide_database())

    await database.migrate(
        {
            "unit": "CREATE TABLE entries (id INTEGER); /* before */ INSERT INTO entries VALUES (1) /* after */"
        }
    )
    async with database.transaction() as transaction:
        rows = await transaction.fetch_all(sqlite.raw("SELECT * FROM entries"))
    assert_eq(rows, [{"id": 1}])

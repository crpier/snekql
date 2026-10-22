"""Migration success requires the complete canonical history to remain intact."""

from snektest import Param, assert_eq, assert_raises, load_fixture, test

from snekql import mariadb
from tests.helpers import migration_functions, provide_mariadb_server


@test(
    [
        Param("DELETE FROM snekql_migrations", name="delete"),
        Param("UPDATE snekql_migrations SET position = 5", name="position"),
        Param("UPDATE snekql_migrations SET name = 'rewritten'", name="name"),
        Param(
            "INSERT INTO snekql_migrations VALUES (5, 'phantom', UTC_TIMESTAMP(3))",
            name="extra-row",
        ),
    ],
    mark="slow",
)
async def migration_cannot_commit_after_corrupting_earlier_history(body: str) -> None:
    """A body must not report success while leaving a non-prefix history behind."""
    server = await load_fixture(provide_mariadb_server())
    declaration = {"001": "CREATE TABLE entries (id INTEGER PRIMARY KEY) ENGINE=InnoDB"}

    async with await mariadb.Database.initialize(server.config()) as database:
        await database.migrate(migration_functions(declaration))

        with assert_raises(mariadb.MigrationError):
            await database.migrate(
                migration_functions(
                    {
                        **declaration,
                        "002": f"{body}; INSERT INTO entries VALUES (1)",
                    }
                )
            )

        status = await database.migration_status(migration_functions(declaration))
        assert_eq(status.applied, ("001",))


@test(mark="slow")
async def history_corruption_rolls_back_the_migration_body() -> None:
    """Rejecting changed history also undoes transactional application writes."""
    server = await load_fixture(provide_mariadb_server())
    declaration = {"001": "CREATE TABLE entries (id INTEGER PRIMARY KEY) ENGINE=InnoDB"}
    async with await mariadb.Database.initialize(server.config()) as database:
        await database.migrate(migration_functions(declaration))

        with assert_raises(mariadb.MigrationError):
            await database.migrate(
                migration_functions(
                    {
                        **declaration,
                        "002": "INSERT INTO entries VALUES (1); DELETE FROM snekql_migrations",
                    }
                )
            )

        async with database.transaction() as transaction:
            rows = await transaction.fetch_all(mariadb.raw("SELECT id FROM entries"))
        assert_eq(rows, [])


@test(mark="slow")
async def changed_history_schema_cannot_report_migration_success() -> None:
    """Owned history DDL is rejected before execution."""
    server = await load_fixture(provide_mariadb_server())
    async with await mariadb.Database.initialize(server.config()) as database:
        with assert_raises(mariadb.MigrationError):
            await database.migrate(
                migration_functions(
                    {
                        "001": "ALTER TABLE snekql_migrations ADD COLUMN extra INTEGER NULL",
                    }
                )
            )

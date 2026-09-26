"""Migration success requires the complete canonical history to remain intact."""

from snektest import Param, assert_eq, assert_raises, load_fixture, test

from snekql import mariadb
from tests.helpers import provide_mariadb_server


@test(
    [
        Param("DELETE FROM snekql_migrations", name="delete"),
        Param(
            "UPDATE snekql_migrations SET checksum = REPEAT('0', 64)", name="checksum"
        ),
        Param("UPDATE snekql_migrations SET name = 'rewritten'", name="name"),
        Param(
            "INSERT INTO snekql_migrations VALUES (5, 'phantom', REPEAT('0', 64), UTC_TIMESTAMP(3))",
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
        await database.migrate(declaration)

        with assert_raises(mariadb.MigrationHistoryError):
            await database.migrate(
                {
                    **declaration,
                    "002": f"{body}; INSERT INTO entries VALUES (1)",
                }
            )

        status = await database.migration_status(declaration)
        assert_eq(status.applied, ("001",))


@test(mark="slow")
async def history_corruption_rolls_back_the_migration_body() -> None:
    """Rejecting changed history also undoes transactional application writes."""
    server = await load_fixture(provide_mariadb_server())
    declaration = {"001": "CREATE TABLE entries (id INTEGER PRIMARY KEY) ENGINE=InnoDB"}
    async with await mariadb.Database.initialize(server.config()) as database:
        await database.migrate(declaration)

        with assert_raises(mariadb.MigrationHistoryError):
            await database.migrate(
                {
                    **declaration,
                    "002": "INSERT INTO entries VALUES (1); DELETE FROM snekql_migrations",
                }
            )

        async with database.transaction() as transaction:
            rows = await transaction.fetch_all(mariadb.raw("SELECT id FROM entries"))
        assert_eq(rows, [])


@test(mark="slow")
async def changed_history_schema_cannot_report_migration_success() -> None:
    """Implicitly committed DDL still needs repair, but cannot report success."""
    server = await load_fixture(provide_mariadb_server())
    async with await mariadb.Database.initialize(server.config()) as database:
        with assert_raises(mariadb.MigrationHistoryError):
            await database.migrate(
                {
                    "001": "ALTER TABLE snekql_migrations ADD COLUMN extra INTEGER NULL",
                }
            )

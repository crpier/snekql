"""Migration bodies are raw SQL, not driver interpolation templates."""

from __future__ import annotations

from snektest import Param, assert_eq, assert_raises, load_fixture, test

from snekql import mariadb
from tests.helpers import provide_mariadb_server


@test(
    [
        Param(value=("INSERT INTO message VALUES ('100%')", "100%"), name="single"),
        Param(value=("INSERT INTO message VALUES ('100%%')", "100%%"), name="double"),
        Param(value=("INSERT INTO message VALUES ('%s')", "%s"), name="positional"),
        Param(
            value=("INSERT INTO message VALUES ('%(name)s')", "%(name)s"),
            name="named",
        ),
    ],
    mark="slow",
)
async def migration_preserves_percent_literal(case: tuple[str, str]) -> None:
    """Percent characters in raw SQL are not Python formatting instructions."""

    server = await load_fixture(provide_mariadb_server())

    class Message[S = mariadb.Pending](mariadb.Model[S, "Message[mariadb.Fetched]"]):
        """Migration-produced text read through the public query runtime."""

        text: Message.Col[str] = mariadb.Text()

    async with await mariadb.Database.initialize(server.config()) as database:
        await database.migrate(
            {
                "create": "CREATE TABLE message (text TEXT NOT NULL) ENGINE=InnoDB",
                "insert": case[0],
            }
        )
        async with database.transaction() as transaction:
            stored = await transaction.fetch_one(mariadb.select(Message.text).all())

    assert_eq(stored, case[1])


@test(
    [
        Param(value="INSERT INTO measurement SELECT 11 % 4", name="modulo"),
        Param(
            value="INSERT INTO measurement SELECT LENGTH('abc') WHERE 'abc' LIKE 'a%'",
            name="like",
        ),
    ],
    mark="slow",
)
async def migration_executes_percent_expression(body: str) -> None:
    """MariaDB evaluates percent operators and patterns in raw migration SQL."""

    server = await load_fixture(provide_mariadb_server())

    class Measurement[S = mariadb.Pending](
        mariadb.Model[S, "Measurement[mariadb.Fetched]"]
    ):
        """An integer result produced by migration SQL."""

        value: Measurement.Col[int] = mariadb.Integer()

    async with await mariadb.Database.initialize(server.config()) as database:
        await database.migrate(
            {
                "create": "CREATE TABLE measurement (value BIGINT NOT NULL) ENGINE=InnoDB",
                "compute": body,
            }
        )
        async with database.transaction() as transaction:
            stored = await transaction.fetch_one(
                mariadb.select(Measurement.value).all()
            )

    assert_eq(stored, 3)


@test(mark="slow")
async def migration_history_binds_percent_bearing_names() -> None:
    """Opaque migration names remain bound values, including quotes and percent signs."""

    server = await load_fixture(provide_mariadb_server())
    declaration = {"name'%s%%%(name)s": "SELECT '100%%'"}

    async with await mariadb.Database.initialize(server.config()) as database:
        await database.migrate(declaration)
        await database.verify_migrations(declaration)
        repeated = await database.migrate(declaration)

    assert_eq(repeated.already_applied, ("name'%s%%%(name)s",))
    assert_eq(repeated.applied, ())


@test(mark="slow")
async def migration_history_keeps_exact_percent_checksum() -> None:
    """Percent correction does not normalize or rewrite historical body checksums."""

    server = await load_fixture(provide_mariadb_server())
    async with await mariadb.Database.initialize(server.config()) as database:
        await database.migrate({"body": "SELECT '100%%'"})

        with assert_raises(mariadb.MigrationHistoryError):
            await database.verify_migrations({"body": "SELECT '100%'"})

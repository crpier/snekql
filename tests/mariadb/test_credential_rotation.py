"""Credential rotation replaces the Database while existing Transactions drain."""

from collections.abc import AsyncGenerator
from dataclasses import replace

from snektest import assert_eq, fixture, load_fixture, test

from benchmarks._artifacts import mariadb_artifacts
from snekql import mariadb
from snekql.testing.mariadb import TemporaryMariaDBServer, temporary_mariadb_server


@fixture
async def provide_authenticated_server() -> AsyncGenerator[TemporaryMariaDBServer]:
    """Create an application account separate from the fixture's administrator."""
    async with (
        mariadb_artifacts() as root,
        temporary_mariadb_server(
            auth="password", transports={"tcp"}, runtime_base_directory=root
        ) as server,
    ):
        await server.run_sql(
            "CREATE USER 'rotating'@'%' IDENTIFIED BY 'first-password';"
            "GRANT ALL ON test.* TO 'rotating'@'%';"
        )
        yield server


@test(mark="slow")
async def replacement_pool_accepts_rotated_credentials() -> None:
    """A fresh Database authenticates with new credentials while old work completes."""
    server = await load_fixture(provide_authenticated_server())
    config = replace(
        server.config(pool_size=1), user="rotating", password="first-password"
    )
    async with (
        await mariadb.Database.initialize(config) as old_database,
        old_database.transaction() as existing,
    ):
        await server.run_sql(
            "ALTER USER 'rotating'@'%' IDENTIFIED BY 'second-password'"
        )
        async with await mariadb.Database.initialize(
            replace(config, password="second-password")
        ) as replacement:
            async with replacement.transaction() as fresh:
                rows = await fresh.fetch_all(
                    mariadb.raw("SELECT CURRENT_USER() AS account")
                )
            assert_eq(rows, [{"account": "rotating@%"}])
            await existing.fetch_all(mariadb.raw("SELECT 1"))

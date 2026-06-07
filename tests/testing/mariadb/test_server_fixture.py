"""MariaDB test server fixture contract tests."""

from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory

from snektest import assert_eq, assert_in, load_fixture, test

from snekql.testing.mariadb import temporary_mariadb_server
from tests.helpers import provide_mariadb_server


@test(mark="medium")
async def mariadb_server_fixture_starts_queryable_server() -> None:
    """The shared fixture provides a local unprivileged MariaDB server."""

    server = await load_fixture(provide_mariadb_server())
    result = await server.run_sql("SELECT 1")

    assert_in("1", result.stdout)


@test(mark="medium")
async def mariadb_server_fixture_reset_drops_tables_from_reused_data_dir() -> None:
    """The shared fixture can reuse a data directory without stale tables."""

    with TemporaryDirectory() as temporary_directory:
        data_directory = Path(temporary_directory) / "data"
        async with temporary_mariadb_server(data_directory=data_directory) as server:
            _ = await server.run_sql("CREATE TABLE stale_fixture_table (`id` INT)")

        async with temporary_mariadb_server(data_directory=data_directory) as server:
            await server.reset_database()
            result = await server.run_sql("SHOW TABLES LIKE 'stale_fixture_table'")

    assert_eq(result.stdout, "")

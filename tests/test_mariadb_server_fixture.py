"""MariaDB test server fixture contract tests."""

from __future__ import annotations

from snektest import assert_in, load_fixture, test

from tests.mariadb_server import provide_mariadb_server


@test(mark="medium")
def mariadb_server_fixture_starts_queryable_server() -> None:
    """The shared fixture provides a local unprivileged MariaDB server."""

    server = load_fixture(provide_mariadb_server())
    result = server.run_sql("SELECT 1")

    assert_in("1", result.stdout)

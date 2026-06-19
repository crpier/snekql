"""Backend identity runtime safety tests."""

from __future__ import annotations

from snektest import assert_in, assert_raises, load_fixture, test

from snekql import mariadb, sqlite
from snekql.sqlite import (
    Database,
    DatabaseRuntimeError,
    Fetched,
    Model,
    Pending,
    Text,
    select,
)
from tests.helpers import TemporaryMariaDBServer, provide_mariadb_server


class SqliteIdentityUser[S = Pending](sqlite.Model[S, "SqliteIdentityUser[Fetched]"]):
    """SQLite table model for backend identity checks."""

    email: SqliteIdentityUser.Col[str] = sqlite.Text(nullable=False)


class LegacyIdentityUser[S = Pending](Model[S, "LegacyIdentityUser[Fetched]"]):
    """Legacy top-level model remains a SQLite declaration."""

    email: LegacyIdentityUser.Col[str] = Text(nullable=False)


class MariadbIdentityUser[S = Pending](
    mariadb.Model[S, "MariadbIdentityUser[Fetched]"]
):
    """MariaDB table model for backend identity checks."""

    email: MariadbIdentityUser.Col[str] = mariadb.Text(nullable=False)


def _config_from_server(server: TemporaryMariaDBServer) -> mariadb.Config:
    """Build a MariaDB config for the shared local test server."""

    return server.config()


@test(mark="medium")
async def sqlite_initialization_rejects_mariadb_models() -> None:
    """SQLite Database startup rejects MariaDB Table Models."""

    with assert_raises(DatabaseRuntimeError) as error:
        _ = await Database.initialize(database=":memory:", models=[MariadbIdentityUser])

    assert_in("expected sqlite", str(error.exception))
    assert_in("received mariadb", str(error.exception))


@test(mark="medium")
async def mariadb_initialization_rejects_sqlite_models() -> None:
    """MariaDB Database startup rejects SQLite Table Models."""

    with assert_raises(DatabaseRuntimeError) as error:
        _ = await Database.initialize(
            mariadb.Config(database="app", user="snekql"),
            models=[SqliteIdentityUser],
        )

    assert_in("expected mariadb", str(error.exception))
    assert_in("received sqlite", str(error.exception))


@test(mark="medium")
async def sqlite_transaction_rejects_mariadb_queries() -> None:
    """SQLite Transactions reject MariaDB queries."""

    sqlite_database = await Database.initialize(database=":memory:")
    try:
        async with sqlite_database.transaction() as tx:
            with assert_raises(DatabaseRuntimeError) as error:
                _ = await tx.fetch_all(select(MariadbIdentityUser).all())
    finally:
        await sqlite_database.close()

    assert_in("expected sqlite", str(error.exception))
    assert_in("received mariadb", str(error.exception))


@test(mark="medium")
async def mariadb_transaction_rejects_sqlite_queries() -> None:
    """MariaDB Transactions reject SQLite queries."""

    server = await load_fixture(provide_mariadb_server())

    mariadb_database = await Database.initialize(_config_from_server(server))
    try:
        async with mariadb_database.transaction() as tx:
            with assert_raises(DatabaseRuntimeError) as error:
                _ = await tx.fetch_all(select(SqliteIdentityUser).all())
    finally:
        await mariadb_database.close()

    assert_in("expected mariadb", str(error.exception))
    assert_in("received sqlite", str(error.exception))


@test()
def legacy_top_level_model_is_a_sqlite_declaration() -> None:
    """Compatibility aliases keep behaving as SQLite declarations."""

    assert_in("sqlite", LegacyIdentityUser.__snekql_backend__)
    assert_in("sqlite", SqliteIdentityUser.__snekql_backend__)
    assert_in("mariadb", MariadbIdentityUser.__snekql_backend__)

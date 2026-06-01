"""Backend identity runtime safety tests."""

from __future__ import annotations

from snektest import assert_in, assert_raises, load_fixture, test

from snekql import (
    Database,
    DatabaseRuntimeError,
    Model,
    Pending,
    Text,
    mariadb,
    select,
    sqlite,
)
from tests.logging_helpers import NULL_LOGGER
from tests.mariadb_server import MariaDBServer, provide_mariadb_server


class SqliteIdentityUser[S = Pending](sqlite.Model[S, "SqliteIdentityUser[object]"]):
    """SQLite table model for backend identity checks."""

    email: SqliteIdentityUser.Col[str] = sqlite.Text(nullable=False)


class LegacyIdentityUser[S = Pending](Model[S, "LegacyIdentityUser[object]"]):
    """Legacy top-level model remains a SQLite declaration."""

    email: LegacyIdentityUser.Col[str] = Text(nullable=False)


class MariadbIdentityUser[S = Pending](mariadb.Model[S, "MariadbIdentityUser[object]"]):
    """MariaDB table model for backend identity checks."""

    email: MariadbIdentityUser.Col[str] = mariadb.Text(nullable=False)


def _config_from_server(server: MariaDBServer) -> mariadb.Config:
    """Build a MariaDB config for the shared local test server."""

    return mariadb.Config(
        database=server.database,
        host=server.host,
        port=server.port,
        user=server.user,
    )


@test(mark="medium")
async def initialization_rejects_models_from_the_wrong_backend() -> None:
    """Database startup rejects model/config backend mismatches before runtime work."""

    with assert_raises(DatabaseRuntimeError) as sqlite_error:
        _ = await Database.initialize(
            NULL_LOGGER, database=":memory:", models=[MariadbIdentityUser]
        )
    assert_in("expected sqlite", str(sqlite_error.exception))
    assert_in("received mariadb", str(sqlite_error.exception))

    with assert_raises(DatabaseRuntimeError) as mariadb_error:
        _ = await Database.initialize(
            NULL_LOGGER,
            mariadb.Config(database="app", user="snekql"),
            models=[SqliteIdentityUser],
        )
    assert_in("expected mariadb", str(mariadb_error.exception))
    assert_in("received sqlite", str(mariadb_error.exception))


@test(mark="medium")
async def transactions_reject_queries_from_the_wrong_backend() -> None:
    """Transactions reject query/model backends that do not match their runtime."""

    sqlite_database = await Database.initialize(NULL_LOGGER, database=":memory:")
    try:
        async with sqlite_database.transaction() as transaction:
            with assert_raises(DatabaseRuntimeError) as error:
                _ = await transaction.fetch_all(select(MariadbIdentityUser).all())
        assert_in("expected sqlite", str(error.exception))
        assert_in("received mariadb", str(error.exception))
    finally:
        await sqlite_database.close()

    server = load_fixture(provide_mariadb_server())
    mariadb_database = await Database.initialize(
        NULL_LOGGER, _config_from_server(server)
    )
    try:
        async with mariadb_database.transaction() as transaction:
            with assert_raises(DatabaseRuntimeError) as error:
                _ = await transaction.fetch_all(select(SqliteIdentityUser).all())
        assert_in("expected mariadb", str(error.exception))
        assert_in("received sqlite", str(error.exception))
    finally:
        await mariadb_database.close()


@test()
def legacy_top_level_model_is_a_sqlite_declaration() -> None:
    """Compatibility aliases keep behaving as SQLite declarations."""

    assert_in("sqlite", LegacyIdentityUser.__snekql_backend__)
    assert_in("sqlite", SqliteIdentityUser.__snekql_backend__)
    assert_in("mariadb", MariadbIdentityUser.__snekql_backend__)

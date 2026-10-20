"""Self-contained driver contracts, also copied into isolated wheel installs."""

from collections.abc import AsyncGenerator
from typing import ClassVar

from snektest import assert_eq, fixture, load_fixture, test

from snekql import mariadb
from snekql.testing.mariadb import TemporaryMariaDBServer, temporary_mariadb_server


@fixture(scope="session")
async def provide_artifact_server() -> AsyncGenerator[TemporaryMariaDBServer]:
    """Keep native server ownership inside the installed-package test process."""
    async with temporary_mariadb_server() as server:
        yield server


@fixture
async def provide_empty_database() -> AsyncGenerator[mariadb.Database]:
    """Each test starts with an empty database, not inherited migration history."""
    server = await load_fixture(provide_artifact_server())
    await server.reset_database()
    async with await mariadb.Database.initialize(server.config()) as database:
        yield database


@test(mark="slow")
async def revision_identity_survives_driver_binding() -> None:
    """A fresh driver installation can persist and verify revision IDs."""
    database = await load_fixture(provide_empty_database())

    async def create_probe(migration: mariadb.MigrationContext) -> None:
        await migration.execute("CREATE TABLE driver_probe (id INTEGER PRIMARY KEY)")
        assert_eq(
            await migration.execute(
                "INSERT INTO driver_probe VALUES (%s)", params=(7,)
            ),
            1,
        )
        assert_eq(
            await migration.fetch_all(
                "SELECT id FROM driver_probe WHERE id=%s", params=(7,)
            ),
            [(7,)],
        )

    declaration = {"001_probe": create_probe}

    result = await database.migrate(declaration)
    await database.verify_migrations(declaration)

    assert_eq(result.applied, ("001_probe",))


@test(mark="slow")
async def binary_values_survive_driver_binding() -> None:
    """All byte values round-trip without text decoding or SQL escape damage."""
    database = await load_fixture(provide_empty_database())

    class BinaryRecord[S = mariadb.Pending](mariadb.Model[S]):
        __row_type__: ClassVar[mariadb.ReadType[BinaryRecord[mariadb.Row]]]
        id: mariadb.Col[int] = mariadb.Integer(primary_key=True)
        payload: mariadb.Col[bytes] = mariadb.Blob()

    async def create_binary(migration: mariadb.MigrationContext) -> None:
        await migration.execute(
            "CREATE TABLE binary_record (id BIGINT NOT NULL PRIMARY KEY, "
            "payload BLOB NOT NULL) ENGINE=InnoDB"
        )

    await database.migrate({"001_binary": create_binary})
    async with database.transaction() as transaction:
        await transaction.execute(
            mariadb.insert(BinaryRecord(id=1, payload=bytes(range(256))))
        )

    async with database.transaction() as transaction:
        observed = await transaction.fetch_one(
            mariadb.select(BinaryRecord.payload).where(BinaryRecord.id.eq(1))
        )

    assert_eq(observed, bytes(range(256)))

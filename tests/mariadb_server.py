"""Shared MariaDB server fixture for integration tests."""

from __future__ import annotations

from pathlib import Path

from snektest import AsyncSessionFixture

from snekql.testing.mariadb import (
    TemporaryMariaDBServer,
    temporary_mariadb_server,
)


async def provide_mariadb_server() -> AsyncSessionFixture[TemporaryMariaDBServer]:
    """Provide a local MariaDB server for medium integration tests."""

    async with temporary_mariadb_server(
        data_directory=Path(".snektest/mariadb-data"),
        reset_database=True,
        transports={"tcp"},
    ) as server:
        yield server

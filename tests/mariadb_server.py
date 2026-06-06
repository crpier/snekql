"""Shared MariaDB server fixture for integration tests."""

from __future__ import annotations

from collections.abc import AsyncGenerator
from pathlib import Path

from snektest import session_fixture

from snekql.testing.mariadb import (
    TemporaryMariaDBServer,
    temporary_mariadb_server,
)


@session_fixture()
async def provide_mariadb_server() -> AsyncGenerator[TemporaryMariaDBServer]:
    """Provide a local MariaDB server for medium integration tests."""

    async with temporary_mariadb_server(
        data_directory=Path(".snektest/mariadb-data"),
        clean_before_start=True,
        transports={"tcp"},
    ) as server:
        yield server

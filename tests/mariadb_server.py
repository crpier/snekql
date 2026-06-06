"""Shared MariaDB server fixture for integration tests."""

from __future__ import annotations

from collections.abc import AsyncGenerator

from snekql.testing.mariadb import (
    TemporaryMariaDBServer,
    temporary_mariadb_server,
)

MariaDBServer = TemporaryMariaDBServer


async def provide_mariadb_server() -> AsyncGenerator[MariaDBServer]:
    """Provide a local MariaDB server for medium integration tests."""

    async with temporary_mariadb_server(transports={"tcp"}) as server:
        yield server

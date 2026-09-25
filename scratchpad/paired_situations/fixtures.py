"""Disposable MariaDB owned by this local comparison."""

from collections.abc import AsyncGenerator
from pathlib import Path

from anyio import to_thread
from snekql.testing.mariadb import TemporaryMariaDBServer, temporary_mariadb_server
from snektest import fixture


@fixture(scope="session")
async def server() -> AsyncGenerator[TemporaryMariaDBServer]:
    async with temporary_mariadb_server(
        data_directory=Path(".git/approach-situations/mariadb"),
        socket_path=await to_thread.run_sync(Path(".git/situations.sock").resolve),
        transports={"unix_socket"},
        reset_database=True,
    ) as instance:
        yield instance

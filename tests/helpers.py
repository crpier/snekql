"""Shared test helpers and fixtures."""

from __future__ import annotations

from pathlib import Path

from snektest import AsyncSessionFixture

from snekql.testing.mariadb import (
    TemporaryMariaDBServer,
    temporary_mariadb_server,
)


class NullStructuredLogger:
    """Structured logger fake that intentionally ignores all events."""

    def debug(self, event: str, **fields: object) -> None:
        _ = event
        _ = fields

    def info(self, event: str, **fields: object) -> None:
        _ = event
        _ = fields

    def warning(self, event: str, **fields: object) -> None:
        _ = event
        _ = fields

    def error(self, event: str, **fields: object) -> None:
        _ = event
        _ = fields


NULL_LOGGER = NullStructuredLogger()


async def provide_mariadb_server() -> AsyncSessionFixture[TemporaryMariaDBServer]:
    """Provide a local MariaDB server for medium integration tests."""

    async with temporary_mariadb_server(
        data_directory=Path(".snektest/mariadb-data"),
        reset_database=True,
        transports={"tcp"},
    ) as server:
        yield server

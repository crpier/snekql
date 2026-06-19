"""Shared test helpers and fixtures."""

from __future__ import annotations

import logging
from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path

from snektest import AsyncSessionFixture

from snekql.testing.mariadb import (
    TemporaryMariaDBServer,
    temporary_mariadb_server,
)


class SnekqlLogCapture(logging.Handler):
    """Logging handler that records every ``snekql`` record for assertions."""

    def __init__(self) -> None:
        super().__init__()
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)

    def messages(self, level: int) -> list[str]:
        """Return rendered messages recorded at exactly the given level."""

        return [
            record.getMessage() for record in self.records if record.levelno == level
        ]

    def has(self, level: int, fragment: str) -> bool:
        """Return whether a record at the level contains the fragment."""

        return any(fragment in message for message in self.messages(level))

    def find(self, level: int, fragment: str) -> str:
        """Return the first rendered message at the level containing fragment."""

        for message in self.messages(level):
            if fragment in message:
                return message
        msg = f"no {logging.getLevelName(level)} message contained {fragment!r}"
        raise AssertionError(msg)


@contextmanager
def capture_snekql_logs() -> Generator[SnekqlLogCapture]:
    """Capture all ``snekql`` log records at DEBUG for the block's duration."""

    logger = logging.getLogger("snekql")
    handler = SnekqlLogCapture()
    previous_level = logger.level
    logger.addHandler(handler)
    logger.setLevel(logging.DEBUG)
    try:
        yield handler
    finally:
        logger.setLevel(previous_level)
        logger.removeHandler(handler)


async def provide_mariadb_server() -> AsyncSessionFixture[TemporaryMariaDBServer]:
    """Provide a local MariaDB server for medium integration tests."""

    async with temporary_mariadb_server(
        data_directory=Path(".snektest/mariadb-data"),
        reset_database=True,
        transports={"tcp"},
    ) as server:
        yield server

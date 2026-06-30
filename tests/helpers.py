"""Shared test helpers and fixtures."""

from __future__ import annotations

import logging
from collections.abc import AsyncGenerator, Generator, Sequence
from contextlib import contextmanager
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

from snektest import fixture

from snekql.mariadb.schema import scaffold_mariadb_statements
from snekql.runtime import Database
from snekql.sqlite._schema_ddl import scaffold_sqlite_statements
from snekql.storage import SchemaPolicy
from snekql.testing.mariadb import (
    TemporaryMariaDBServer,
    temporary_mariadb_server,
)

if TYPE_CHECKING:
    from snekql._runtime_selection import RuntimeConfig
    from snekql.model import Table


def scaffold_migrations(
    backend_family: str,
    models: Sequence[type[Table[Any]]],
) -> dict[str, str]:
    """Build a Migration mapping that creates ``models`` via the scaffold DDL.

    This is the documented test pattern (ADR 0007): tests build their schema by
    replaying a real Migration chain, never a model-direct shortcut. Scaffolding
    then migrating is exactly the production construction path.
    """

    if backend_family == "sqlite":
        statements = scaffold_sqlite_statements(models)
    elif backend_family == "mariadb":
        statements = scaffold_mariadb_statements(models)
    else:
        msg = f"unknown backend family {backend_family!r}"
        raise ValueError(msg)
    return {
        f"{index:03d}_{label}": sql for index, (label, sql) in enumerate(statements)
    }


async def migrate_models(db: Database, models: Sequence[type[Table[Any]]]) -> None:
    """Build ``models``' schema on ``db`` by replaying scaffolded Migrations."""

    await db.migrate(scaffold_migrations(db.runtime.backend_family, models))


async def initialized_database(
    backend: RuntimeConfig | None = None,
    *,
    database: Path | Literal[":memory:"] | None = None,
    models: Sequence[type[Table[Any]]] = (),
    verify: bool = False,
    policy: SchemaPolicy = "strict",
    **init_kwargs: Any,
) -> Database:
    """Initialize a Database and build ``models``' schema via scaffold+migrate.

    Mirrors the old ``Database.initialize(models=...)`` convenience for tests
    that just need a populated schema, but goes through the real connect ->
    migrate (-> verify) path so a broken scaffold or migration fails the test.
    """

    if backend is not None:
        db = await Database.initialize(backend, **init_kwargs)
    else:
        assert database is not None
        db = await Database.initialize(database=database, **init_kwargs)
    if models:
        await migrate_models(db, models)
        if verify:
            await db.verify(models, policy=policy)
    return db


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


@fixture(scope="session")
async def provide_mariadb_server() -> AsyncGenerator[TemporaryMariaDBServer]:
    """Provide a local MariaDB server for medium integration tests."""

    async with temporary_mariadb_server(
        data_directory=Path(".snektest/mariadb-data"),
        reset_database=True,
        transports={"tcp"},
    ) as server:
        yield server

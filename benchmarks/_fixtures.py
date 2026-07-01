"""snektest fixtures providing ready-to-use benchmark databases.

A fixture handle doubles as an async context manager, so the standalone
concurrency driver consumes these with ``async with`` -- no snektest runner
required -- while getting fixture-style setup and deterministic teardown for
free. Each fixture yields a database that is already connected, migrated, and
seeded; on block exit it is closed.
"""

from __future__ import annotations

import secrets
from collections.abc import AsyncGenerator
from pathlib import Path

from snektest import fixture

from benchmarks import _models_mariadb, _models_sqlite
from benchmarks._workloads import BackendQueryApi, seed_rows
from snekql.runtime import Database
from snekql.testing.mariadb import TemporaryMariaDBServer, temporary_mariadb_server
from tests.helpers import migrate_models


@fixture
async def benchmark_mariadb_server() -> AsyncGenerator[TemporaryMariaDBServer]:
    """Provide a throwaway MariaDB server for the duration of the block."""

    async with temporary_mariadb_server(
        data_directory=Path(".snektest/bench-mariadb-data"),
        reset_database=True,
        transports={"tcp"},
    ) as server:
        yield server


@fixture
async def sqlite_benchmark_database(
    directory: Path,
    api: BackendQueryApi,
    *,
    pool_size: int,
    rows: int,
) -> AsyncGenerator[Database]:
    """Provide a migrated, seeded file-backed SQLite database.

    Each instance gets its own database file, so separate scenarios never share
    accumulated rows.
    """

    path = directory / f"bench_{secrets.token_hex(8)}.db"
    db = await Database.initialize(database=path, pool_size=pool_size)
    try:
        await migrate_models(db, _models_sqlite.MODELS)
        await seed_rows(api, db, rows)
        yield db
    finally:
        await db.close()


@fixture
async def mariadb_benchmark_database(
    server: TemporaryMariaDBServer,
    api: BackendQueryApi,
    *,
    pool_size: int,
    rows: int,
) -> AsyncGenerator[Database]:
    """Provide a migrated, seeded database on a throwaway MariaDB ``server``.

    All instances share the one server (and therefore one schema), matching the
    original driver: migrations are applied idempotently and seed rows
    accumulate across pool sizes.
    """

    db = await Database.initialize(server.config(pool_size=pool_size))
    try:
        await migrate_models(db, _models_mariadb.MODELS)
        await seed_rows(api, db, rows)
        yield db
    finally:
        await db.close()

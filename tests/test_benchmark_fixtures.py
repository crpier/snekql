"""Tests for the benchmark database fixtures.

The concurrency benchmark driver consumes these snektest fixtures standalone
(via ``async with``); the contract they must uphold is "yield a migrated,
seeded, usable Database and close it on exit". Only the SQLite fixture is
covered here: it needs no external server, so it is deterministic in CI. The
MariaDB fixture shares its shape but requires the MariaDB binaries.
"""

from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory

from snektest import assert_eq, assert_raises, test

from benchmarks import _models_sqlite
from benchmarks._fixtures import sqlite_benchmark_database
from benchmarks._workloads import BackendQueryApi
from snekql.runtime import DatabaseRuntimeError
from snekql.sqlite import insert as sqlite_insert
from snekql.sqlite import select as sqlite_select

_API = BackendQueryApi(
    model=_models_sqlite.BenchUser,
    select=sqlite_select,
    insert=sqlite_insert,
)


@test(mark="medium")
async def sqlite_fixture_yields_migrated_seeded_database() -> None:
    with TemporaryDirectory() as directory:
        async with (
            sqlite_benchmark_database(Path(directory), _API, pool_size=2, rows=7) as db,
            db.transaction() as tx,
        ):
            rows = await tx.fetch_all(sqlite_select(_models_sqlite.BenchUser).all())

        assert_eq(len(rows), 7)


@test(mark="medium")
async def sqlite_fixture_closes_database_on_exit() -> None:
    with TemporaryDirectory() as directory:
        async with sqlite_benchmark_database(
            Path(directory), _API, pool_size=1, rows=1
        ) as db:
            pass

        with assert_raises(DatabaseRuntimeError):
            async with db.transaction():
                pass


@test(mark="medium")
async def sqlite_fixture_instances_are_independent() -> None:
    with TemporaryDirectory() as directory:
        handle = sqlite_benchmark_database
        async with (
            handle(Path(directory), _API, pool_size=1, rows=3) as first,
            handle(Path(directory), _API, pool_size=1, rows=5) as second,
        ):
            async with first.transaction() as tx:
                first_rows = await tx.fetch_all(
                    sqlite_select(_models_sqlite.BenchUser).all()
                )
            async with second.transaction() as tx:
                second_rows = await tx.fetch_all(
                    sqlite_select(_models_sqlite.BenchUser).all()
                )

        assert_eq(len(first_rows), 3)
        assert_eq(len(second_rows), 5)

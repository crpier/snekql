"""Entry point for the snekql concurrency benchmarks.

Run everything that is locally available::

    uv run python -m benchmarks.run

Restrict to one backend or tune the load::

    uv run python -m benchmarks.run --backend sqlite --duration 5
    uv run python -m benchmarks.run --backend mariadb --rows 20000

MariaDB scenarios spin up a throwaway server via the project's
``TemporaryMariaDBServer`` helper; they are skipped automatically when the
MariaDB binaries are not installed.
"""

from __future__ import annotations

import argparse
import asyncio
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from benchmarks import _models_mariadb, _models_sqlite
from benchmarks._harness import BenchmarkReport, format_report, run_concurrent
from benchmarks._workloads import (
    BackendQueryApi,
    large_select,
    mixed_read_write,
    point_read,
    seed_rows,
    write_row,
)
from snekql import mariadb
from snekql.runtime import Database
from snekql.sqlite import insert as sqlite_insert
from snekql.sqlite import select as sqlite_select
from snekql.testing.mariadb import temporary_mariadb_server
from tests.helpers import migrate_models

_SQLITE_API = BackendQueryApi(
    model=_models_sqlite.BenchUser,
    select=sqlite_select,
    insert=sqlite_insert,
)
_MARIADB_API = BackendQueryApi(
    model=_models_mariadb.BenchUser,
    select=mariadb.select,
    insert=mariadb.insert,
)


@dataclass
class BenchConfig:
    """Tunables shared across scenarios."""

    duration: float
    rows: int
    pool_sizes: Sequence[int]
    worker_counts: Sequence[int]
    large_select_limit: int


def _section(title: str) -> None:
    print()
    print("=" * 72)
    print(title)
    print("=" * 72)


async def _run_scenarios(
    backend_label: str,
    make_db: Any,
    api: BackendQueryApi,
    config: BenchConfig,
) -> list[BenchmarkReport]:
    """Run the full scenario matrix against one backend factory."""

    reports: list[BenchmarkReport] = []
    representative_pool = max(config.pool_sizes)
    representative_workers = max(config.worker_counts)

    # Sweep every workload mix across the pool-size axis: point reads run the
    # full worker sweep (the headline fairness + throughput matrix), while the
    # write-heavy and mixed workloads run at the peak worker count for each pool
    # size so workload mix and pool size are crossed, not measured in isolation.
    for pool_size in config.pool_sizes:
        db = await make_db(pool_size)
        try:
            await seed_rows(api, db, config.rows)
            for workers in config.worker_counts:
                report = await run_concurrent(
                    f"{backend_label} point-read pool={pool_size} workers={workers}",
                    point_read(api, db, config.rows),
                    workers=workers,
                    duration=config.duration,
                )
                reports.append(report)
                print(format_report(report))
                print()
            for label, op in (
                ("write", write_row(api, db)),
                ("mixed", mixed_read_write(api, db, config.rows)),
            ):
                scenario = f"{backend_label} {label} pool={pool_size}"
                scenario += f" workers={representative_workers}"
                report = await run_concurrent(
                    scenario,
                    op,
                    workers=representative_workers,
                    duration=config.duration,
                )
                reports.append(report)
                print(format_report(report))
                print()
        finally:
            await db.close()

    # Large-result materialization: the event-loop-stall probe.
    db = await make_db(representative_pool)
    try:
        await seed_rows(api, db, config.large_select_limit)
        scenario = f"{backend_label} large-select rows={config.large_select_limit}"
        scenario += f" pool={representative_pool}"
        report = await run_concurrent(
            scenario,
            large_select(api, db, config.large_select_limit),
            workers=4,
            duration=config.duration,
        )
        reports.append(report)
        print(format_report(report))
        print()
    finally:
        await db.close()

    return reports


async def run_sqlite(config: BenchConfig, directory: Path) -> list[BenchmarkReport]:
    """Run scenarios against file-backed SQLite."""

    _section("SQLite (file-backed, WAL)")

    counter = {"n": 0}

    async def make_db(pool_size: int) -> Database:
        counter["n"] += 1
        path = directory / f"bench_{counter['n']}.db"
        db = await Database.initialize(database=path, pool_size=pool_size)
        await migrate_models(db, _models_sqlite.MODELS)
        return db

    return await _run_scenarios("sqlite", make_db, _SQLITE_API, config)


async def run_mariadb(config: BenchConfig) -> list[BenchmarkReport]:
    """Run scenarios against a throwaway MariaDB server, if available."""

    _section("MariaDB (throwaway server)")
    try:
        async with temporary_mariadb_server(
            data_directory=Path(".snektest/bench-mariadb-data"),
            reset_database=True,
            transports={"tcp"},
        ) as server:

            async def make_db(pool_size: int) -> Database:
                backend = server.config(pool_size=pool_size)
                db = await Database.initialize(backend)
                await migrate_models(db, _models_mariadb.MODELS)
                return db

            return await _run_scenarios("mariadb", make_db, _MARIADB_API, config)
    except Exception as error:
        print(f"MariaDB benchmark skipped: {error!r}")
        return []


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="snekql concurrency benchmarks")
    _ = parser.add_argument(
        "--backend",
        choices=("all", "sqlite", "mariadb"),
        default="all",
    )
    _ = parser.add_argument("--duration", type=float, default=3.0)
    _ = parser.add_argument("--rows", type=int, default=5000)
    _ = parser.add_argument("--large-select-rows", type=int, default=20000)
    _ = parser.add_argument("--pool-sizes", type=int, nargs="+", default=[1, 4, 16])
    _ = parser.add_argument("--worker-counts", type=int, nargs="+", default=[1, 8, 32])
    return parser.parse_args(argv)


async def _main_async(args: argparse.Namespace) -> None:
    config = BenchConfig(
        duration=args.duration,
        rows=args.rows,
        pool_sizes=args.pool_sizes,
        worker_counts=args.worker_counts,
        large_select_limit=args.large_select_rows,
    )
    if args.backend in ("all", "sqlite"):
        with TemporaryDirectory() as directory:
            _ = await run_sqlite(config, Path(directory))
    if args.backend in ("all", "mariadb"):
        _ = await run_mariadb(config)


def main(argv: Sequence[str] | None = None) -> None:
    args = _parse_args(argv)
    asyncio.run(_main_async(args))


if __name__ == "__main__":
    main()

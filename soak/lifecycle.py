"""Opt-in Linux resource soak, separate from deterministic test discovery."""

import asyncio
import gc
import json
import sys
from argparse import ArgumentParser
from contextlib import AsyncExitStack
from pathlib import Path
from resource import RUSAGE_SELF, getrusage
from threading import active_count
from typing import Any

from anyio import fail_after
from snektest import assert_eq, assert_raises, assert_true

from snekql import mariadb, sqlite
from snekql.model import BackendFamily
from snekql.runtime import Database
from snekql.testing.mariadb import temporary_mariadb_server


def _sample() -> dict[str, int]:
    """Collect after garbage collection; callers run this blocking sample in a worker."""
    gc.collect()
    return {
        "descriptors": len(list(Path("/proc/self/fd").iterdir())),
        "peak_rss_kib": getrusage(RUSAGE_SELF).ru_maxrss,
        "threads": active_count(),
    }


async def _run_cycles(
    backend: BackendFamily, cycles: int, config: mariadb.Config | None
) -> None:
    namespace = sqlite if backend == "sqlite" else mariadb

    async def cycle() -> None:
        with fail_after(10):
            # The branch and namespace select the same backend; resource checks use the shared API.
            database: Database[Any] = (
                await mariadb.Database.initialize(config)
                if config is not None
                else await sqlite.Database.initialize(database=":memory:", pool_size=1)
            )
            async with database:
                async with database.transaction() as owner:

                    async def wait_for_lease() -> None:
                        async with database.transaction():
                            message = "waiter entered a fully occupied pool"
                            raise AssertionError(message)

                    async with asyncio.TaskGroup() as tasks:
                        waiter = tasks.create_task(wait_for_lease())
                        # The public pool snapshot is the admission barrier; no sleep duration is assumed.
                        while database.pool_stats().waiters != 1:  # noqa: ASYNC110
                            await asyncio.sleep(0)
                        waiter.cancel()
                        with assert_raises(asyncio.CancelledError):
                            await waiter
                    async with owner.fetch_chunks(
                        namespace.raw("SELECT 1 AS value UNION ALL SELECT 2 AS value"),
                        size=1,
                    ) as stream:
                        await anext(stream)
                assert_eq(database.pool_stats().occupied, 0)
            assert_eq(database.pool_stats().state, "closed")
            assert_eq(database.pool_stats().occupied, 0)
        # Let queued asyncio transport closes run before measuring OS handles.
        await asyncio.sleep(0)
        await asyncio.sleep(0)

    await cycle()
    baseline = await asyncio.to_thread(_sample)
    print(json.dumps({"backend": backend, "cycle": 0, **baseline}), flush=True)
    for index in range(1, cycles + 1):
        await cycle()
        if index % 100 == 0 or index == cycles:
            sample = await asyncio.to_thread(_sample)
            print(
                json.dumps({"backend": backend, "cycle": index, **sample}), flush=True
            )
            assert_true(sample["descriptors"] <= baseline["descriptors"])
            assert_true(sample["threads"] <= baseline["threads"])


async def run_soak(backend: BackendFamily, cycles: int) -> None:
    """Measure closed database cycles against a warmed-up handle baseline."""
    async with AsyncExitStack() as resources:
        server = (
            await resources.enter_async_context(
                temporary_mariadb_server(transports={"tcp"})
            )
            if backend == "mariadb"
            else None
        )
        await _run_cycles(
            backend, cycles, server.config(pool_size=1) if server else None
        )


def main() -> None:
    """Reject invalid run bounds before opening any database or child process."""
    parser = ArgumentParser(description=__doc__)
    parser.add_argument("--backend", choices=("sqlite", "mariadb"), required=True)
    parser.add_argument("--cycles", type=int, default=10000)
    arguments = parser.parse_args()
    maximum_cycles = 100000
    if not 1 <= arguments.cycles <= maximum_cycles:
        parser.error("--cycles must be between 1 and 100000")
    if sys.platform != "linux":
        parser.error("resource accounting requires Linux /proc")
    backend: BackendFamily = "sqlite" if arguments.backend == "sqlite" else "mariadb"
    asyncio.run(run_soak(backend, arguments.cycles))


if __name__ == "__main__":
    main()

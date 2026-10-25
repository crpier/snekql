"""Opt-in Linux long-lived service soak; see soak/README.md and issue #538."""

import asyncio
import math
import sys
from argparse import ArgumentParser
from contextlib import AsyncExitStack
from dataclasses import asdict, dataclass
from pathlib import Path
from random import Random
from time import monotonic
from typing import Any

from anyio import TemporaryDirectory

from snekql import mariadb, sqlite
from snekql.testing.mariadb import temporary_mariadb_server
from soak._service_evidence import Histogram, emit, environment, resources
from soak._service_workload import Workload, require


@dataclass(frozen=True, kw_only=True)
class Config:
    """Bounded caller inputs; no existing database can be targeted."""

    backend: str
    duration: float = 300
    warmup: float = 5
    sample_interval: float = 5
    pool_size: int = 4
    workers: int = 8
    rows: int = 64
    batch_size: int = 16
    slow_consumer: float = 0.001
    burst_interval: float = 5
    seed: int = 538


async def _phase(  # noqa: C901
    work: Workload,
    config: Config,
    duration: float,
    *,
    latency: dict[str, Histogram] | None = None,
) -> dict[str, Histogram]:
    """Drain rather than cancel workers: no in-flight write is silently abandoned."""
    operations = ("read", "write", "stream", "early_stream")
    if latency is None:
        latency = {name: Histogram() for name in (*operations, "loop_delay")}
    deadline = monotonic() + duration
    done = asyncio.Event()
    worker_tasks: list[asyncio.Task[None]] = []

    async def worker(identity: int) -> None:
        random = Random(config.seed + identity)
        operation = 0
        # Each worker exercises every kind even in a short smoke-sized phase.
        while operation < len(operations) or monotonic() < deadline:
            name = operations[operation % len(operations)]
            started = monotonic()
            async with asyncio.timeout(60):
                if name == "read":
                    await work.read(random)
                elif name == "write":
                    await work.write(identity)
                else:
                    await work.stream(early=name == "early_stream")
            latency[name].record(monotonic() - started)
            operation += 1

    async def monitor() -> None:
        while not done.is_set():
            started = monotonic()
            await asyncio.sleep(0.01)
            latency["loop_delay"].record(max(0, monotonic() - started - 0.01))

    async def bursts() -> None:
        while not done.is_set():
            try:
                await asyncio.wait_for(done.wait(), timeout=config.burst_interval)
            except TimeoutError:
                async with asyncio.timeout(60):
                    await work.cancel_waiter(worker_tasks)

    async with asyncio.TaskGroup() as group:
        group.create_task(monitor())
        group.create_task(bursts())
        async with asyncio.TaskGroup() as workers:
            for identity in range(config.workers):
                worker_tasks.append(workers.create_task(worker(identity)))
        done.set()
    return latency


async def _sample(
    work: Workload, phase: str, started: float, latency: dict[str, Histogram]
) -> dict[str, int]:
    sample = await asyncio.to_thread(resources)
    emit(
        "sample",
        phase=phase,
        elapsed_seconds=monotonic() - started,
        resources=sample,
        pool=asdict(work.database.pool_stats()),
        completed={name: histogram.count for name, histogram in latency.items()},
    )
    return sample


async def _exercise(database: Any, config: Config, namespace: Any) -> dict[str, Any]:
    work = Workload(
        database,
        namespace,
        rows=config.rows,
        workers=config.workers,
        batch_size=config.batch_size,
        slow_consumer=config.slow_consumer,
        seed=config.seed,
    )
    async with asyncio.timeout(120):
        await work.prepare()
        await work.cancel_waiter()
        await _phase(work, config, config.warmup)
        await work.verify()
    started = monotonic()
    latency = {
        name: Histogram()
        for name in ("read", "write", "stream", "early_stream", "loop_delay")
    }
    baseline = await _sample(work, "baseline", started, latency)
    before = work.writes.copy()
    cancellations_before = work.cancelled_waiters
    async with asyncio.TaskGroup() as group:
        task = group.create_task(_phase(work, config, config.duration, latency=latency))
        while not task.done():
            done, _ = await asyncio.wait({task}, timeout=config.sample_interval)
            if not done:
                await _sample(work, "load", started, latency)
    elapsed = monotonic() - started
    drained = database.pool_stats()
    require(drained.occupied == 0 and drained.waiters == 0, "pool did not drain")
    async with asyncio.timeout(60):
        await work.verify()
        await work.read(Random(config.seed))
    final = await _sample(work, "drained", started, latency)
    require(
        final["descriptors"] <= baseline["descriptors"],
        "drained descriptors grew above warmed baseline",
    )
    require(
        final["threads"] <= baseline["threads"],
        "drained native threads grew above warmed baseline",
    )
    return {
        "elapsed_seconds": elapsed,
        "latency": {
            name: histogram.report() for name, histogram in task.result().items()
        },
        "operations_per_second": sum(
            histogram.count
            for name, histogram in task.result().items()
            if name != "loop_delay"
        )
        / elapsed,
        "writes_by_worker": work.writes,
        "measured_writes_by_worker": [
            after - prior for after, prior in zip(work.writes, before, strict=True)
        ],
        "verified_writes": sum(work.writes),
        "cancelled_waiters": work.cancelled_waiters,
        "measured_cancelled_waiters": work.cancelled_waiters - cancellations_before,
        "resource_checks_passed": True,
        "drained_pool": asdict(drained),
        "recovery_verified": True,
        "resource_delta": {
            name: final[name] - value for name, value in baseline.items()
        },
    }


async def run(config: Config) -> None:
    """Own all native resources and emit success only after verified shutdown."""
    await environment(asdict(config))
    async with AsyncExitStack() as owned:
        if config.backend == "mariadb":
            server = await owned.enter_async_context(
                temporary_mariadb_server(transports={"tcp"})
            )
            database: Any = await mariadb.Database.initialize(
                server.config(pool_size=config.pool_size)
            )
            namespace: Any = mariadb
        else:
            directory = await owned.enter_async_context(
                TemporaryDirectory(prefix="snekql-service-")
            )
            database = await sqlite.Database.initialize(
                sqlite.Config(
                    database=Path(directory) / "service.db", pool_size=config.pool_size
                )
            )
            namespace = sqlite
        async with database:
            async with database.transaction() as tx:
                version = await tx.fetch_one(
                    namespace.raw(
                        "SELECT VERSION() AS version"
                        if config.backend == "mariadb"
                        else "SELECT sqlite_version() AS version"
                    )
                )
            emit(
                "engine",
                backend=config.backend,
                version=version["version"],
                pool=asdict(database.pool_stats()),
            )
            report = await _exercise(database, config, namespace)
        closed = database.pool_stats()
        require(closed.state == "closed" and closed.occupied == 0, "pool did not close")
    emit("summary", status="passed", closed_pool=asdict(closed), **report)


def main() -> None:
    """Validate inputs before allocating a database, server or temporary directory."""
    parser = ArgumentParser(description=__doc__)
    parser.add_argument("--backend", required=True, choices=("sqlite", "mariadb"))
    for name, default in (
        ("duration", 300),
        ("warmup", 5),
        ("sample-interval", 5),
        ("slow-consumer", 0.001),
        ("burst-interval", 5),
    ):
        parser.add_argument(f"--{name}", type=float, default=default)
    for name, default in (
        ("pool-size", 4),
        ("workers", 8),
        ("rows", 64),
        ("batch-size", 16),
        ("seed", 538),
    ):
        parser.add_argument(f"--{name}", type=int, default=default)
    args = parser.parse_args()
    bounds = {
        "duration": (0.05, 86400),
        "warmup": (0.05, 300),
        "sample_interval": (0.01, 300),
        "slow_consumer": (0.0001, 0.05),
        "burst_interval": (0.05, 300),
        "pool_size": (1, 32),
        "workers": (2, 128),
        "rows": (16, 4096),
        "batch_size": (1, 1024),
        "seed": (0, 2**32 - 1),
    }
    for name, (lower, upper) in bounds.items():
        value = getattr(args, name)
        if not math.isfinite(value) or not lower <= value <= upper:
            parser.error(
                f"--{name.replace('_', '-')} must be between {lower} and {upper}"
            )
    if sys.platform != "linux":
        parser.error("resource accounting requires Linux /proc")
    try:
        asyncio.run(run(Config(**vars(args))))
    except Exception as error:
        emit("failure", status="failed", error_type=type(error).__name__)
        raise


if __name__ == "__main__":
    main()

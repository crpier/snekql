"""Validated runtime/capacity comparisons via `python -m benchmarks.compare`."""

import asyncio
import os
import sys
from argparse import ArgumentParser
from collections.abc import AsyncIterator, Callable
from contextlib import (
    AbstractAsyncContextManager,
    AsyncExitStack,
    asynccontextmanager,
    suppress,
)
from dataclasses import asdict
from datetime import UTC, datetime
from functools import partial
from gc import isenabled
from hashlib import sha256
from importlib.metadata import version
from json import dumps
from os import cpu_count
from pathlib import Path
from platform import machine, platform, processor
from sqlite3 import sqlite_version
from time import perf_counter

from anyio import TemporaryDirectory, run_process

from benchmarks import _comparison_mariadb, _comparison_sqlite
from benchmarks._artifacts import mariadb_artifacts
from benchmarks._comparison_contract import (
    ComparisonError,
    ReadSession,
    Record,
    StreamObservation,
)
from benchmarks._comparison_diagnostics import PoolDiagnostics, measure_memory
from benchmarks._metrics import LatencyRecorder
from benchmarks.comparison_plan import ComparisonPlan
from snekql.testing.mariadb import temporary_mariadb_server


async def _operation(
    session: ReadSession, target: int, run: ComparisonPlan
) -> StreamObservation:
    """Check completed work, including warmup, without retaining streamed rows."""
    if run.workload == "bulk":
        start = target * run.batch_size + 1
        records = await session.bulk(start, run.batch_size)
        expected = [
            Record(
                id=identity,
                email=f"user{identity}@example.com",
                payload="x" * run.payload_bytes,
            )
            for identity in range(start, start + run.batch_size)
        ]
        if records != expected:
            message = "bulk write did not return its committed records"
            raise ComparisonError(message)
        return StreamObservation(
            rows=len(records),
            identity_sum=sum(record.id for record in records),
            payload_bytes=sum(len(record.payload) for record in records),
        )
    if run.workload == "stream":
        observed = await session.stream(run.batch_size)
        if observed.rows != run.rows:
            message = "stream row count differs from the seeded dataset"
            raise ComparisonError(message)
        return observed
    records = await (
        session.join(target) if run.workload == "join" else session.read(target)
    )
    expected = Record(
        id=target,
        email=f"user{target}@example.com",
        payload=("j" if run.workload == "join" else "x") * run.payload_bytes,
    )
    if records != [expected]:
        message = "point read did not return its expected validated record"
        raise ComparisonError(message)
    return StreamObservation(
        rows=len(records),
        identity_sum=sum(record.id for record in records),
        payload_bytes=sum(len(record.payload) for record in records),
    )


@asynccontextmanager
async def _observe_loop() -> AsyncIterator[LatencyRecorder]:
    """Record completed 5 ms heartbeat wakeups only inside the measured window."""
    recorder = LatencyRecorder()

    async def sample() -> None:
        while True:
            deadline = perf_counter() + 0.005
            await asyncio.sleep(0.005)
            recorder.record(max(0.0, perf_counter() - deadline))

    task = asyncio.create_task(sample())
    try:
        # Arm the first heartbeat before the workload can block the loop.
        await asyncio.sleep(0)
        yield recorder
    finally:
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task


async def _measure(
    open_reader: Callable[
        [str, PoolDiagnostics], AbstractAsyncContextManager[ReadSession]
    ],
    *,
    adapter: str,
    run: ComparisonPlan,
) -> dict[str, object]:
    diagnostics = PoolDiagnostics(
        enabled=run.profile == "diagnostic", telemetry_enabled=run.telemetry == "on"
    )
    async with open_reader(adapter, diagnostics) as session:
        if session.prepared_sessions != run.pool_size:
            message = "comparison did not prepare every pool slot"
            raise ComparisonError(message)
        if run.workload == "bulk":
            await session.reset_bulk()
        for index in range(run.warmup):
            await _operation(
                session, index if run.workload == "bulk" else index % run.rows + 1, run
            )
        if run.workload == "bulk":
            await session.reset_bulk()
        latency = LatencyRecorder()
        totals = StreamObservation()
        per_worker_operations = [0] * run.workers

        async def worker(worker_index: int) -> None:
            for index in range(worker_index, run.operations, run.workers):
                target = index if run.workload == "bulk" else index % run.rows + 1
                operation_started = perf_counter()
                observed = await _operation(session, target, run)
                latency.record(perf_counter() - operation_started)
                totals.rows += observed.rows
                totals.payload_bytes += observed.payload_bytes
                totals.identity_sum += observed.identity_sum
                totals.batches += observed.batches
                totals.max_batch_rows = max(
                    totals.max_batch_rows, observed.max_batch_rows
                )
                per_worker_operations[worker_index] += 1

        async with (
            measure_memory(enabled=run.profile == "memory") as memory,
            _observe_loop() as stalls,
        ):
            diagnostics.active = True
            started = perf_counter()
            async with asyncio.TaskGroup() as tasks:
                for worker_index in range(run.workers):
                    tasks.create_task(worker(worker_index))
            elapsed = perf_counter() - started
            diagnostics.active = False
    return {
        "adapter": adapter,
        "prepared_sessions": session.prepared_sessions,
        "telemetry": diagnostics.telemetry_report(adapter),
        "session_policy": session.policy,
        "pool": diagnostics.report(adapter),
        "memory": memory,
        "per_worker_operations": per_worker_operations,
        "loop_stall": asdict(stalls.summary())
        if stalls.samples
        else {
            "count": 0,
            "mean_ms": None,
            "p50_ms": None,
            "p99_ms": None,
            "max_ms": None,
        },
        "elapsed_seconds": elapsed,
        "latency": asdict(latency.summary()),
        "observed": {
            "rows": totals.rows,
            "identity_sum": totals.identity_sum,
            "payload_bytes": totals.payload_bytes,
        },
        "stream": {"batches": totals.batches, "max_batch_rows": totals.max_batch_rows}
        if run.workload == "stream"
        else None,
        "throughput_ops_s": run.operations / elapsed,
    }


def _hardware() -> dict[str, object]:
    """Read available host facts; unsupported or inaccessible fields remain null."""
    details: dict[str, object] = {
        "cpu_model": processor() or None,
        "memory_total_bytes": None,
        "affinity": None,
        "cpu0_governor": None,
    }
    if sys.platform != "linux":
        return details
    details["affinity"] = sorted(os.sched_getaffinity(0))
    for path, prefix, key, numeric in (
        ("/proc/cpuinfo", "model name", "cpu_model", False),
        ("/proc/meminfo", "MemTotal", "memory_total_bytes", True),
    ):
        try:
            lines = Path(path).read_text().splitlines()
        except OSError:
            continue
        for line in lines:
            if line.startswith((prefix + ":", prefix + "\t")):
                text = line.split(":", 1)[1].strip()
                details[key] = int(text.split()[0]) * 1024 if numeric else text
                break
    with suppress(OSError):
        details["cpu0_governor"] = (
            Path("/sys/devices/system/cpu/cpu0/cpufreq/scaling_governor")
            .read_text()
            .strip()
        )
    return details


async def _environment() -> dict[str, object]:
    """Collect provenance outside the timed workload, never guess missing versions."""
    source = (await asyncio.to_thread(Path(__file__).resolve)).parent.parent
    lock = await asyncio.to_thread((source / "uv.lock").read_bytes)
    commit = await run_process(["git", "rev-parse", "HEAD"], cwd=source, check=False)
    status = await run_process(
        ["git", "status", "--porcelain"], cwd=source, check=False
    )
    loop_type = type(asyncio.get_running_loop())
    return {
        "hardware": await asyncio.to_thread(_hardware),
        "source_directory": str(source),
        "lock_sha256": sha256(lock).hexdigest(),
        "architecture": machine(),
        "cpu": await asyncio.to_thread(processor),
        "logical_cpus": cpu_count(),
        "os": await asyncio.to_thread(platform),
        "python": sys.version,
        "sqlite": sqlite_version,
        "loop": f"{loop_type.__module__}.{loop_type.__qualname__}",
        "gc_enabled": isenabled(),
        "commit": commit.stdout.decode().strip() if commit.returncode == 0 else None,
        "dirty": bool(status.stdout) if status.returncode == 0 else None,
        "packages": {
            package: await asyncio.to_thread(version, package)
            for package in (
                "snekql",
                "aiosqlite",
                "aiomysql",
                "sqlalchemy",
                "greenlet",
                "pydantic",
                "pydantic-core",
                "pymysql",
                "anyio",
            )
        },
    }


async def _run(run: ComparisonPlan) -> dict[str, object]:
    server_metadata: dict[str, object] | None = None
    async with AsyncExitStack() as resources:
        if run.backend == "sqlite":
            directory = await resources.enter_async_context(
                TemporaryDirectory(prefix="snekql-compare-")
            )
            path = Path(directory) / "comparison.db"
            await _comparison_sqlite.seed(
                path, run.rows, payload_bytes=run.payload_bytes
            )
            open_reader = partial(
                _comparison_sqlite.open_reader,
                path,
                pool_size=run.pool_size,
                payload_bytes=run.payload_bytes,
            )
        else:
            root = await resources.enter_async_context(mariadb_artifacts())
            server = await resources.enter_async_context(
                temporary_mariadb_server(
                    transports={"tcp"}, runtime_base_directory=root
                )
            )
            config = server.config(pool_size=run.pool_size)
            server_metadata = await _comparison_mariadb.seed(
                config, run.rows, payload_bytes=run.payload_bytes
            )
            open_reader = partial(
                _comparison_mariadb.open_reader, config, payload_bytes=run.payload_bytes
            )
        measurements = []
        for trial in run.schedule:
            measurement = await _measure(open_reader, adapter=trial.adapter, run=run)
            measurement["round"] = trial.round
            measurement["position"] = trial.position
            measurements.append(measurement)
    return {
        "backend": run.backend,
        "configuration": run.configuration,
        "environment": {**await _environment(), "mariadb": server_metadata},
        "measurement": run.measurement,
        "recorded_at": datetime.now(UTC).isoformat(),
        "schema_version": 2,
        "trials": measurements,
        "workload": run.workload,
    }


def main() -> None:
    """Emit a JSON report only after every requested transaction succeeds."""
    defaults = ComparisonPlan(backend="sqlite")
    parser = ArgumentParser(description=__doc__)
    parser.add_argument("--backend", choices=("sqlite", "mariadb"), required=True)
    parser.add_argument(
        "--adapter",
        choices=("all", "raw", "snekql", "sqlalchemy"),
        default=defaults.adapter,
    )
    parser.add_argument(
        "--workload",
        choices=("point-read", "stream", "join", "bulk"),
        default=defaults.workload,
    )
    parser.add_argument("--batch-size", type=int, default=defaults.batch_size)
    parser.add_argument(
        "--profile",
        choices=("timing", "diagnostic", "memory"),
        default=defaults.profile,
    )
    parser.add_argument(
        "--order", choices=("balanced", "forward", "reverse"), default=defaults.order
    )
    parser.add_argument(
        "--telemetry", choices=("off", "on"), default=defaults.telemetry
    )
    parser.add_argument("--payload-bytes", type=int, default=defaults.payload_bytes)
    parser.add_argument("--pool-size", type=int, default=defaults.pool_size)
    parser.add_argument("--workers", type=int, default=defaults.workers)
    parser.add_argument("--operations", type=int, default=defaults.operations)
    parser.add_argument("--rows", type=int, default=defaults.rows)
    parser.add_argument("--trials", type=int, default=defaults.trials)
    parser.add_argument("--warmup", type=int, default=defaults.warmup)
    arguments = parser.parse_args()
    try:
        plan = ComparisonPlan(**vars(arguments))
    except ValueError as error:
        parser.error(str(error))
    report = asyncio.run(_run(plan))
    print(dumps(report, allow_nan=False))


if __name__ == "__main__":
    main()

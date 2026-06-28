"""Concurrency benchmark harness.

``run_concurrent`` drives ``workers`` async tasks that repeatedly invoke a
single-operation coroutine against a live ``Database`` for ``duration`` seconds,
while a heartbeat task watches event-loop responsiveness. It reports throughput,
per-operation latency percentiles, a fairness index over per-worker completed
counts, and the worst observed event-loop stall.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass

import anyio

from benchmarks._metrics import (
    HeartbeatMonitor,
    LatencyRecorder,
    LatencySummary,
    fairness_jain,
)

WorkerOp = Callable[[int], Awaitable[None]]
"""One unit of work. Receives its worker index; performs one operation."""


@dataclass
class BenchmarkReport:
    """Outcome of one ``run_concurrent`` invocation."""

    label: str
    workers: int
    duration_s: float
    total_ops: int
    per_worker_ops: list[int]
    latency: LatencySummary
    fairness_index: float
    max_stall_ms: float
    p99_stall_ms: float

    @property
    def throughput_ops_s(self) -> float:
        return self.total_ops / self.duration_s if self.duration_s else 0.0


async def run_concurrent(
    label: str,
    op: WorkerOp,
    *,
    workers: int,
    duration: float,
    heartbeat_interval: float = 0.005,
) -> BenchmarkReport:
    """Run ``op`` from ``workers`` tasks for ``duration`` seconds."""

    latency = LatencyRecorder()
    per_worker_ops = [0] * workers
    monitor = HeartbeatMonitor(interval=heartbeat_interval)
    deadline = anyio.current_time() + duration

    async def worker(index: int) -> None:
        while anyio.current_time() < deadline:
            start = anyio.current_time()
            await op(index)
            latency.record(anyio.current_time() - start)
            per_worker_ops[index] += 1

    async with anyio.create_task_group() as task_group:
        task_group.start_soon(monitor.run)
        async with anyio.create_task_group() as workers_group:
            for index in range(workers):
                workers_group.start_soon(worker, index)
        monitor.stop()

    total_ops = sum(per_worker_ops)
    return BenchmarkReport(
        label=label,
        workers=workers,
        duration_s=duration,
        total_ops=total_ops,
        per_worker_ops=per_worker_ops,
        latency=latency.summary(),
        fairness_index=fairness_jain(per_worker_ops),
        max_stall_ms=monitor.max_stall_ms(),
        p99_stall_ms=monitor.p99_stall_ms(),
    )


def format_report(report: BenchmarkReport) -> str:
    """Render a single report as a compact multi-line block."""

    lat = report.latency
    counts = report.per_worker_ops
    spread = f"{min(counts)}..{max(counts)}" if counts else "n/a"
    load = f"workers={report.workers} duration={report.duration_s:.1f}s"
    latencies = f"p50={lat.p50_ms:.3f} p99={lat.p99_ms:.3f} max={lat.max_ms:.3f}"
    stalls = f"p99={report.p99_stall_ms:.3f}ms max={report.max_stall_ms:.3f}ms"
    lines = [
        f"[{report.label}]",
        f"  {load} ops={report.total_ops}",
        f"  throughput   {report.throughput_ops_s:.1f} ops/s",
        f"  latency ms   {latencies}",
        f"  fairness     jain={report.fairness_index:.4f} per-worker ops={spread}",
        f"  loop stall   {stalls}",
    ]
    return "\n".join(lines)

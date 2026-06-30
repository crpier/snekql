"""Query *construction* throughput and memory benchmark.

Separate from the concurrency harness (which drives live databases): this one
measures the pure-CPU cost of the immutable Query Builder -- turning
``select(...).where(...).limit(...)`` chains into query state -- with no I/O.
It reports a throughput distribution over repeated trials (so run-to-run
variance is visible) and per-query retained memory via ``tracemalloc``.

Run with ``uv run python -m benchmarks.construction``. Pin a single core and
disable turbo for the least noisy numbers; the harness already disables the GC
during each timed trial and reports the spread so residual noise is legible.
"""

from __future__ import annotations

import gc
import statistics
import time
import tracemalloc
from collections.abc import Callable
from dataclasses import dataclass

from snekql import sqlite
from snekql.sqlite import (
    Fetched,
    Integer,
    Model,
    Pending,
    Text,
    insert,
    select,
    update,
)


class BenchUser[S = Pending](Model[S, "BenchUser[Fetched]"]):
    """Narrow model exercising the common construction transitions."""

    __tablename__ = "bench_user"

    id: BenchUser.GenCol[int] = Integer(
        primary_key=True,
        auto_increment=True,
        default=sqlite.PENDING_GENERATION,
    )
    email: BenchUser.Col[str] = Text(nullable=False)
    name: BenchUser.Col[str] = Text(nullable=False)
    age: BenchUser.Col[int] = Integer(nullable=False)


def build_point_read() -> object:
    """select + single where + limit: the most common read shape."""

    return select(BenchUser).where(BenchUser.id.eq(42)).limit(1)


def build_filtered() -> object:
    """Multi-predicate filter with ordering and paging."""

    return (
        select(BenchUser)
        .where(BenchUser.age.gt(18))
        .where(BenchUser.name.eq("alice"))
        .order_by(BenchUser.id.desc())
        .limit(10)
        .offset(5)
    )


def build_projection() -> object:
    """Two-column projection select with a predicate."""

    return (
        select(BenchUser.email, BenchUser.name)
        .where(BenchUser.age.gte(21))
        .limit(
            100,
        )
    )


def build_insert() -> object:
    """Single-row insert from a freshly constructed pending model."""

    return insert(BenchUser(email="a@b.com", name="alice", age=30))


def build_update() -> object:
    """Update with one assignment and a primary-key predicate."""

    return update(BenchUser).set(BenchUser.name.to("bob")).where(BenchUser.id.eq(1))


WORKLOADS: dict[str, Callable[[], object]] = {
    "point_read": build_point_read,
    "filtered": build_filtered,
    "projection": build_projection,
    "insert": build_insert,
    "update": build_update,
}


@dataclass
class ThroughputResult:
    """Per-workload throughput distribution over repeated trials."""

    label: str
    ops_per_trial: int
    samples_ops_s: list[float]

    @property
    def median(self) -> float:
        return statistics.median(self.samples_ops_s)

    @property
    def mean(self) -> float:
        return statistics.fmean(self.samples_ops_s)

    @property
    def stdev(self) -> float:
        return (
            statistics.stdev(self.samples_ops_s) if len(self.samples_ops_s) > 1 else 0.0
        )

    @property
    def cv_pct(self) -> float:
        """Coefficient of variation: stdev as a percent of the mean."""

        return 100.0 * self.stdev / self.mean if self.mean else 0.0


def measure_throughput(
    label: str,
    op: Callable[[], object],
    *,
    ops_per_trial: int,
    trials: int,
    warmup: int,
) -> ThroughputResult:
    """Time ``op`` over ``trials`` independent runs of ``ops_per_trial`` builds.

    The GC is disabled inside each timed trial so a background collection cannot
    land in the middle of a sample and inflate one trial's time; it is restored
    between trials. ``perf_counter`` is the monotonic high-resolution clock.
    """

    for _ in range(warmup):
        _ = op()
    samples: list[float] = []
    for _ in range(trials):
        gc_was_enabled = gc.isenabled()
        gc.disable()
        try:
            start = time.perf_counter()
            for _ in range(ops_per_trial):
                _ = op()
            elapsed = time.perf_counter() - start
        finally:
            if gc_was_enabled:
                gc.enable()
        samples.append(ops_per_trial / elapsed)
    return ThroughputResult(label, ops_per_trial, samples)


def measure_memory(op: Callable[[], object], *, count: int) -> float:
    """Return mean retained bytes per built query via ``tracemalloc``.

    Holds every built query alive in a list so the snapshot diff reflects the
    retained state size, not transient allocations the allocator already reused.
    """

    _ = gc.collect()
    tracemalloc.start()
    before = tracemalloc.take_snapshot()
    retained = [op() for _ in range(count)]
    after = tracemalloc.take_snapshot()
    stats = after.compare_to(before, "filename")
    total = sum(stat.size_diff for stat in stats)
    tracemalloc.stop()
    # Reference ``retained`` after the diff so the built queries stay alive
    # across both snapshots (the diff must see retained, not freed, state).
    held = len(retained)
    return total / held


def main() -> None:
    ops_per_trial = 50_000
    trials = 15
    warmup = 5_000
    summary = f"construction benchmark: {trials} trials x {ops_per_trial} builds (warmup {warmup})"
    print(summary)
    print()
    header = f"{'workload':<12} {'median ops/s':>14} {'mean ops/s':>14} {'cv%':>7} {'bytes/query':>12}"
    print(header)
    print("-" * len(header))
    for label, op in WORKLOADS.items():
        result = measure_throughput(
            label,
            op,
            ops_per_trial=ops_per_trial,
            trials=trials,
            warmup=warmup,
        )
        bytes_per_query = measure_memory(op, count=20_000)
        row = f"{label:<12} {result.median:>14,.0f} {result.mean:>14,.0f} {result.cv_pct:>6.2f}% {bytes_per_query:>12,.1f}"
        print(row)


if __name__ == "__main__":
    main()

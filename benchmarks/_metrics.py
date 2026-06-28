"""Timing primitives used by the concurrency benchmarks.

Two things are measured:

* per-operation latency distributions (``LatencyRecorder``), and
* event-loop responsiveness (``HeartbeatMonitor``).

The heartbeat monitor is the direct probe for "does this code path stall the
event loop": a background task tries to wake every ``interval`` seconds and we
record how late each wake actually was. A CPU-bound stretch on the loop (for
example materializing a huge result set) shows up as a large maximum lateness.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import anyio


def _percentile(sorted_samples: list[float], fraction: float) -> float:
    """Return the ``fraction`` percentile of an already-sorted sample list."""

    if not sorted_samples:
        return math.nan
    if fraction <= 0:
        return sorted_samples[0]
    if fraction >= 1:
        return sorted_samples[-1]
    position = fraction * (len(sorted_samples) - 1)
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return sorted_samples[lower]
    weight = position - lower
    return sorted_samples[lower] * (1 - weight) + sorted_samples[upper] * weight


@dataclass
class LatencySummary:
    """Aggregate latency statistics in milliseconds."""

    count: int
    mean_ms: float
    p50_ms: float
    p99_ms: float
    max_ms: float


@dataclass
class LatencyRecorder:
    """Collect raw latency samples (seconds) and summarize them."""

    samples: list[float] = field(default_factory=list[float])

    def record(self, seconds: float) -> None:
        self.samples.append(seconds)

    def summary(self) -> LatencySummary:
        if not self.samples:
            return LatencySummary(0, math.nan, math.nan, math.nan, math.nan)
        ordered = sorted(self.samples)
        mean = sum(ordered) / len(ordered)
        return LatencySummary(
            count=len(ordered),
            mean_ms=mean * 1000,
            p50_ms=_percentile(ordered, 0.50) * 1000,
            p99_ms=_percentile(ordered, 0.99) * 1000,
            max_ms=_percentile(ordered, 1.0) * 1000,
        )


@dataclass
class HeartbeatMonitor:
    """Background probe that records event-loop wake-up lateness."""

    interval: float = 0.005
    lateness: list[float] = field(default_factory=list[float])
    _running: bool = False

    async def run(self) -> None:
        """Loop until ``stop`` is called, recording wake lateness each tick."""

        self._running = True
        while self._running:
            start = anyio.current_time()
            await anyio.sleep(self.interval)
            elapsed = anyio.current_time() - start
            self.lateness.append(max(0.0, elapsed - self.interval))

    def stop(self) -> None:
        self._running = False

    def max_stall_ms(self) -> float:
        if not self.lateness:
            return math.nan
        return max(self.lateness) * 1000

    def p99_stall_ms(self) -> float:
        if not self.lateness:
            return math.nan
        return _percentile(sorted(self.lateness), 0.99) * 1000


def fairness_jain(counts: list[int]) -> float:
    """Return Jain's fairness index for per-worker completed-op counts.

    1.0 means every worker completed the same number of operations; the value
    falls toward ``1/len(counts)`` as one worker monopolizes the pool. This is
    the headline "is the pool fair" number.
    """

    if not counts:
        return math.nan
    total = sum(counts)
    if total == 0:
        return math.nan
    sum_squares = sum(value * value for value in counts)
    return (total * total) / (len(counts) * sum_squares)

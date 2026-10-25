"""Bounded timing aggregation and Linux process samples for the service soak."""

import gc
import json
import math
import os
import platform
import sys
from dataclasses import dataclass, field
from importlib.metadata import distributions
from pathlib import Path
from threading import active_count
from typing import Any

from anyio import run_process

# Fixed logarithmic histogram: no per-operation list grows with run duration.
# Upper bucket bounds in milliseconds: 1us through ~1000s, then overflow.
BOUNDS_MS: tuple[float, ...] = tuple(
    0.001 * math.exp2(index / 4) for index in range(121)
)


@dataclass
class Histogram:
    """Exact counts/mean/max, approximate upper-bound histogram percentiles."""

    buckets: list[int] = field(default_factory=lambda: [0] * (len(BOUNDS_MS) + 1))
    count: int = 0
    total_ms: float = 0
    max_ms: float = 0

    def record(self, seconds: float) -> None:
        milliseconds = seconds * 1000
        index = next(
            (i for i, bound in enumerate(BOUNDS_MS) if milliseconds <= bound),
            len(BOUNDS_MS),
        )
        self.buckets[index] += 1
        self.count += 1
        self.total_ms += milliseconds
        self.max_ms = max(self.max_ms, milliseconds)

    def percentile(self, fraction: float) -> float | None:
        """Overflow percentiles use the observed maximum, never JSON infinity."""
        if not self.count:
            return None
        target = math.ceil(self.count * fraction)
        accumulated = 0
        for bound, count in zip((*BOUNDS_MS, self.max_ms), self.buckets, strict=True):
            accumulated += count
            if accumulated >= target:
                return bound
        return self.max_ms

    def report(self) -> dict[str, Any]:
        """Raw fixed buckets permit later aggregation without retaining timings."""
        return {
            "count": self.count,
            "mean_ms": self.total_ms / self.count if self.count else None,
            "max_ms": self.max_ms if self.count else None,
            "p50_upper_ms": self.percentile(0.5),
            "p95_upper_ms": self.percentile(0.95),
            "p99_upper_ms": self.percentile(0.99),
            "buckets": self.buckets,
        }


def resources() -> dict[str, int]:
    """Sample in a worker; GC is explicit and can itself perturb measurements."""
    gc.collect()
    status = dict(
        line.split(":", 1)
        for line in Path("/proc/self/status").read_text().splitlines()
    )
    return {
        "rss_kib": int(status["VmRSS"].split()[0]),
        "peak_rss_kib": int(status["VmHWM"].split()[0]),
        "descriptors": len(list(Path("/proc/self/fd").iterdir())),
        "threads": len(list(Path("/proc/self/task").iterdir())),
        "python_threads": active_count(),
    }


def emit(kind: str, **fields: Any) -> None:
    """One flushed, finite JSON object per line; partial runs lack passed summary."""
    print(
        json.dumps({"schema_version": 1, "kind": kind, **fields}, allow_nan=False),
        flush=True,
    )


async def environment(config: dict[str, Any]) -> None:
    """Capture source identity and environment without endpoints or credentials."""
    root = Path(__file__).parent.parent
    revision = await run_process(["git", "rev-parse", "HEAD"], cwd=root)
    status = await run_process(["git", "status", "--porcelain"], cwd=root)
    emit(
        "environment",
        revision=revision.stdout.decode().strip(),
        dirty=bool(status.stdout.strip()),
        python=sys.version,
        os=platform.platform(),
        architecture=platform.machine(),
        pid=os.getpid(),
        config=config,
        dependencies={item.metadata["Name"]: item.version for item in distributions()},
        latency_bucket_upper_ms=BOUNDS_MS,
    )

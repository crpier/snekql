"""Optional acquisition diagnostics, kept separate from primary timing runs."""

import asyncio
import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import asdict, dataclass, field
from gc import collect
from pathlib import Path
from tracemalloc import get_traced_memory, is_tracing, start, stop

from benchmarks._comparison_contract import ComparisonError
from benchmarks._metrics import LatencyRecorder
from snekql.telemetry import TelemetryEvent


@dataclass(kw_only=True)
class PoolDiagnostics:
    """Accept only samples inside the timed window; disabled runs install no observer."""

    enabled: bool
    active: bool = False
    samples: LatencyRecorder = field(default_factory=LatencyRecorder)

    def observe(self, event: TelemetryEvent) -> None:
        """Use public snekql admission events, not whole transaction-entry latency."""
        if (
            self.active
            and event.kind == "pool_wait"
            and event.phase == "finish"
            and event.duration_seconds is not None
        ):
            self.samples.record(event.duration_seconds)

    def report(self, adapter: str) -> dict[str, object] | None:
        """Core connect duration includes checkout work and is not pure queue wait."""
        if not self.enabled:
            return None
        return {
            "metric": "checkout" if adapter == "sqlalchemy" else "admission_wait",
            "source": {
                "raw": "asyncio-lock",
                "snekql": "public-pool-wait-event",
                "sqlalchemy": "async-engine-connect",
            }[adapter],
            "summary": asdict(self.samples.summary()) if self.samples.samples else None,
        }


def _resident_bytes() -> int | None:
    """Linux resident snapshots are not a process-lifetime high-water mark."""
    if sys.platform != "linux":
        return None
    for line in Path("/proc/self/status").read_text().splitlines():
        if line.startswith("VmRSS:"):
            return int(line.split()[1]) * 1024
    return None


@asynccontextmanager
async def measure_memory(*, enabled: bool) -> AsyncIterator[dict[str, object] | None]:
    """Trace only warmed workload allocations, never contaminate primary timing runs."""
    if not enabled:
        yield None
        return
    if is_tracing():
        message = "memory comparison requires an interpreter without pre-existing tracemalloc instrumentation"
        raise ComparisonError(message)
    await asyncio.to_thread(collect)
    before = await asyncio.to_thread(_resident_bytes)
    report: dict[str, object] = {"rss_before_bytes": before}
    start()
    try:
        yield report
    finally:
        current, peak = get_traced_memory()
        stop()
    report.update(
        {
            "python_traced_current_bytes": current,
            "python_traced_peak_bytes": peak,
            "rss_after_bytes": await asyncio.to_thread(_resident_bytes),
        }
    )

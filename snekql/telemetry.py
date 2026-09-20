"""Immutable, parameter-free observations of database runtime activity."""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal

type _EventKind = Literal[
    "pool_wait", "pool_checkout", "driver", "materialization", "transaction", "stream"
]


@dataclass(frozen=True, slots=True, kw_only=True)
class PoolStats:
    """Point-in-time pool capacity, including slots reserved for setup or cleanup.

    `occupied` counts admission slots, not just application-held connections.
    `waiters` counts queued acquirers. Read snapshots on the database's event loop;
    they neither acquire a connection nor reserve capacity for subsequent work.
    """

    acquisition_cancellations: int
    acquisition_failures: int
    capacity: int
    discarded_connections: int
    observer_failures: int
    occupied: int
    state: Literal["open", "closing", "closed"]
    waiters: int


@dataclass(frozen=True, slots=True, kw_only=True)
class TelemetryEvent:
    """One start or finish observation, without SQL, values, or exception objects.

    Operation IDs pair events across Databases in one process, never metric labels.
    Durations use a monotonic clock. `occurred_at_ns` is Unix time for tracing.
    """

    backend: Literal["sqlite", "mariadb"]
    duration_seconds: float | None
    fingerprint: str | None = None
    kind: _EventKind
    occurred_at_ns: int
    operation_id: int
    outcome: Literal["success", "error", "cancelled"] | None
    phase: Literal["start", "finish"]


type Observer = Callable[[TelemetryEvent], None]


__all__ = ["Observer", "PoolStats", "TelemetryEvent"]

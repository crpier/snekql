"""Pure source-checkout planning for validated comparative benchmarks."""

from dataclasses import dataclass

from benchmarks._comparison_policy import POLICY


@dataclass(frozen=True)
class TrialPlan:
    """One adapter's one-based round and run position."""

    round: int
    position: int
    adapter: str


@dataclass(frozen=True, kw_only=True)
class ComparisonPlan:
    """Describe requested work; construction rejects unsafe sizes before setup."""

    backend: str
    adapter: str = "all"
    batch_size: int = 256
    operations: int = 1000
    order: str = "balanced"
    pool_size: int = 1
    payload_bytes: int = 32
    profile: str = "timing"
    rows: int = 1000
    trials: int = 3
    telemetry: str = "off"
    warmup: int = 100
    workload: str = "point-read"
    workers: int = 1

    def __post_init__(self) -> None:
        for name, choices in (
            ("backend", ("sqlite", "mariadb")),
            ("adapter", ("all", "raw", "snekql", "sqlalchemy")),
            ("workload", ("point-read", "stream", "join", "bulk")),
            ("profile", ("timing", "diagnostic", "memory")),
            ("order", ("balanced", "forward", "reverse")),
            ("telemetry", ("off", "on")),
        ):
            if getattr(self, name) not in choices:
                message = f"unsupported {name}: {getattr(self, name)!r}"
                raise ValueError(message)
        for name, lower, upper in (
            ("workers", 1, 128),
            ("pool_size", 1, 32),
            ("payload_bytes", 1, 8192),
            ("batch_size", 1, 10000),
            ("operations", 1, 100000),
            ("rows", 1, 1000000),
            ("trials", 1, 30),
            ("warmup", 0, 10000),
        ):
            value = getattr(self, name)
            if type(value) is not int or not lower <= value <= upper:
                message = (
                    f"--{name.replace('_', '-')} must be between {lower} and {upper}"
                )
                raise ValueError(message)
        if self.rows * self.payload_bytes > 64 * 1024**2:
            message = "seed payload budget must not exceed 64 MiB across one table"
            raise ValueError(message)
        if (
            self.workload == "bulk"
            and self.batch_size * self.payload_bytes > 8 * 1024**2
        ):
            message = "INSERT payload budget must not exceed 8 MiB"
            raise ValueError(message)
        if self.workload == "bulk":
            write_rows = max(self.operations, self.warmup) * self.batch_size
            if write_rows * (self.payload_bytes + 64) > 128 * 1024**2:
                message = "write payload budget including row allowance must not exceed 128 MiB"
                raise ValueError(message)

    @property
    def schedule(self) -> tuple[TrialPlan, ...]:
        """Rotate positions and reverse each second balanced cycle."""
        adapters = (
            ["raw", "snekql", "sqlalchemy"] if self.adapter == "all" else [self.adapter]
        )
        scheduled = []
        for trial in range(self.trials):
            reverse = self.order == "reverse" or (
                self.order == "balanced" and (trial // len(adapters)) % 2 == 1
            )
            ordered = list(reversed(adapters)) if reverse else adapters
            offset = trial % len(adapters)
            scheduled.extend(
                TrialPlan(trial + 1, position, adapter)
                for position, adapter in enumerate(
                    ordered[offset:] + ordered[:offset], 1
                )
            )
        return tuple(scheduled)

    @property
    def configuration(self) -> dict[str, object]:
        """A fresh view of effective settings; contains no observed measurements."""
        return {
            "operations": self.operations,
            "adapter_order": self.order,
            "rows": self.rows,
            "trials": self.trials,
            "warmup": self.warmup,
            "workers": self.workers,
            "pool_size": self.pool_size,
            "payload_bytes": self.payload_bytes,
            "telemetry": self.telemetry,
            "buffering": "fetch-many" if self.workload == "stream" else "fetch-all",
            **(
                {"batch_size": self.batch_size}
                if self.workload in {"stream", "bulk"}
                else {}
            ),
            "validation": "strict-pydantic",
            "transaction": "explicit-begin-commit",
            "query_construction": "per-operation",
            self.backend: {
                "journal_mode": "WAL",
                "synchronous": "NORMAL",
                "foreign_keys": True,
                "busy_timeout_ms": 5000,
            }
            if self.backend == "sqlite"
            else dict(POLICY),
        }

    @property
    def measurement(self) -> dict[str, object]:
        """Declare timing scope without inventing latency or completion evidence."""
        return {
            "profile": self.profile,
            "heartbeat_interval_seconds": 0.005,
            "latency_includes_correctness_checks": True,
            "setup_included": False,
            "warmup_included": False,
        }

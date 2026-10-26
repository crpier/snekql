"""The optional soak command reports measured closed-cycle resources."""

import json
import os
import sys

from anyio import run_process
from snektest import Param, assert_eq, test


@test(mark="slow")
async def soak_command_reports_completed_cycles() -> None:
    """An explicit short run must emit a baseline and a final measurement."""
    result = await run_process(
        [
            sys.executable,
            "-m",
            "soak.lifecycle",
            "--backend",
            "sqlite",
            "--cycles",
            "2",
        ],
        check=False,
    )
    assert_eq(result.returncode, 0)
    samples = [json.loads(line) for line in result.stdout.splitlines()]
    assert_eq([sample["cycle"] for sample in samples], [0, 2])


@test(mark="slow")
async def service_soak_keeps_one_pool_and_verifies_mixed_work() -> None:
    """The short service workload drains and reconciles acknowledged writes."""
    result = await run_process(
        [
            sys.executable,
            "-m",
            "soak.service",
            "--backend",
            "sqlite",
            "--duration",
            "0.15",
            "--warmup",
            "0.1",
            "--sample-interval",
            "0.05",
            "--pool-size",
            "2",
            "--workers",
            "4",
        ],
        check=False,
    )
    assert_eq(result.returncode, 0, msg=result.stderr.decode())
    records = [json.loads(line) for line in result.stdout.splitlines()]
    assert_eq(records[0]["schema_version"], 1)
    assert_eq(records[0]["kind"], "environment")
    summary = records[-1]
    assert_eq(summary["kind"], "summary")
    assert_eq(summary["status"], "passed")
    assert_eq(summary["drained_pool"]["occupied"], 0)
    assert_eq(summary["drained_pool"]["waiters"], 0)
    assert_eq(summary["closed_pool"]["state"], "closed")
    assert_eq(summary["verified_writes"], sum(summary["writes_by_worker"]))
    for operation in ("read", "write", "stream", "early_stream"):
        assert_eq(summary["latency"][operation]["count"] > 0, True)
    assert_eq(summary["cancelled_waiters"] > 0, True)
    assert_eq(summary["recovery_verified"], True)
    samples = [record for record in records if record["kind"] == "sample"]
    assert_eq(len(samples) >= 2, True)
    assert_eq(samples[0]["phase"], "baseline")
    assert_eq(samples[-1]["phase"], "drained")
    assert_eq(samples[0]["resources"]["rss_kib"] > 0, True)
    assert_eq(samples[0]["completed"]["write"], 0)
    assert_eq(samples[-1]["completed"]["write"], summary["latency"]["write"]["count"])


@test(
    [Param(value="sqlite", name="sqlite"), Param(value="mariadb", name="mariadb")],
    [Param(value=1, name="one"), Param(value=3, name="three")],
    mark="slow",
)
async def service_soak_recovers_from_repeated_saturation(
    backend: str, capacity: int
) -> None:
    """Native pools recover under load; a partial final stream batch is verified."""
    result = await run_process(
        [
            sys.executable,
            "-m",
            "soak.service",
            "--backend",
            backend,
            "--duration",
            "0.3",
            "--warmup",
            "0.05",
            "--burst-interval",
            "0.05",
            "--sample-interval",
            "0.05",
            "--pool-size",
            str(capacity),
            "--workers",
            "4",
            "--rows",
            "17",
            "--batch-size",
            "8",
            "--seed",
            "42",
        ],
        check=False,
    )
    assert_eq(result.returncode, 0, msg=result.stderr.decode())
    records = [json.loads(line) for line in result.stdout.splitlines()]
    engine = records[1]
    summary = records[-1]
    assert_eq(engine["backend"], backend)
    assert_eq(engine["pool"]["capacity"], capacity)
    assert_eq(summary["measured_cancelled_waiters"] >= 1, True)
    assert_eq(summary["verified_writes"] > 0, True)
    assert_eq(
        sum(summary["measured_writes_by_worker"]), summary["latency"]["write"]["count"]
    )
    assert_eq(summary["drained_pool"]["acquisition_failures"], 0)
    assert_eq(summary["drained_pool"]["discarded_connections"], 0)
    assert_eq(summary["recovery_verified"], True)
    for metrics in summary["latency"].values():
        assert_eq(sum(metrics["buckets"]), metrics["count"])
        assert_eq(
            len(metrics["buckets"]), len(records[0]["latency_bucket_upper_ms"]) + 1
        )
    assert_eq(summary["resource_checks_passed"], True)


@test(
    [
        Param(value=value, name=str(index))
        for index, value in enumerate(
            [
                ("--duration", "nan"),
                ("--duration", "inf"),
                ("--duration", "0"),
                ("--pool-size", "0"),
                ("--workers", "129"),
                ("--sample-interval", "0"),
                ("--seed", "-1"),
                ("--minimum-bursts", "-1"),
                ("--minimum-bursts", "1001"),
                ("--rows", "15"),
                ("--batch-size", "0"),
            ]
        )
    ],
    mark="slow",
)
async def service_soak_rejects_invalid_inputs(value: tuple[str, str]) -> None:
    """Invalid run bounds fail before any environment or database is allocated."""
    result = await run_process(
        [sys.executable, "-m", "soak.service", "--backend", "sqlite", *value],
        check=False,
    )
    assert_eq(result.returncode, 2)
    assert_eq(result.stdout, b"")
    assert_eq(b"must be between" in result.stderr, True)


@test(mark="slow")
async def service_soak_sustained_multislot_saturation_does_not_stall() -> None:
    """Complete five bursts under native contention, independent of host speed."""
    result = await run_process(
        [
            sys.executable,
            "-m",
            "soak.service",
            "--backend",
            "mariadb",
            "--duration",
            "2",
            "--minimum-bursts",
            "5",
            "--warmup",
            "0.1",
            "--burst-interval",
            "0.05",
            "--sample-interval",
            "0.1",
            "--pool-size",
            "3",
            "--workers",
            "8",
            "--rows",
            "17",
            "--batch-size",
            "8",
        ],
        check=False,
    )
    assert_eq(result.returncode, 0, msg=result.stderr.decode())
    summary = json.loads(result.stdout.splitlines()[-1])
    assert_eq(summary["measured_cancelled_waiters"] >= 5, True)
    assert_eq(summary["cancelled_waiters"] >= 2, True)
    assert_eq(summary["resource_checks_passed"], True)
    assert_eq(summary["recovery_verified"], True)
    assert_eq(summary["drained_pool"]["occupied"], 0)
    assert_eq(summary["drained_pool"]["waiters"], 0)
    assert_eq(summary["closed_pool"]["state"], "closed")
    assert_eq(summary["closed_pool"]["occupied"], 0)


@test(mark="slow")
async def service_soak_reports_failure_without_a_success_summary() -> None:
    """A missing evidence prerequisite is a failed run, never a passing subset."""

    result = await run_process(
        [sys.executable, "-m", "soak.service", "--backend", "sqlite"],
        env={**os.environ, "PATH": ""},
        check=False,
    )
    assert_eq(result.returncode != 0, True)
    records = [json.loads(line) for line in result.stdout.splitlines()]
    assert_eq([record["kind"] for record in records], ["failure"])
    assert_eq(records[0]["status"], "failed")

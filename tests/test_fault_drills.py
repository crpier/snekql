"""Real fault drills are observed through their source-checkout CLI evidence."""

import json
import sys

from anyio import fail_after, run_process
from snektest import Param, assert_eq, test


@test(mark="slow")
async def stream_transport_cut_is_terminal_and_fresh_work_recovers() -> None:
    """A real cut after a delivered batch cannot become a successful/replayed stream."""
    with fail_after(120):
        result = await run_process(
            [sys.executable, "-m", "soak.faults", "--scenario", "stream-cut"],
            check=False,
        )
    assert_eq(result.returncode, 0, msg=result.stderr.decode())
    records = [json.loads(line) for line in result.stdout.splitlines()]
    assert_eq(records[0]["kind"], "environment")
    fault = next(record for record in records if record["kind"] == "fault")
    assert_eq(fault["first_batch_ids"], [1, 2, 3, 4])
    assert_eq(fault["transport_cut"], True)
    assert_eq(fault["server_bytes_forwarded"] < 4096 * 4096, True)
    summary = records[-1]
    assert_eq(summary["kind"], "summary")
    assert_eq(summary["status"], "passed")
    assert_eq(summary["failure_category"], "connection_loss")
    assert_eq(summary["terminal_transaction"], True)
    assert_eq(4 <= summary["delivered_rows"] < 4096, True)
    assert_eq(summary["drained_pool"]["occupied"], 0)
    assert_eq(summary["drained_pool"]["waiters"], 0)
    assert_eq(summary["drained_pool"]["discarded_connections"], 1)
    assert_eq(summary["recovery_verified"], True)
    assert_eq(summary["closed_pool"]["state"], "closed")


@test(mark="slow")
async def real_commit_reply_blackhole_requires_reconciliation_not_replay() -> None:
    """The server's held OK is not an application acknowledgement of its durable write."""
    with fail_after(120):
        result = await run_process(
            [sys.executable, "-m", "soak.faults", "--scenario", "commit-blackhole"],
            check=False,
        )
    assert_eq(result.returncode, 0, msg=result.stderr.decode())
    records = [json.loads(line) for line in result.stdout.splitlines()]
    fault = next(record for record in records if record["kind"] == "fault")
    assert_eq(fault["commit_requests_forwarded"], 1)
    assert_eq(fault["reply_held"], True)
    assert_eq(fault["server_reply"], "ok")
    summary = records[-1]
    assert_eq(summary["kind"], "summary")
    assert_eq(summary["status"], "passed")
    assert_eq(summary["error_type"], "DatabaseOperationTimeoutError")
    assert_eq(summary["commit_outcome"], "unknown")
    assert_eq(summary["reconciled_rows"], [{"operation_id": 544, "value": 7}])
    assert_eq(summary["commit_requests_forwarded"], 1)
    assert_eq(summary["drained_pool"]["discarded_connections"], 1)
    assert_eq(summary["drained_pool"]["occupied"], 0)
    assert_eq(summary["recovery_verified"], True)
    assert_eq(summary["closed_pool"]["state"], "closed")


@test(mark="slow")
async def owned_server_restart_interrupts_active_and_queued_load_without_replay() -> (
    None
):
    """A real restart preserves acknowledged records and lets the same pool serve new work."""
    with fail_after(180):
        result = await run_process(
            [sys.executable, "-m", "soak.faults", "--scenario", "restart-load"],
            check=False,
        )
    assert_eq(result.returncode, 0, msg=result.stderr.decode())
    records = [json.loads(line) for line in result.stdout.splitlines()]
    fault = next(record for record in records if record["kind"] == "fault")
    assert_eq(fault["active_server_queries"], 4)
    assert_eq(fault["pool"]["occupied"], 4)
    assert_eq(fault["pool"]["waiters"], 4)
    summary = records[-1]
    assert_eq(summary["kind"], "summary")
    assert_eq(summary["status"], "passed")
    assert_eq(summary["active_failure_categories"], ["connection_loss"] * 4)
    assert_eq(len(summary["queued_errors"]), 4)
    assert_eq(summary["preserved_ids"], [1, 2, 3, 4])
    assert_eq(summary["recovered_ids"], [1, 2, 3, 4, 5])
    assert_eq(summary["drained_pool"]["occupied"], 0)
    assert_eq(summary["drained_pool"]["waiters"], 0)
    assert_eq(summary["recovery_verified"], True)
    assert_eq(summary["closed_pool"]["state"], "closed")


@test(mark="slow")
async def storage_cli_proves_real_enospc_recovery_or_explicit_isolation_rejection() -> (
    None
):
    """A storage pass requires actual ENOSPC, not a page-count limit or mocked driver."""
    with fail_after(60):
        result = await run_process(
            [sys.executable, "-m", "soak.faults", "--scenario", "sqlite-full"],
            check=False,
        )
    records = [json.loads(line) for line in result.stdout.splitlines()]
    # Normal CI may prohibit user namespaces. Verify honest failure rather than
    # silently counting an unexecuted storage drill as passed.
    if result.returncode != 0:
        failure = records[-1]
        assert_eq(failure["kind"], "failure", msg=result.stderr.decode())
        assert_eq(
            failure["error_type"],
            "NamespaceUnavailableError",
            msg=result.stderr.decode(),
        )
        assert_eq(any(r["kind"] == "summary" for r in records), False)
        return
    fault = next(record for record in records if record["kind"] == "fault")
    assert_eq(fault["os_errno"], 28)
    assert_eq(fault["mount_namespace_isolated"], True)
    assert_eq(fault["user_namespace_isolated"], True)
    assert_eq(fault["filesystem"], "tmpfs")
    assert_eq(0 < fault["filesystem_bytes"] <= 4 * 1024 * 1024, True)
    summary = records[-1]
    assert_eq(summary["kind"], "summary")
    assert_eq(summary["status"], "passed")
    assert_eq(summary["sqlite_errorcode"], 13)
    assert_eq(
        summary["commit_outcome"] in ("not_attempted", "rejected", "unknown"), True
    )
    assert_eq(summary["reconciled_ids"], [1])
    assert_eq(summary["recovered_ids"], [1, 3])
    assert_eq(summary["drained_pool"]["occupied"], 0)
    assert_eq(summary["recovery_verified"], True)
    assert_eq(summary["closed_pool"]["state"], "closed")


@test(
    [
        Param(("stream-cut", "mariadb", 1, 5), name="stream"),
        Param(("commit-blackhole", "mariadb", 1, 1), name="commit"),
        Param(("restart-load", "mariadb", 4, 10), name="restart"),
        Param(("sqlite-full", "sqlite", 1, 5), name="storage"),
    ],
    mark="slow",
)
async def drill_records_engine_and_effective_operation_configuration(
    case: tuple[str, str, int, int],
) -> None:
    """Reproduction evidence identifies the actual engine and deadline, not just the label."""
    scenario, backend, capacity, timeout = case
    result = await run_process(
        [sys.executable, "-m", "soak.faults", "--scenario", scenario],
        check=False,
    )
    records = [json.loads(line) for line in result.stdout.splitlines()]
    if scenario == "sqlite-full" and result.returncode != 0:
        assert_eq(
            records[-1]["error_type"],
            "NamespaceUnavailableError",
            msg=result.stderr.decode(),
        )
        return
    assert_eq(result.returncode, 0, msg=result.stderr.decode())
    engine = next(record for record in records if record["kind"] == "engine")
    assert_eq(engine["backend"], backend)
    assert_eq(isinstance(engine["version"], str), True)
    assert_eq(engine["pool_size"], capacity)
    assert_eq(engine["transaction_timeout"], timeout)

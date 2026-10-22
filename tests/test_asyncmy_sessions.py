"""Observe session policy via public transactions against an owned MariaDB."""

from json import loads

from anyio import run_process
from snektest import assert_eq, test


@test(mark="slow")
async def startup_reuse_and_replacement_have_required_session_settings() -> None:
    result = await run_process(
        [
            "uv",
            "run",
            "--locked",
            "--with",
            "asyncmy==0.2.16",
            "python",
            "-m",
            "benchmarks.asyncmy_prototype",
            "--scenario",
            "session-settings",
        ],
        check=False,
    )
    assert_eq(result.returncode, 0, msg=result.stderr.decode())
    report = loads(result.stdout)
    assert_eq([r["driver"] for r in report["results"]], ["aiomysql", "asyncmy"])
    for observed in report["results"]:
        assert_eq(observed["reused"], True)
        assert_eq(observed["replaced"], True)
        assert_eq(observed["extra_results_rejected"], True)
        for state in observed["sessions"]:
            assert_eq(state["time_zone"], "+00:00")
            assert_eq(state["foreign_key_checks"], 1)
            assert_eq(state["check_constraint_checks"], 1)
            assert_eq(state["unique_checks"], 1)
            assert_eq(state["autocommit"], 0)
            assert_eq(state["character_set_connection"], "utf8mb4")
            assert_eq(
                {"STRICT_ALL_TABLES", "NO_ENGINE_SUBSTITUTION"}
                <= set(state["sql_mode"].split(",")),
                True,
            )
        assert_eq(
            (
                observed["occupied"],
                observed["waiters"],
                observed["discarded_connections"],
            ),
            (0, 0, 1),
        )
        assert_eq(observed["pool_state_after_close"], "closed")
        assert_eq(observed["warnings"], [])


@test(mark="slow")
async def session_mutations_have_matching_checkout_semantics() -> None:
    result = await run_process(
        [
            "uv",
            "run",
            "--locked",
            "--with",
            "asyncmy==0.2.16",
            "python",
            "-m",
            "benchmarks.asyncmy_prototype",
            "--scenario",
            "session-mutations",
        ],
        check=False,
    )
    assert_eq(result.returncode, 0, msg=result.stderr.decode())
    report = loads(result.stdout)
    assert_eq([r["driver"] for r in report["results"]], ["aiomysql", "asyncmy"])
    for observed in report["results"]:
        assert_eq(observed["within_lease"]["time_zone"], "+05:30")
        assert_eq(observed["within_lease"]["marker"], 42)
        assert_eq(observed["next_lease"]["time_zone"], "+05:30")
        assert_eq(observed["next_lease"]["marker"], 42)
        assert_eq(observed["replacement"]["time_zone"], "+00:00")
        assert_eq(observed["replacement"]["marker"], None)
        assert_eq(
            (
                observed["reused"],
                observed["replaced"],
                observed["extra_results_rejected"],
            ),
            (True, True, True),
        )
        assert_eq(observed["warnings"], [])


@test(mark="slow")
async def timed_out_shutdown_blocks_new_work_and_can_be_retried() -> None:
    result = await run_process(
        [
            "uv",
            "run",
            "--locked",
            "--with",
            "asyncmy==0.2.16",
            "python",
            "-m",
            "benchmarks.asyncmy_prototype",
            "--scenario",
            "shutdown-timeout",
        ],
        check=False,
    )
    assert_eq(result.returncode, 0, msg=result.stderr.decode())
    report = loads(result.stdout)
    assert_eq([r["driver"] for r in report["results"]], ["aiomysql", "asyncmy"])
    for observed in report["results"]:
        assert_eq(
            (
                observed["close_error"],
                observed["new_work_error"],
                observed["state_after_failure"],
                observed["occupied_after_failure"],
                observed["active_answer"],
                observed["commit_outcome"],
                observed["final_state"],
                observed["occupied"],
                observed["waiters"],
                observed["closed_work_error"],
            ),
            (
                "DatabaseCloseTimeoutError",
                "DatabaseClosingError",
                "closing",
                1,
                42,
                "committed",
                "closed",
                0,
                0,
                "DatabaseClosedError",
            ),
        )
        assert_eq(observed["warnings"], [])


@test(mark="slow")
async def cancelled_close_caller_does_not_abandon_concurrent_shutdown() -> None:
    result = await run_process(
        [
            "uv",
            "run",
            "--locked",
            "--with",
            "asyncmy==0.2.16",
            "python",
            "-m",
            "benchmarks.asyncmy_prototype",
            "--scenario",
            "shutdown-cancel",
        ],
        check=False,
    )
    assert_eq(result.returncode, 0, msg=result.stderr.decode())
    report = loads(result.stdout)
    assert_eq([r["driver"] for r in report["results"]], ["aiomysql", "asyncmy"])
    for observed in report["results"]:
        assert_eq(
            (
                observed["cancel_error"],
                observed["concurrent_close_pending"],
                observed["new_work_error"],
                observed["active_answer"],
                observed["commit_outcome"],
                observed["final_state"],
                observed["occupied"],
                observed["waiters"],
            ),
            (
                "CancelledError",
                True,
                "DatabaseClosingError",
                42,
                "committed",
                "closed",
                0,
                0,
            ),
        )
        assert_eq(observed["warnings"], [])

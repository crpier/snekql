"""Cancellation/deadline behavior at the public prototype transaction seam."""

from json import loads

from anyio import run_process
from snektest import Param, assert_eq, test


@test(mark="slow")
async def cancelled_public_query_discards_connection_and_preserves_rollback() -> None:
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
            "cancel-query",
        ],
        check=False,
    )
    assert_eq(result.returncode, 0, msg=result.stderr.decode())
    report = loads(result.stdout)
    assert_eq([r["unsafe_work_blocked"] for r in report["results"]], [True, True])
    assert_eq(
        [
            (
                r["occupied"],
                r["waiters"],
                r["discarded_connections"],
                r["pool_state_after_close"],
            )
            for r in report["results"]
        ],
        [(0, 0, 1, "closed"), (0, 0, 1, "closed")],
    )
    assert_eq(
        [
            (
                r["driver"],
                r["error_type"],
                r["phase"],
                r["same_connection"],
                r["visible_writes"],
                r["recovered_writes"],
                r["commit_outcome"],
                r["recovery_outcome"],
            )
            for r in report["results"]
        ],
        [
            (
                "aiomysql",
                "CancelledError",
                "query",
                False,
                0,
                1,
                "not_attempted",
                "committed",
            ),
            (
                "asyncmy",
                "CancelledError",
                "query",
                False,
                0,
                1,
                "not_attempted",
                "committed",
            ),
        ],
    )


@test([Param("fetch", name="fetch"), Param("close", name="close")], mark="slow")
async def cancelled_public_stream_releases_its_connection(phase: str) -> None:
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
            f"cancel-{phase}",
        ],
        check=False,
    )
    assert_eq(result.returncode, 0, msg=result.stderr.decode())
    report = loads(result.stdout)
    assert_eq([r["unsafe_work_blocked"] for r in report["results"]], [True, True])
    assert_eq(
        [
            (
                r["driver"],
                r["error_type"],
                r["phase"],
                r["first_identity"],
                r["same_connection"],
                r["visible_writes"],
                r["recovered_writes"],
                r["commit_outcome"],
                r["recovery_outcome"],
                r["occupied"],
                r["waiters"],
                r["discarded_connections"],
                r["pool_state_after_close"],
            )
            for r in report["results"]
        ],
        [
            (
                "aiomysql",
                "CancelledError",
                phase,
                1,
                False,
                0,
                1,
                "not_attempted",
                "committed",
                0,
                0,
                1,
                "closed",
            ),
            (
                "asyncmy",
                "CancelledError",
                phase,
                1,
                False,
                0,
                1,
                "not_attempted",
                "committed",
                0,
                0,
                1,
                "closed",
            ),
        ],
    )


@test(mark="slow")
async def public_query_deadline_discards_connection_and_blocks_more_work() -> None:
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
            "deadline-query",
        ],
        check=False,
    )
    assert_eq(result.returncode, 0, msg=result.stderr.decode())
    report = loads(result.stdout)
    assert_eq([r["unsafe_work_blocked"] for r in report["results"]], [True, True])
    assert_eq(
        [
            (
                r["driver"],
                r["error_type"],
                r["phase"],
                r["unsafe_work_blocked"],
                r["same_connection"],
                r["visible_writes"],
                r["recovered_writes"],
                r["commit_outcome"],
                r["recovery_outcome"],
                r["occupied"],
                r["waiters"],
                r["discarded_connections"],
                r["pool_state_after_close"],
            )
            for r in report["results"]
        ],
        [
            (
                "aiomysql",
                "DatabaseOperationTimeoutError",
                "query",
                True,
                False,
                0,
                1,
                "not_attempted",
                "committed",
                0,
                0,
                1,
                "closed",
            ),
            (
                "asyncmy",
                "DatabaseOperationTimeoutError",
                "query",
                True,
                False,
                0,
                1,
                "not_attempted",
                "committed",
                0,
                0,
                1,
                "closed",
            ),
        ],
    )


@test([Param("fetch", name="fetch"), Param("close", name="close")], mark="slow")
async def public_stream_deadline_characterizes_completion_error_precedence(
    phase: str,
) -> None:
    expected_error = (
        "ExecutionError" if phase == "fetch" else "DatabaseOperationTimeoutError"
    )
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
            f"deadline-{phase}",
        ],
        check=False,
    )
    assert_eq(result.returncode, 0, msg=result.stderr.decode())
    report = loads(result.stdout)
    assert_eq(
        [r["timeout_evidence"] for r in report["results"]],
        ["context", "context"] if phase == "fetch" else ["direct", "direct"],
    )
    assert_eq(
        [
            (
                r["driver"],
                r["error_type"],
                r["phase"],
                r["first_identity"],
                r["unsafe_work_blocked"],
                r["same_connection"],
                r["visible_writes"],
                r["recovered_writes"],
                r["commit_outcome"],
                r["recovery_outcome"],
                r["occupied"],
                r["waiters"],
                r["discarded_connections"],
                r["pool_state_after_close"],
            )
            for r in report["results"]
        ],
        [
            (
                "aiomysql",
                expected_error,
                phase,
                1,
                True,
                False,
                0,
                1,
                "not_attempted",
                "committed",
                0,
                0,
                1,
                "closed",
            ),
            (
                "asyncmy",
                expected_error,
                phase,
                1,
                True,
                False,
                0,
                1,
                "not_attempted",
                "committed",
                0,
                0,
                1,
                "closed",
            ),
        ],
    )

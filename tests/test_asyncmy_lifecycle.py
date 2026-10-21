"""Real-driver lifecycle experiments run in an isolated dependency overlay."""

from json import loads

from anyio import run_process
from snektest import assert_eq, test


@test(mark="slow")
async def abandoned_stream_can_reuse_the_same_connection() -> None:
    result = await run_process(
        [
            "uv",
            "run",
            "--locked",
            "--with",
            "asyncmy==0.2.16",
            "python",
            "-m",
            "benchmarks.asyncmy_lifecycle",
            "--scenario",
            "abandoned-stream",
        ],
        check=False,
    )
    assert_eq((result.returncode, result.stderr.decode()), (0, ""))
    report = loads(result.stdout)
    assert_eq(
        [
            (r["driver"], r["first_identity"], r["same_connection"], r["answer"])
            for r in report["results"]
        ],
        [("aiomysql", 1, True, 42), ("asyncmy", 1, True, 42)],
    )


@test(mark="slow")
async def unread_result_sets_expose_asyncmy_protocol_failure() -> None:
    result = await run_process(
        [
            "uv",
            "run",
            "--locked",
            "--with",
            "asyncmy==0.2.16",
            "python",
            "-m",
            "benchmarks.asyncmy_lifecycle",
            "--scenario",
            "multiple-results",
        ],
        check=False,
    )
    assert_eq((result.returncode, result.stderr.decode()), (0, ""))
    report = loads(result.stdout)
    baseline, candidate = report["results"]
    assert_eq(
        (baseline["driver"], baseline["status"], baseline["same_connection"]),
        ("aiomysql", "reused", True),
    )
    assert_eq(
        (
            candidate["driver"],
            candidate["status"],
            candidate["phase"],
            candidate["error_type"],
        ),
        ("asyncmy", "driver-error", "reuse", "InternalError"),
    )
    assert_eq(candidate["error"].startswith("Packet sequence number wrong"), True)


@test(mark="slow")
async def abandoned_stream_can_return_to_a_single_connection_pool() -> None:
    result = await run_process(
        [
            "uv",
            "run",
            "--locked",
            "--with",
            "asyncmy==0.2.16",
            "python",
            "-m",
            "benchmarks.asyncmy_lifecycle",
            "--scenario",
            "pool-reuse",
        ],
        check=False,
    )
    assert_eq((result.returncode, result.stderr.decode()), (0, ""))
    report = loads(result.stdout)
    assert_eq(
        [
            (r["driver"], r["status"], r["same_connection"], r["answer"])
            for r in report["results"]
        ],
        [("aiomysql", "reused", True, 42), ("asyncmy", "reused", True, 42)],
    )


@test(mark="slow")
async def discarding_pending_results_gets_a_fresh_usable_pool_connection() -> None:
    result = await run_process(
        [
            "uv",
            "run",
            "--locked",
            "--with",
            "asyncmy==0.2.16",
            "python",
            "-m",
            "benchmarks.asyncmy_lifecycle",
            "--scenario",
            "pool-discard-multiple",
        ],
        check=False,
    )
    assert_eq((result.returncode, result.stderr.decode()), (0, ""))
    report = loads(result.stdout)
    assert_eq(
        [
            (r["driver"], r["status"], r["same_connection"], r["answer"], r["warnings"])
            for r in report["results"]
        ],
        [
            ("aiomysql", "replaced", False, 42, []),
            (
                "asyncmy",
                "replaced",
                False,
                42,
                ["coroutine 'MySQLResult._finish_unbuffered_query' was never awaited"],
            ),
        ],
    )


@test(mark="slow")
async def cancelled_query_discards_connection_and_rolls_back_pending_write() -> None:
    result = await run_process(
        [
            "uv",
            "run",
            "--locked",
            "--with",
            "asyncmy==0.2.16",
            "python",
            "-m",
            "benchmarks.asyncmy_lifecycle",
            "--scenario",
            "cancel-query",
        ],
        check=False,
    )
    assert_eq((result.returncode, result.stderr.decode()), (0, ""))
    report = loads(result.stdout)
    assert_eq(
        [
            (
                r["driver"],
                r["cancelled"],
                r["driver_closed"],
                r["same_connection"],
                r["visible_writes"],
                r["answer"],
            )
            for r in report["results"]
        ],
        [("aiomysql", True, True, False, 0, 42), ("asyncmy", True, True, False, 0, 42)],
    )


@test(mark="slow")
async def cancelled_stream_fetch_discards_connection_and_rolls_back_pending_write() -> (
    None
):
    result = await run_process(
        [
            "uv",
            "run",
            "--locked",
            "--with",
            "asyncmy==0.2.16",
            "python",
            "-m",
            "benchmarks.asyncmy_lifecycle",
            "--scenario",
            "cancel-fetch",
        ],
        check=False,
    )
    assert_eq((result.returncode, result.stderr.decode()), (0, ""))
    report = loads(result.stdout)
    assert_eq(
        [
            (
                r["driver"],
                r["first_identity"],
                r["cancelled"],
                r["driver_closed"],
                r["same_connection"],
                r["visible_writes"],
                r["recovered_writes"],
                r["answer"],
            )
            for r in report["results"]
        ],
        [
            ("aiomysql", 1, True, True, False, 0, 1, 42),
            ("asyncmy", 1, True, True, False, 0, 1, 42),
        ],
    )


@test(mark="slow")
async def cancelled_stream_cleanup_discards_connection_and_rolls_back_pending_write() -> (
    None
):
    result = await run_process(
        [
            "uv",
            "run",
            "--locked",
            "--with",
            "asyncmy==0.2.16",
            "python",
            "-m",
            "benchmarks.asyncmy_lifecycle",
            "--scenario",
            "cancel-close",
        ],
        check=False,
    )
    assert_eq((result.returncode, result.stderr.decode()), (0, ""))
    report = loads(result.stdout)
    assert_eq(
        [
            (
                r["driver"],
                r["first_identity"],
                r["cancelled"],
                r["driver_closed"],
                r["same_connection"],
                r["visible_writes"],
                r["recovered_writes"],
                r["answer"],
            )
            for r in report["results"]
        ],
        [
            ("aiomysql", 1, True, True, False, 0, 1, 42),
            ("asyncmy", 1, True, True, False, 0, 1, 42),
        ],
    )


@test(mark="slow")
async def lost_commit_acknowledgement_can_hide_a_committed_write() -> None:
    result = await run_process(
        [
            "uv",
            "run",
            "--locked",
            "--with",
            "asyncmy==0.2.16",
            "python",
            "-m",
            "benchmarks.asyncmy_lifecycle",
            "--scenario",
            "commit-drop-ack",
        ],
        check=False,
    )
    assert_eq((result.returncode, result.stderr.decode()), (0, ""))
    report = loads(result.stdout)
    assert_eq([r["commit_seen"] for r in report["results"]], [True, True])
    assert_eq(
        [
            (
                r["driver"],
                r["commit_returned"],
                r["error_code"],
                r["commit_forwarded"],
                r["server_ok_seen"],
                r["visible_writes"],
            )
            for r in report["results"]
        ],
        [
            ("aiomysql", False, 2013, True, True, 1),
            ("asyncmy", False, 2013, True, True, 1),
        ],
    )


@test(mark="slow")
async def loss_before_commit_has_the_same_client_error_without_persisting_the_write() -> (
    None
):
    result = await run_process(
        [
            "uv",
            "run",
            "--locked",
            "--with",
            "asyncmy==0.2.16",
            "python",
            "-m",
            "benchmarks.asyncmy_lifecycle",
            "--scenario",
            "commit-drop-before",
        ],
        check=False,
    )
    assert_eq((result.returncode, result.stderr.decode()), (0, ""))
    report = loads(result.stdout)
    assert_eq([r["commit_seen"] for r in report["results"]], [True, True])
    assert_eq(
        [
            (
                r["driver"],
                r["commit_returned"],
                r["error_code"],
                r["commit_forwarded"],
                r["server_ok_seen"],
                r["visible_writes"],
            )
            for r in report["results"]
        ],
        [
            ("aiomysql", False, 2013, False, False, 0),
            ("asyncmy", False, 2013, False, False, 0),
        ],
    )


@test(mark="slow")
async def commit_relay_control_preserves_acknowledged_commits() -> None:
    result = await run_process(
        [
            "uv",
            "run",
            "--locked",
            "--with",
            "asyncmy==0.2.16",
            "python",
            "-m",
            "benchmarks.asyncmy_lifecycle",
            "--scenario",
            "commit-control",
        ],
        check=False,
    )
    assert_eq((result.returncode, result.stderr.decode()), (0, ""))
    report = loads(result.stdout)
    assert_eq([r["commit_seen"] for r in report["results"]], [True, True])
    assert_eq(
        [
            (
                r["driver"],
                r["commit_seen"],
                r["commit_returned"],
                r["error_code"],
                r["commit_forwarded"],
                r["server_ok_seen"],
                r["visible_writes"],
            )
            for r in report["results"]
        ],
        [
            ("aiomysql", True, True, None, True, True, 1),
            ("asyncmy", True, True, None, True, True, 1),
        ],
    )


@test(mark="slow")
async def explicitly_draining_each_result_avoids_native_cleanup_failure() -> None:
    result = await run_process(
        [
            "uv",
            "run",
            "--locked",
            "--with",
            "asyncmy==0.2.16",
            "python",
            "-m",
            "benchmarks.asyncmy_lifecycle",
            "--scenario",
            "multiple-results-drained",
        ],
        check=False,
    )
    assert_eq((result.returncode, result.stderr.decode()), (0, ""))
    report = loads(result.stdout)
    assert_eq(
        [
            (r["driver"], r["status"], r["same_connection"], r["answer"], r["warnings"])
            for r in report["results"]
        ],
        [("aiomysql", "reused", True, 42, []), ("asyncmy", "reused", True, 42, [])],
    )

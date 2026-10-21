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

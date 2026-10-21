"""Exercise the isolated adapter through the public snekql transaction interface."""

from json import loads

from anyio import run_process
from snektest import assert_eq, test


@test(mark="slow")
async def prototype_completes_an_abandoned_stream_and_reuses_its_connection() -> None:
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
            "stream",
        ],
        check=False,
    )
    assert_eq(result.returncode, 0, msg=result.stderr.decode())
    report = loads(result.stdout)
    assert_eq(
        [
            (
                r["driver"],
                r["first_identity"],
                r["same_connection"],
                r["answer"],
                r["commit_outcome"],
                r["warnings"],
            )
            for r in report["results"]
        ],
        [
            ("aiomysql", 1, True, 42, "committed", []),
            ("asyncmy", 1, True, 42, "committed", []),
        ],
    )


@test(mark="slow")
async def prototype_rejects_extra_results_and_replaces_the_connection() -> None:
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
            "extra-results",
        ],
        check=False,
    )
    assert_eq(result.returncode, 0, msg=result.stderr.decode())
    report = loads(result.stdout)
    assert_eq(
        [
            (
                r["driver"],
                r["rejected"],
                r["same_connection"],
                r["answer"],
                r["commit_outcome"],
                r["warnings"],
            )
            for r in report["results"]
        ],
        [
            ("aiomysql", True, False, 42, "not_attempted", []),
            ("asyncmy", True, False, 42, "not_attempted", []),
        ],
    )


@test(mark="slow")
async def prototype_preserves_unknown_commit_outcome_when_acknowledgement_is_lost() -> (
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
            "benchmarks.asyncmy_prototype",
            "--scenario",
            "commit-drop-ack",
        ],
        check=False,
    )
    assert_eq(result.returncode, 0, msg=result.stderr.decode())
    report = loads(result.stdout)
    assert_eq(
        [
            (
                r["driver"],
                r["commit_outcome"],
                r["failure_category"],
                r["failure_code"],
                r["visible_writes"],
                r["server_ok_seen"],
            )
            for r in report["results"]
        ],
        [
            ("aiomysql", "unknown", "connection_loss", 2013, 1, True),
            ("asyncmy", "unknown", "connection_loss", 2013, 1, True),
        ],
    )


@test(mark="slow")
async def prototype_commit_control_reports_committed() -> None:
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
            "commit-control",
        ],
        check=False,
    )
    assert_eq(result.returncode, 0, msg=result.stderr.decode())
    report = loads(result.stdout)
    assert_eq(
        [
            (
                r["driver"],
                r["commit_outcome"],
                r["failure_category"],
                r["visible_writes"],
            )
            for r in report["results"]
        ],
        [("aiomysql", "committed", None, 1), ("asyncmy", "committed", None, 1)],
    )


@test(mark="slow")
async def prototype_does_not_infer_rollback_from_commit_connection_loss() -> None:
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
            "commit-drop-before",
        ],
        check=False,
    )
    assert_eq(result.returncode, 0, msg=result.stderr.decode())
    report = loads(result.stdout)
    assert_eq(
        [
            (
                r["driver"],
                r["commit_outcome"],
                r["failure_category"],
                r["failure_code"],
                r["visible_writes"],
                r["commit_seen"],
                r["commit_forwarded"],
            )
            for r in report["results"]
        ],
        [
            ("aiomysql", "unknown", "connection_loss", 2013, 0, True, False),
            ("asyncmy", "unknown", "connection_loss", 2013, 0, True, False),
        ],
    )

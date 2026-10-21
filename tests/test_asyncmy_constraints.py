"""Public transaction checks for the restricted asyncmy prototype."""

from json import loads

from anyio import run_process
from snektest import Param, assert_eq, assert_not_in, test


@test(mark="slow")
async def duplicate_key_rolls_back_only_the_savepoint_and_redacts_values() -> None:
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
            "constraint-unique",
        ],
        check=False,
    )
    assert_eq(result.returncode, 0, msg=result.stderr.decode())
    assert_not_in(
        "probe-secret-unique-value", result.stdout.decode() + result.stderr.decode()
    )
    report = loads(result.stdout)
    assert_eq([r["traceback_redacted"] for r in report["results"]], [True, True])
    assert_eq(
        [
            (
                r["driver"],
                r["category"],
                r["code"],
                r["same_connection"],
                r["ids"],
                r["commit_outcome"],
                r["error_redacted"],
                r["warnings"],
            )
            for r in report["results"]
        ],
        [
            ("aiomysql", "unique_violation", 1062, True, [1, 3], "committed", True, []),
            ("asyncmy", "unique_violation", 1062, True, [1, 3], "committed", True, []),
        ],
    )


@test(
    [
        Param(("not-null", "not_null_violation", 1048), name="not-null"),
        Param(("check", "check_violation", 4025), name="check"),
        Param(("foreign-insert", "foreign_key_violation", 1452), name="foreign-insert"),
        Param(("foreign-delete", "foreign_key_violation", 1451), name="foreign-delete"),
    ],
    mark="slow",
)
async def recognized_constraint_errors_preserve_outer_work(
    case: tuple[str, str, int],
) -> None:
    scenario, category, code = case
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
            f"constraint-{scenario}",
        ],
        check=False,
    )
    assert_eq(result.returncode, 0, msg=result.stderr.decode())
    report = loads(result.stdout)
    assert_eq(
        [
            (
                r["driver"],
                r["category"],
                r["code"],
                r["same_connection"],
                r["ids"],
                r["commit_outcome"],
                r["warnings"],
            )
            for r in report["results"]
        ],
        [
            ("aiomysql", category, code, True, [1, 3], "committed", []),
            ("asyncmy", category, code, True, [1, 3], "committed", []),
        ],
    )


@test(mark="slow")
async def constraint_without_savepoint_remains_terminal() -> None:
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
            "constraint-no-savepoint",
        ],
        check=False,
    )
    assert_eq(result.returncode, 0, msg=result.stderr.decode())
    report = loads(result.stdout)
    assert_eq(
        [
            (
                r["driver"],
                r["category"],
                r["blocked"],
                r["same_connection"],
                r["ids"],
                r["commit_outcome"],
            )
            for r in report["results"]
        ],
        [
            ("aiomysql", "unique_violation", True, False, [], "not_attempted"),
            ("asyncmy", "unique_violation", True, False, [], "not_attempted"),
        ],
    )


@test(mark="slow")
async def lock_timeout_inside_savepoint_is_not_treated_as_recoverable_constraint() -> (
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
            "constraint-lock-timeout",
        ],
        check=False,
    )
    assert_eq(result.returncode, 0, msg=result.stderr.decode())
    report = loads(result.stdout)
    assert_eq(
        [
            (
                r["driver"],
                r["category"],
                r["code"],
                r["blocked"],
                r["same_connection"],
                r["ids"],
                r["commit_outcome"],
            )
            for r in report["results"]
        ],
        [
            ("aiomysql", "lock_conflict", 1205, True, False, [], "not_attempted"),
            ("asyncmy", "lock_conflict", 1205, True, False, [], "not_attempted"),
        ],
    )

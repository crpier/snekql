"""Fault real startup traffic; observe public errors and client-initiated EOF."""

from json import loads

from anyio import run_process
from snektest import assert_eq, test


@test(mark="slow")
async def settings_deadline_closes_partial_connection_and_allows_fresh_startup() -> (
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
            "startup-deadline",
        ],
        check=False,
    )
    assert_eq(result.returncode, 0, msg=result.stderr.decode())
    report = loads(result.stdout)
    assert_eq([r["driver"] for r in report["results"]], ["aiomysql", "asyncmy"])
    for observed in report["results"]:
        assert_eq(
            (
                observed["settings_seen"],
                observed["error_type"],
                observed["public_error"],
                observed["client_eof_before_cleanup"],
                observed["recovery_answer"],
                observed["recovery_zone"],
                observed["final_state"],
            ),
            (True, "PoolTimeoutError", True, True, 42, "+00:00", "closed"),
        )
        assert_eq(observed["relay_stopped_before_observation"], False)
        assert_eq(observed["warnings"], [])


@test(mark="slow")
async def cancelled_settings_initialization_closes_its_partial_connection() -> None:
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
            "startup-cancel",
        ],
        check=False,
    )
    assert_eq(result.returncode, 0, msg=result.stderr.decode())
    report = loads(result.stdout)
    assert_eq([r["driver"] for r in report["results"]], ["aiomysql", "asyncmy"])
    for observed in report["results"]:
        assert_eq(
            (
                observed["settings_seen"],
                observed["error_type"],
                observed["client_eof_before_cleanup"],
                observed["recovery_answer"],
                observed["recovery_zone"],
                observed["final_state"],
            ),
            (True, "CancelledError", True, 42, "+00:00", "closed"),
        )
        assert_eq(observed["relay_stopped_before_observation"], False)
        assert_eq(observed["warnings"], [])


@test(mark="slow")
async def rejected_startup_settings_characterize_native_errors_and_close_the_connection() -> (
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
            "startup-rejected-setting",
        ],
        check=False,
    )
    assert_eq(result.returncode, 0, msg=result.stderr.decode())
    report = loads(result.stdout)
    assert_eq([r["driver"] for r in report["results"]], ["aiomysql", "asyncmy"])
    for observed in report["results"]:
        assert_eq(
            (observed["error_type"], observed["public_error"]),
            ("OperationalError", False),
        )
        assert_eq(
            (
                observed["settings_seen"],
                observed["error_code"],
                observed["client_eof_before_cleanup"],
                observed["recovery_answer"],
                observed["recovery_zone"],
                observed["final_state"],
            ),
            (True, 1231, True, 42, "+00:00", "closed"),
        )
        assert_eq(observed["relay_stopped_before_observation"], False)
        assert_eq(observed["warnings"], [])


@test(mark="slow")
async def acquisition_deadline_bounds_startup_authentication() -> None:
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
            "startup-auth-deadline",
        ],
        check=False,
    )
    assert_eq(result.returncode, 0, msg=result.stderr.decode())
    report = loads(result.stdout)
    assert_eq([r["driver"] for r in report["results"]], ["aiomysql", "asyncmy"])
    for observed in report["results"]:
        assert_eq(observed["authentication_seen"], True)
        assert_eq(
            (
                observed["error_type"],
                observed["watchdog_expired"],
                observed["client_eof_before_cleanup"],
            ),
            ("PoolTimeoutError", False, True),
        )
        assert_eq(
            (
                observed["recovery_answer"],
                observed["recovery_zone"],
                observed["final_state"],
            ),
            (42, "+00:00", "closed"),
        )
        assert_eq(observed["warnings"], [])

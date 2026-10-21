"""Real TLS and wire-observed initialization checks in an isolated overlay."""

from json import loads

from anyio import run_process
from snektest import Param, assert_eq, assert_in, test


@test(mark="slow")
async def native_drivers_negotiate_verified_tls() -> None:
    result = await run_process(
        [
            "uv",
            "run",
            "--locked",
            "--with",
            "asyncmy==0.2.16",
            "python",
            "-m",
            "benchmarks.asyncmy_tls",
            "--scenario",
            "verified",
        ],
        check=False,
    )
    assert_eq(result.returncode, 0, msg=result.stderr.decode())
    report = loads(result.stdout)
    assert_eq([r["driver"] for r in report["results"]], ["aiomysql", "asyncmy"])
    for observed in report["results"]:
        assert_eq(
            (observed["connected"], observed["cipher_present"], observed["answer"]),
            (True, True, 42),
        )
        assert_in(observed["tls_version"], ("TLSv1.2", "TLSv1.3"))


@test(
    [Param("untrusted", name="untrusted"), Param("wrong-host", name="wrong-host")],
    mark="slow",
)
async def native_drivers_reject_unverified_tls(scenario: str) -> None:
    result = await run_process(
        [
            "uv",
            "run",
            "--locked",
            "--with",
            "asyncmy==0.2.16",
            "python",
            "-m",
            "benchmarks.asyncmy_tls",
            "--scenario",
            scenario,
        ],
        check=False,
    )
    assert_eq(result.returncode, 0, msg=result.stderr.decode())
    report = loads(result.stdout)
    assert_eq(
        [
            (r["driver"], r["connected"], r["certificate_failure"])
            for r in report["results"]
        ],
        [("aiomysql", False, True), ("asyncmy", False, True)],
    )


@test(mark="slow")
async def tls_stripped_greeting_characterizes_native_and_guarded_responses() -> None:
    result = await run_process(
        [
            "uv",
            "run",
            "--locked",
            "--with",
            "asyncmy==0.2.16",
            "python",
            "-m",
            "benchmarks.asyncmy_tls",
            "--scenario",
            "stripped",
        ],
        check=False,
    )
    assert_eq(result.returncode, 0, msg=result.stderr.decode())
    report = loads(result.stdout)
    assert_eq(
        [(r["driver"], r["connected"], r["response_kind"]) for r in report["results"]],
        [
            ("aiomysql", False, "handshake-response"),
            ("asyncmy", False, "ssl-request"),
            ("snekql-aiomysql", False, "eof"),
        ],
    )


@test(mark="slow")
async def cancelled_native_pool_initialization_closes_its_socket_without_help() -> None:
    result = await run_process(
        [
            "uv",
            "run",
            "--locked",
            "--with",
            "asyncmy==0.2.16",
            "python",
            "-m",
            "benchmarks.asyncmy_tls",
            "--scenario",
            "cancel-initialization",
        ],
        check=False,
    )
    assert_eq(result.returncode, 0, msg=result.stderr.decode())
    report = loads(result.stdout)
    assert_eq([r["driver"] for r in report["results"]], ["aiomysql", "asyncmy"])
    for observed in report["results"]:
        assert_eq(
            (
                observed["error_type"],
                observed["peer_closed_before_cleanup"],
                observed["pre_cleanup_response_bytes"],
                observed["recovery_answer"],
                observed["recovery_cipher_present"],
                observed["shutdown_completed"],
            ),
            ("CancelledError", True, 0, 42, True, True),
        )


@test(mark="slow")
async def cancelled_native_tls_growth_recovers_bounded_pool_capacity() -> None:
    result = await run_process(
        [
            "uv",
            "run",
            "--locked",
            "--with",
            "asyncmy==0.2.16",
            "python",
            "-m",
            "benchmarks.asyncmy_tls",
            "--scenario",
            "cancel-growth",
        ],
        check=False,
    )
    assert_eq(result.returncode, 0, msg=result.stderr.decode())
    report = loads(result.stdout)
    assert_eq([r["driver"] for r in report["results"]], ["aiomysql", "asyncmy"])
    for observed in report["results"]:
        assert_eq(
            (
                observed["error_type"],
                observed["peer_closed_before_cleanup"],
                observed["pre_cleanup_response_bytes"],
                observed["recovery_answer"],
                observed["recovery_cipher_present"],
                observed["different_connection"],
                observed["size_with_first_held"],
                observed["free_with_first_held"],
                observed["shutdown_completed"],
            ),
            ("CancelledError", True, 0, 42, True, True, 2, 1, True),
        )

"""Comparative measurements must describe completed, validated database work."""

import sys
from asyncio import to_thread
from hashlib import sha256
from json import loads
from os import environ, pathsep
from pathlib import Path

from anyio import Path as AsyncPath
from anyio import TemporaryDirectory, run_process
from snektest import Param, assert_eq, assert_in, test


@test(
    [
        Param("raw", name="raw"),
        Param("snekql", name="snekql"),
        Param("sqlalchemy", name="sqlalchemy"),
    ],
    [Param("sqlite", name="sqlite"), Param("mariadb", name="mariadb")],
    mark="slow",
)
async def comparison_reports_observed_work(adapter: str, backend: str) -> None:
    """Three point reads must actually return the three seeded identities."""
    async with TemporaryDirectory(prefix="sq-") as directory:
        result = await run_process(
            [
                sys.executable,
                "-m",
                "benchmarks.compare",
                "--backend",
                backend,
                "--adapter",
                adapter,
                "--operations",
                "3",
                "--rows",
                "3",
                "--trials",
                "1",
                "--warmup",
                "1",
            ],
            check=False,
            env={**environ, "TMPDIR": directory},
        )
        assert_eq((result.returncode, result.stderr.decode()), (0, ""))
        report = loads(result.stdout)
        assert_eq(report["schema_version"], 2)
        assert_eq(report["backend"], backend)
        assert_eq(
            report["trials"][0]["observed"],
            {"rows": 3, "identity_sum": 6, "payload_bytes": 96},
        )
        assert_eq(report["trials"][0]["latency"]["count"], 3)
        assert_eq([path async for path in AsyncPath(directory).iterdir()], [])


@test(
    [
        Param(("operations", "0"), name="zero-operations"),
        Param(("workers", "0"), name="zero-workers"),
        Param(("rows", "0"), name="zero-rows"),
        Param(("trials", "0"), name="zero-trials"),
        Param(("warmup", "-1"), name="negative-warmup"),
        Param(("batch-size", "0"), name="zero-batch-size"),
        Param(("pool-size", "0"), name="zero-pool-size"),
        Param(("pool-size", "33"), name="excess-pool-size"),
        Param(("payload-bytes", "0"), name="zero-payload"),
        Param(("payload-bytes", "8193"), name="excess-payload"),
    ],
    mark="slow",
)
async def comparison_rejects_invalid_bounds(option: tuple[str, str]) -> None:
    """Invalid run sizes must fail as usage errors without a success report."""
    result = await run_process(
        [
            sys.executable,
            "-m",
            "benchmarks.compare",
            "--backend",
            "sqlite",
            "--operations",
            "1",
            "--rows",
            "1",
            "--trials",
            "1",
            "--warmup",
            "0",
            f"--{option[0]}",
            option[1],
        ],
        check=False,
    )
    assert_eq(result.returncode, 2)
    assert_eq(result.stdout, b"")
    assert_in(b"must be between", result.stderr)


@test(mark="slow")
async def comparison_rotates_adapter_order_between_trials() -> None:
    """Every adapter gets each run position, rather than always running last."""
    result = await run_process(
        [
            sys.executable,
            "-m",
            "benchmarks.compare",
            "--backend",
            "sqlite",
            "--adapter",
            "all",
            "--operations",
            "1",
            "--rows",
            "1",
            "--trials",
            "3",
            "--warmup",
            "0",
        ],
        check=False,
    )
    assert_eq((result.returncode, result.stderr.decode()), (0, ""))
    report = loads(result.stdout)
    assert_eq(
        [(trial["round"], trial["adapter"]) for trial in report["trials"]],
        [
            (1, "raw"),
            (1, "snekql"),
            (1, "sqlalchemy"),
            (2, "snekql"),
            (2, "sqlalchemy"),
            (2, "raw"),
            (3, "sqlalchemy"),
            (3, "raw"),
            (3, "snekql"),
        ],
    )


@test(mark="slow")
async def comparison_reports_reproduction_settings() -> None:
    """A saved report must retain the workload size and measurement policies."""
    result = await run_process(
        [
            sys.executable,
            "-m",
            "benchmarks.compare",
            "--backend",
            "sqlite",
            "--adapter",
            "raw",
            "--operations",
            "2",
            "--rows",
            "3",
            "--trials",
            "1",
            "--warmup",
            "0",
        ],
        check=False,
    )
    assert_eq((result.returncode, result.stderr.decode()), (0, ""))
    report = loads(result.stdout)
    assert_eq(
        report["configuration"],
        {
            "operations": 2,
            "adapter_order": "balanced",
            "rows": 3,
            "trials": 1,
            "warmup": 0,
            "workers": 1,
            "pool_size": 1,
            "payload_bytes": 32,
            "telemetry": "off",
            "buffering": "fetch-all",
            "validation": "strict-pydantic",
            "transaction": "explicit-begin-commit",
            "query_construction": "per-operation",
            "sqlite": {
                "journal_mode": "WAL",
                "synchronous": "NORMAL",
                "foreign_keys": True,
                "busy_timeout_ms": 5000,
            },
        },
    )


@test(
    [
        Param("raw", name="raw"),
        Param("snekql", name="snekql"),
        Param("sqlalchemy", name="sqlalchemy"),
    ],
    mark="slow",
)
async def mariadb_comparison_verifies_session_policy(adapter: str) -> None:
    """The measured connection must expose the common isolation/integrity policy."""
    result = await run_process(
        [
            sys.executable,
            "-m",
            "benchmarks.compare",
            "--backend",
            "mariadb",
            "--adapter",
            adapter,
            "--operations",
            "1",
            "--rows",
            "1",
            "--trials",
            "1",
            "--warmup",
            "0",
        ],
        check=False,
    )
    assert_eq((result.returncode, result.stderr.decode()), (0, ""))
    report = loads(result.stdout)
    assert_eq(
        report["trials"][0]["session_policy"],
        {
            "charset": "utf8mb4",
            "autocommit": 0,
            "read_only": 0,
            "isolation": "REPEATABLE-READ",
            "time_zone": "+00:00",
            "foreign_key_checks": 1,
            "check_constraint_checks": 1,
            "unique_checks": 1,
            "sql_mode": [
                "ERROR_FOR_DIVISION_BY_ZERO",
                "NO_ENGINE_SUBSTITUTION",
                "NO_ZERO_DATE",
                "NO_ZERO_IN_DATE",
                "STRICT_ALL_TABLES",
            ],
        },
    )
    assert_in("MariaDB", report["environment"]["mariadb"]["version"])


@test(mark="slow")
async def comparison_rejects_session_policy_drift() -> None:
    """A native connection with disabled integrity checks cannot produce a report."""
    driver_fault = """
import runpy
from aiomysql import Cursor
original = Cursor.execute
async def execute(self, query, args=None):
    if isinstance(query, str) and "@@SESSION.character_set_connection" in query:
        await original(self, "SET SESSION unique_checks = 0")
    return await original(self, query, args)
Cursor.execute = execute
runpy.run_module("benchmarks.compare", run_name="__main__")
"""
    async with TemporaryDirectory(prefix="sq-") as directory:
        result = await run_process(
            [
                sys.executable,
                "-c",
                driver_fault,
                "--backend",
                "mariadb",
                "--adapter",
                "raw",
                "--operations",
                "1",
                "--rows",
                "1",
                "--trials",
                "1",
                "--warmup",
                "0",
            ],
            check=False,
            env={**environ, "TMPDIR": directory},
        )
        assert_eq(result.returncode, 1)
        assert_eq(result.stdout, b"")
        assert_in(
            b"connection policy differs from the declared contract", result.stderr
        )


@test(mark="slow")
async def unavailable_mariadb_does_not_become_a_successful_skip() -> None:
    """An explicitly requested backend must be measured or fail."""
    async with TemporaryDirectory(prefix="sq-") as directory:
        result = await run_process(
            [
                sys.executable,
                "-m",
                "benchmarks.compare",
                "--backend",
                "mariadb",
                "--adapter",
                "raw",
                "--operations",
                "1",
                "--rows",
                "1",
                "--trials",
                "1",
                "--warmup",
                "0",
            ],
            env={**environ, "PATH": "", "TMPDIR": directory},
            check=False,
        )
        assert_eq(result.returncode, 1)
        assert_eq(result.stdout, b"")
        assert_in(b"mariadb-install-db", result.stderr)


@test(
    [
        Param("raw", name="raw"),
        Param("snekql", name="snekql"),
        Param("sqlalchemy", name="sqlalchemy"),
    ],
    [Param("sqlite", name="sqlite"), Param("mariadb", name="mariadb")],
    mark="slow",
)
async def streaming_comparison_consumes_partial_final_batch(
    adapter: str, backend: str
) -> None:
    """Two scans of five rows must consume the final one-row batch too."""
    result = await run_process(
        [
            sys.executable,
            "-m",
            "benchmarks.compare",
            "--backend",
            backend,
            "--adapter",
            adapter,
            "--workload",
            "stream",
            "--batch-size",
            "2",
            "--operations",
            "2",
            "--rows",
            "5",
            "--trials",
            "1",
            "--warmup",
            "1",
        ],
        check=False,
    )
    assert_eq((result.returncode, result.stderr.decode()), (0, ""))
    report = loads(result.stdout)
    assert_eq(report["workload"], "stream")
    assert_eq(
        report["trials"][0]["observed"],
        {"rows": 10, "identity_sum": 30, "payload_bytes": 320},
    )
    assert_eq(report["trials"][0]["stream"], {"batches": 6, "max_batch_rows": 2})
    assert_eq(report["trials"][0]["latency"]["count"], 2)


@test(
    [Param("truncate", name="truncate"), Param("duplicate", name="duplicate")],
    mark="slow",
)
async def streaming_comparison_rejects_incomplete_delivery(fault: str) -> None:
    """Valid row types alone cannot certify a complete ordered scan."""
    driver_fault = """
import runpy
from aiosqlite import Cursor
original = Cursor.fetchmany
async def fetchmany(self, size=None):
    rows = await original(self, size)
    if FAULT == "truncate" and len(rows) == 1:
        return []
    if FAULT == "duplicate" and len(rows) == 2:
        return [rows[0], rows[0]]
    return rows
Cursor.fetchmany = fetchmany
runpy.run_module("benchmarks.compare", run_name="__main__")
""".replace("FAULT", repr(fault))
    result = await run_process(
        [
            sys.executable,
            "-c",
            driver_fault,
            "--backend",
            "sqlite",
            "--adapter",
            "raw",
            "--workload",
            "stream",
            "--batch-size",
            "2",
            "--operations",
            "1",
            "--rows",
            "5",
            "--trials",
            "1",
            "--warmup",
            "0",
        ],
        check=False,
    )
    assert_eq(result.returncode, 1)
    assert_eq(result.stdout, b"")
    assert_in(b"ComparisonError: stream", result.stderr)


@test(mark="slow")
async def comparison_observes_an_injected_loop_stall() -> None:
    """A deliberate driver callback block must appear in heartbeat diagnostics."""
    driver_fault = """
import runpy
from time import sleep
from aiosqlite import Cursor
original = Cursor.fetchmany
async def fetchmany(self, size=None):
    sleep(0.05)
    return await original(self, size)
Cursor.fetchmany = fetchmany
runpy.run_module("benchmarks.compare", run_name="__main__")
"""
    result = await run_process(
        [
            sys.executable,
            "-c",
            driver_fault,
            "--backend",
            "sqlite",
            "--adapter",
            "raw",
            "--workload",
            "stream",
            "--batch-size",
            "2",
            "--operations",
            "1",
            "--rows",
            "5",
            "--trials",
            "1",
            "--warmup",
            "0",
        ],
        check=False,
    )
    assert_eq((result.returncode, result.stderr.decode()), (0, ""))
    report = loads(result.stdout)
    assert report["trials"][0]["loop_stall"]["max_ms"] >= 20


@test(
    [
        Param("raw", name="raw"),
        Param("snekql", name="snekql"),
        Param("sqlalchemy", name="sqlalchemy"),
    ],
    [Param("sqlite", name="sqlite"), Param("mariadb", name="mariadb")],
    mark="slow",
)
async def streaming_comparison_does_not_fetch_all(adapter: str, backend: str) -> None:
    """A result-bearing stream must not call the native cursor's fetchall."""
    driver_guard = """
import runpy
if BACKEND == "sqlite":
    from aiosqlite import Cursor
else:
    from aiomysql import Cursor
original = Cursor.fetchall
async def fetchall(self):
    if self.description and any(column[0] == "payload" for column in self.description):
        raise AssertionError("stream used buffered fetchall")
    return await original(self)
Cursor.fetchall = fetchall
if BACKEND == "mariadb":
    from aiomysql import SSCursor
    original_stream = SSCursor.fetchall
    async def stream_fetchall(self):
        raise AssertionError("stream used unbounded server-cursor fetchall")
    SSCursor.fetchall = stream_fetchall
runpy.run_module("benchmarks.compare", run_name="__main__")
""".replace("BACKEND", repr(backend))
    result = await run_process(
        [
            sys.executable,
            "-c",
            driver_guard,
            "--backend",
            backend,
            "--adapter",
            adapter,
            "--workload",
            "stream",
            "--batch-size",
            "2",
            "--operations",
            "1",
            "--rows",
            "5",
            "--trials",
            "1",
            "--warmup",
            "0",
        ],
        check=False,
    )
    assert_eq((result.returncode, result.stderr.decode()), (0, ""))
    assert_eq(
        loads(result.stdout)["trials"][0]["observed"],
        {"rows": 5, "identity_sum": 15, "payload_bytes": 160},
    )


@test(
    [
        Param("raw", name="raw"),
        Param("snekql", name="snekql"),
        Param("sqlalchemy", name="sqlalchemy"),
    ],
    [Param("sqlite", name="sqlite"), Param("mariadb", name="mariadb")],
    mark="slow",
)
async def join_comparison_reads_the_related_record(adapter: str, backend: str) -> None:
    """The joined payload differs from the base table's payload."""
    result = await run_process(
        [
            sys.executable,
            "-m",
            "benchmarks.compare",
            "--backend",
            backend,
            "--adapter",
            adapter,
            "--workload",
            "join",
            "--operations",
            "3",
            "--rows",
            "3",
            "--trials",
            "1",
            "--warmup",
            "0",
        ],
        check=False,
    )
    assert_eq((result.returncode, result.stderr.decode()), (0, ""))
    report = loads(result.stdout)
    assert_eq(report["workload"], "join")
    assert_eq(
        report["trials"][0]["observed"],
        {"rows": 3, "identity_sum": 6, "payload_bytes": 96},
    )


@test(
    [
        Param("raw", name="raw"),
        Param("snekql", name="snekql"),
        Param("sqlalchemy", name="sqlalchemy"),
    ],
    [Param("sqlite", name="sqlite"), Param("mariadb", name="mariadb")],
    mark="slow",
)
async def bulk_comparison_verifies_committed_rows(adapter: str, backend: str) -> None:
    """Warmup and earlier trials must not change the measured insert dataset."""
    result = await run_process(
        [
            sys.executable,
            "-m",
            "benchmarks.compare",
            "--backend",
            backend,
            "--adapter",
            adapter,
            "--workload",
            "bulk",
            "--batch-size",
            "2",
            "--workers",
            "4",
            "--operations",
            "3",
            "--rows",
            "1",
            "--trials",
            "2",
            "--warmup",
            "1",
        ],
        check=False,
    )
    assert_eq((result.returncode, result.stderr.decode()), (0, ""))
    report = loads(result.stdout)
    assert_eq(report["workload"], "bulk")
    assert_eq(
        [trial["observed"] for trial in report["trials"]],
        [
            {"rows": 6, "identity_sum": 21, "payload_bytes": 192},
            {"rows": 6, "identity_sum": 21, "payload_bytes": 192},
        ],
    )


@test(mark="slow")
async def bulk_comparison_rejects_uncommitted_rows() -> None:
    """A simulated successful reply without persistence must fail readback."""
    driver_fault = """
import runpy
from aiosqlite import Connection
original_execute = Connection.execute
original_commit = Connection.commit
pending = set()
def execute(self, sql, parameters=None):
    if "INSERT INTO bench_write" in sql:
        pending.add(id(self))
    return original_execute(self, sql, parameters)
async def commit(self):
    if id(self) in pending:
        pending.remove(id(self))
        await self.rollback()
    else:
        await original_commit(self)
Connection.execute = execute
Connection.commit = commit
runpy.run_module("benchmarks.compare", run_name="__main__")
"""
    result = await run_process(
        [
            sys.executable,
            "-c",
            driver_fault,
            "--backend",
            "sqlite",
            "--adapter",
            "raw",
            "--workload",
            "bulk",
            "--batch-size",
            "2",
            "--operations",
            "1",
            "--rows",
            "1",
            "--trials",
            "1",
            "--warmup",
            "0",
        ],
        check=False,
    )
    assert_eq(result.returncode, 1)
    assert_eq(result.stdout, b"")
    assert_in(b"bulk write did not return its committed records", result.stderr)


@test(
    [
        Param("raw", name="raw"),
        Param("snekql", name="snekql"),
        Param("sqlalchemy", name="sqlalchemy"),
    ],
    [Param("sqlite", name="sqlite"), Param("mariadb", name="mariadb")],
    mark="slow",
)
async def contended_comparison_completes_every_request(
    adapter: str, backend: str
) -> None:
    """Four workers safely share capacity one without losing or duplicating work."""
    result = await run_process(
        [
            sys.executable,
            "-m",
            "benchmarks.compare",
            "--backend",
            backend,
            "--adapter",
            adapter,
            "--workers",
            "4",
            "--operations",
            "12",
            "--rows",
            "3",
            "--trials",
            "1",
            "--warmup",
            "1",
        ],
        check=False,
    )
    assert_eq((result.returncode, result.stderr.decode()), (0, ""))
    report = loads(result.stdout)
    assert_eq(report["configuration"]["workers"], 4)
    assert_eq(report["configuration"]["pool_size"], 1)
    assert_eq(
        report["trials"][0]["observed"],
        {"rows": 12, "identity_sum": 24, "payload_bytes": 384},
    )
    assert_eq(report["trials"][0]["per_worker_operations"], [3, 3, 3, 3])
    assert_eq(report["trials"][0]["latency"]["count"], 12)


@test(
    [
        Param("raw", name="raw"),
        Param("snekql", name="snekql"),
        Param("sqlalchemy", name="sqlalchemy"),
    ],
    [Param("sqlite", name="sqlite"), Param("mariadb", name="mariadb")],
    mark="slow",
)
async def pool_diagnostics_exclude_setup_and_warmup(adapter: str, backend: str) -> None:
    """Pool timings count only measured acquisitions and identify their scope."""
    result = await run_process(
        [
            sys.executable,
            "-m",
            "benchmarks.compare",
            "--backend",
            backend,
            "--adapter",
            adapter,
            "--profile",
            "diagnostic",
            "--workers",
            "4",
            "--operations",
            "8",
            "--rows",
            "2",
            "--trials",
            "1",
            "--warmup",
            "2",
        ],
        check=False,
    )
    assert_eq((result.returncode, result.stderr.decode()), (0, ""))
    report = loads(result.stdout)
    pool = report["trials"][0]["pool"]
    assert_eq(
        pool["metric"], "checkout" if adapter == "sqlalchemy" else "admission_wait"
    )
    assert_eq(pool["summary"]["count"], 8)
    assert_eq(report["measurement"]["profile"], "diagnostic")


@test(mark="slow")
async def memory_profile_reports_scoped_python_allocations() -> None:
    """Memory instrumentation is explicit and still verifies every streamed row."""
    result = await run_process(
        [
            sys.executable,
            "-m",
            "benchmarks.compare",
            "--backend",
            "sqlite",
            "--adapter",
            "raw",
            "--profile",
            "memory",
            "--workload",
            "stream",
            "--batch-size",
            "64",
            "--operations",
            "2",
            "--rows",
            "2000",
            "--trials",
            "1",
            "--warmup",
            "1",
        ],
        check=False,
    )
    assert_eq((result.returncode, result.stderr.decode()), (0, ""))
    report = loads(result.stdout)
    trial = report["trials"][0]
    assert_eq(report["measurement"]["profile"], "memory")
    assert_eq(
        trial["observed"],
        {"rows": 4000, "identity_sum": 4002000, "payload_bytes": 128000},
    )
    assert trial["memory"]["python_traced_peak_bytes"] > 0
    assert (
        trial["memory"]["python_traced_peak_bytes"]
        >= trial["memory"]["python_traced_current_bytes"]
        >= 0
    )
    assert_eq(trial["pool"], None)


@test(mark="slow")
async def comparison_reports_hardware_provenance() -> None:
    """A saved measurement identifies available hardware without invented values."""
    result = await run_process(
        [
            sys.executable,
            "-m",
            "benchmarks.compare",
            "--backend",
            "sqlite",
            "--adapter",
            "raw",
            "--operations",
            "1",
            "--rows",
            "1",
            "--trials",
            "1",
            "--warmup",
            "0",
        ],
        check=False,
    )
    assert_eq((result.returncode, result.stderr.decode()), (0, ""))
    hardware = loads(result.stdout)["environment"]["hardware"]
    assert_in("cpu_model", hardware)
    assert_in("memory_total_bytes", hardware)
    assert_in("affinity", hardware)
    if sys.platform == "linux":
        assert hardware["cpu_model"]
        assert hardware["memory_total_bytes"] > 0
        assert hardware["affinity"]


@test([Param("sqlite", name="sqlite"), Param("mariadb", name="mariadb")], mark="slow")
async def comparison_prepares_every_capacity_slot_before_timing(backend: str) -> None:
    """Each adapter must verify three simultaneously held sessions, not relabel capacity one."""
    result = await run_process(
        [
            sys.executable,
            "-m",
            "benchmarks.compare",
            "--backend",
            backend,
            "--adapter",
            "all",
            "--pool-size",
            "3",
            "--workers",
            "6",
            "--operations",
            "12",
            "--rows",
            "3",
            "--trials",
            "1",
            "--warmup",
            "1",
        ],
        check=False,
    )
    assert_eq((result.returncode, result.stderr.decode()), (0, ""))
    report = loads(result.stdout)
    assert_eq(report["schema_version"], 2)
    assert_eq(report["configuration"]["pool_size"], 3)
    for trial in report["trials"]:
        assert_eq(trial["prepared_sessions"], 3)
        assert_eq(
            trial["observed"], {"rows": 12, "identity_sum": 24, "payload_bytes": 384}
        )
        assert_eq(trial["per_worker_operations"], [2, 2, 2, 2, 2, 2])
        assert_eq(trial["latency"]["count"], 12)
        assert_eq(trial["session_policy"] is not None, True)
        if backend == "sqlite":
            assert_eq(
                trial["session_policy"],
                {
                    "journal_mode": "wal",
                    "synchronous": 1,
                    "foreign_keys": 1,
                    "busy_timeout_ms": 5000,
                },
            )


@test(
    [Param("sqlite", name="sqlite"), Param("mariadb", name="mariadb")],
    [
        Param("point-read", name="point"),
        Param("join", name="join"),
        Param("stream", name="stream"),
        Param("bulk", name="bulk"),
    ],
    mark="slow",
)
async def comparison_validates_wide_payload_work_on_every_adapter(
    backend: str, workload: str
) -> None:
    """Wide returned bytes must be observed, not merely requested in configuration."""
    result = await run_process(
        [
            sys.executable,
            "-m",
            "benchmarks.compare",
            "--backend",
            backend,
            "--adapter",
            "all",
            "--pool-size",
            "2",
            "--workers",
            "4",
            "--payload-bytes",
            "4096",
            "--workload",
            workload,
            "--batch-size",
            "2",
            "--operations",
            "2",
            "--rows",
            "5",
            "--trials",
            "1",
            "--warmup",
            "1",
        ],
        check=False,
    )
    assert_eq((result.returncode, result.stderr.decode()), (0, ""))
    report = loads(result.stdout)
    assert_eq(report["configuration"]["payload_bytes"], 4096)
    expected = {
        "point-read": {"rows": 2, "identity_sum": 3, "payload_bytes": 8192},
        "join": {"rows": 2, "identity_sum": 3, "payload_bytes": 8192},
        "stream": {"rows": 10, "identity_sum": 30, "payload_bytes": 40960},
        "bulk": {"rows": 4, "identity_sum": 10, "payload_bytes": 16384},
    }[workload]
    for trial in report["trials"]:
        assert_eq(trial["observed"], expected)
        assert_eq(trial["prepared_sessions"], 2)
        if workload == "stream":
            assert_eq(trial["stream"], {"batches": 6, "max_batch_rows": 2})


@test(
    [Param("sqlite", name="sqlite"), Param("mariadb", name="mariadb")],
    [Param("off", name="off"), Param("on", name="on")],
    mark="slow",
)
async def comparison_times_counting_observation_independently_of_pool_profile(
    backend: str, telemetry: str
) -> None:
    """Only snekql installs the requested observer; warmup never enters measured counts."""
    result = await run_process(
        [
            sys.executable,
            "-m",
            "benchmarks.compare",
            "--backend",
            backend,
            "--adapter",
            "all",
            "--telemetry",
            telemetry,
            "--profile",
            "timing",
            "--pool-size",
            "2",
            "--workers",
            "4",
            "--operations",
            "3",
            "--rows",
            "3",
            "--trials",
            "1",
            "--warmup",
            "2",
        ],
        check=False,
    )
    assert_eq((result.returncode, result.stderr.decode()), (0, ""))
    report = loads(result.stdout)
    assert_eq(report["configuration"]["telemetry"], telemetry)
    for trial in report["trials"]:
        observed = trial["telemetry"]
        enabled = telemetry == "on" and trial["adapter"] == "snekql"
        assert_eq(observed["observer_installed"], enabled)
        assert_eq(observed["counting_enabled"], enabled)
        assert_eq(trial["pool"], None)
        if enabled:
            assert_eq(observed["events"]["transaction:finish"], 3)
            assert_eq(observed["events"]["pool_wait:finish"], 3)
            assert_eq(observed["events"]["materialization:finish"], 3)
        else:
            assert_eq(observed["events"], {})


@test(mark="slow")
async def six_balanced_rounds_cover_every_adapter_permutation() -> None:
    """Reverse the second rotation cycle instead of repeating the same three orders."""
    result = await run_process(
        [
            sys.executable,
            "-m",
            "benchmarks.compare",
            "--backend",
            "sqlite",
            "--adapter",
            "all",
            "--order",
            "balanced",
            "--operations",
            "1",
            "--rows",
            "1",
            "--trials",
            "6",
            "--warmup",
            "0",
        ],
        check=False,
    )
    assert_eq((result.returncode, result.stderr.decode()), (0, ""))
    report = loads(result.stdout)
    assert_eq(report["configuration"]["adapter_order"], "balanced")
    orders = [
        [
            trial["adapter"]
            for trial in report["trials"]
            if trial["round"] == round_number
        ]
        for round_number in range(1, 7)
    ]
    assert_eq(
        orders,
        [
            ["raw", "snekql", "sqlalchemy"],
            ["snekql", "sqlalchemy", "raw"],
            ["sqlalchemy", "raw", "snekql"],
            ["sqlalchemy", "snekql", "raw"],
            ["snekql", "raw", "sqlalchemy"],
            ["raw", "sqlalchemy", "snekql"],
        ],
    )
    assert_eq([trial["position"] for trial in report["trials"]], [1, 2, 3] * 6)


@test(
    [
        Param(["--rows", "1000000", "--payload-bytes", "8192"], name="seed-payload"),
        Param(
            ["--workload", "bulk", "--operations", "100000", "--batch-size", "10000"],
            name="write-growth",
        ),
        Param(
            [
                "--workload",
                "bulk",
                "--operations",
                "1",
                "--batch-size",
                "10000",
                "--payload-bytes",
                "8192",
            ],
            name="insert-payload",
        ),
    ],
    mark="slow",
)
async def comparison_rejects_combined_resource_budgets_before_native_setup(
    options: list[str],
) -> None:
    """Valid individual sizes cannot combine into unbounded setup, packets or writes."""
    result = await run_process(
        [sys.executable, "-m", "benchmarks.compare", "--backend", "mariadb", *options],
        env={**environ, "PATH": ""},
        check=False,
    )
    assert_eq(result.returncode, 2)
    assert_eq(result.stdout, b"")
    assert_in(b"payload budget", result.stderr)


@test(mark="slow")
async def comparison_identifies_lock_and_raw_driver_dependencies() -> None:
    """A report fingerprints the source lock and records transitive conversion drivers."""
    result = await run_process(
        [
            sys.executable,
            "-m",
            "benchmarks.compare",
            "--backend",
            "sqlite",
            "--adapter",
            "raw",
            "--operations",
            "1",
            "--rows",
            "1",
            "--trials",
            "1",
            "--warmup",
            "0",
        ],
        check=False,
    )
    assert_eq((result.returncode, result.stderr.decode()), (0, ""))
    environment = loads(result.stdout)["environment"]
    source = (await to_thread(Path(__file__).resolve)).parent.parent
    assert_eq(
        environment["lock_sha256"],
        sha256(await to_thread((source / "uv.lock").read_bytes)).hexdigest(),
    )
    assert_eq(environment["source_directory"], str(source))
    assert_eq(bool(environment["packages"]["pymysql"]), True)
    assert_eq(bool(environment["packages"]["pydantic-core"]), True)


@test(mark="slow")
async def comparison_startup_failure_retains_owned_diagnostics() -> None:
    """A failed subprocess reports its private evidence root without a success report."""

    async with TemporaryDirectory(prefix="sq-") as directory:
        base = AsyncPath(directory)
        binary = base / "bin"
        temporary = base / "tmp"
        await binary.mkdir()
        await temporary.mkdir()
        installer = binary / "mariadb-install-db"
        await installer.write_text(
            '#!/bin/sh\necho "controlled installer failure" >&2\nexit 7\n'
        )
        await installer.chmod(0o700)
        result = await run_process(
            [
                sys.executable,
                "-m",
                "benchmarks.compare",
                "--backend",
                "mariadb",
                "--adapter",
                "raw",
                "--operations",
                "1",
                "--rows",
                "1",
                "--trials",
                "1",
                "--warmup",
                "0",
            ],
            env={
                **environ,
                "TMPDIR": str(temporary),
                "PATH": f"{binary}{pathsep}{environ['PATH']}",
            },
            check=False,
        )
        assert_eq(result.returncode, 1)
        assert_eq(result.stdout, b"")
        assert_in(b"controlled installer failure", result.stderr)
        owners = [path async for path in temporary.iterdir()]
        assert_eq(len(owners), 1)
        assert_in(str(owners[0]).encode(), result.stderr)
        assert_eq(len([path async for path in owners[0].iterdir()]), 1)

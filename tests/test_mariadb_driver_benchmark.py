"""Driver benchmark reports describe verified real-server work (#478)."""

import sys
from json import loads

from anyio import run_process
from snektest import Param, assert_eq, assert_in, test


@test(mark="slow")
async def driver_comparison_rotates_and_verifies_point_reads() -> None:
    """Both real drivers return known rows and alternate their trial positions."""
    result = await run_process(
        [
            "uv",
            "run",
            "--locked",
            "--with",
            "asyncmy==0.2.16",
            "python",
            "-m",
            "benchmarks.mariadb_drivers",
            "--operations",
            "3",
            "--rows",
            "3",
            "--trials",
            "2",
            "--warmup",
            "1",
        ],
        check=False,
    )
    assert_eq(result.returncode, 0, msg=result.stderr.decode())
    report = loads(result.stdout)
    assert_eq(report["schema_version"], 1)
    assert_eq(
        [trial["driver"] for trial in report["trials"]],
        ["aiomysql", "asyncmy", "asyncmy", "aiomysql"],
    )
    for trial in report["trials"]:
        assert_eq(trial["observed"], {"rows": 3, "identity_sum": 6})
        assert_eq(trial["latency"]["count"], 3)
        assert_eq(trial["per_worker_operations"], [3])
        assert_eq(trial["session_policies"][0]["charset"], "utf8mb4")
    assert_in("asyncmy", report["environment"]["packages"])
    assert_in("pymysql", report["environment"]["packages"])


@test(
    [
        Param(("buffered", 9, 18), name="buffered"),
        Param(("stream", 9, 18), name="stream"),
        Param(("write", 3, 6), name="write"),
        Param(("bulk", 6, 21), name="bulk"),
    ],
    mark="slow",
)
async def driver_comparison_verifies_concurrent_workloads(
    case: tuple[str, int, int],
) -> None:
    """Two dedicated connections perform real scans and committed writes."""
    workload, rows, identities = case
    result = await run_process(
        [
            "uv",
            "run",
            "--locked",
            "--with",
            "asyncmy==0.2.16",
            "python",
            "-m",
            "benchmarks.mariadb_drivers",
            "--operations",
            "3",
            "--rows",
            "3",
            "--trials",
            "1",
            "--warmup",
            "1",
            "--workload",
            workload,
            "--workers",
            "2",
            "--batch-size",
            "2",
        ],
        check=False,
    )
    assert_eq(result.returncode, 0, msg=result.stderr.decode())
    report = loads(result.stdout)
    for trial in report["trials"]:
        assert_eq(trial["observed"], {"rows": rows, "identity_sum": identities})
        assert_eq(trial["latency"]["count"], 3)
        assert_eq(trial["per_worker_operations"], [2, 1])
        assert_eq(len(trial["session_policies"]), 2)
        assert_eq(
            trial["stream"],
            {"batches": 6, "max_batch_rows": 2} if workload == "stream" else None,
        )


@test(
    [
        Param("operations", name="operations"),
        Param("rows", name="rows"),
        Param("workers", name="workers"),
        Param("batch-size", name="batch"),
        Param("trials", name="trials"),
    ],
    mark="slow",
)
async def driver_comparison_rejects_invalid_sizes(option: str) -> None:
    """Invalid work sizes fail without emitting a successful report."""
    result = await run_process(
        [sys.executable, "-m", "benchmarks.mariadb_drivers", f"--{option}", "0"],
        check=False,
    )
    assert_eq(result.returncode, 2)
    assert_eq(result.stdout, b"")
    assert_in(b"must be between", result.stderr)


@test(mark="slow")
async def driver_comparison_rejects_corrupt_driver_results() -> None:
    """A real driver boundary returning wrong values cannot produce a report."""
    script = """
import runpy
import sys
from aiomysql import Cursor
original = Cursor.fetchall
async def corrupt(self):
    rows = await original(self)
    return [(1, "wrong@example.com", "x" * 32)] if rows else rows
Cursor.fetchall = corrupt
sys.argv = ["benchmark", "--operations", "1", "--rows", "1", "--trials", "1", "--warmup", "0"]
runpy.run_module("benchmarks.mariadb_drivers", run_name="__main__")
"""
    result = await run_process(
        ["uv", "run", "--locked", "--with", "asyncmy==0.2.16", "python", "-c", script],
        check=False,
    )
    assert_eq(result.returncode, 1)
    assert_eq(result.stdout, b"")
    assert_in(b"returned row differs", result.stderr)


@test(mark="slow")
async def driver_stream_never_uses_fetchall() -> None:
    """The unbuffered driver's public fetchall must not be used by streaming."""
    script = """
import runpy
import sys
from aiomysql import SSCursor
async def forbidden(self):
    raise AssertionError("stream buffered via fetchall")
SSCursor.fetchall = forbidden
sys.argv = ["benchmark", "--workload", "stream", "--operations", "1", "--rows", "3", "--trials", "1", "--warmup", "1", "--batch-size", "2"]
runpy.run_module("benchmarks.mariadb_drivers", run_name="__main__")
"""
    result = await run_process(
        ["uv", "run", "--locked", "--with", "asyncmy==0.2.16", "python", "-c", script],
        check=False,
    )
    assert_eq(result.returncode, 0, msg=result.stderr.decode())
    report = loads(result.stdout)
    assert_eq(report["trials"][0]["stream"], {"batches": 2, "max_batch_rows": 2})


@test(mark="slow")
async def driver_comparison_rejects_acknowledged_but_lost_writes() -> None:
    """A successful commit return without persistence is not measured as success."""
    script = """
import runpy
import sys
from aiomysql import Connection, Cursor
execute = Cursor.execute
commit = Connection.commit
writes = set()
async def track(self, sql, args=None):
    result = await execute(self, sql, args)
    if isinstance(sql, str) and sql.startswith("INSERT INTO bench_write"):
        writes.add(self.connection)
    return result
async def lose_write(self):
    if self in writes:
        writes.remove(self)
        await self.rollback()
    else:
        await commit(self)
Cursor.execute = track
Connection.commit = lose_write
sys.argv = ["benchmark", "--workload", "write", "--operations", "1", "--rows", "1", "--trials", "1", "--warmup", "0"]
runpy.run_module("benchmarks.mariadb_drivers", run_name="__main__")
"""
    result = await run_process(
        ["uv", "run", "--locked", "--with", "asyncmy==0.2.16", "python", "-c", script],
        check=False,
    )
    assert_eq(result.returncode, 1)
    assert_eq(result.stdout, b"")
    assert_in(b"returned cardinality differs", result.stderr)

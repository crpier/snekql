"""Direct aiomysql/asyncmy comparison on an owned MariaDB server (#478)."""

import asyncio
from argparse import ArgumentParser, Namespace
from collections.abc import AsyncIterator
from contextlib import AsyncExitStack, asynccontextmanager
from dataclasses import asdict
from datetime import UTC, datetime
from importlib import import_module
from importlib.metadata import version
from json import dumps
from time import perf_counter
from typing import Any

from benchmarks._comparison_mariadb import (
    _POLICY_QUERY,
    _SETTINGS,
    _verified_policy,
    seed,
)
from benchmarks._metrics import LatencyRecorder
from benchmarks.compare import _environment, _observe_loop
from snekql import mariadb
from snekql.testing.mariadb import temporary_mariadb_server


@asynccontextmanager
async def _connection(config: mariadb.Config, driver: str) -> AsyncIterator[Any]:
    connection = await import_module(driver).connect(
        host=config.host,
        port=config.port,
        user=config.user,
        password=config.password,
        db=config.database,
        charset="utf8mb4",
        autocommit=False,
        connect_timeout=30,
    )
    try:
        async with connection.cursor() as cursor:
            for statement in _SETTINGS:
                await cursor.execute(statement)
        yield connection
    finally:
        await connection.ensure_closed()


def _require(condition: bool, message: str) -> None:  # noqa: FBT001
    if not condition:
        raise ValueError(message)


def _check_rows(rows: Any, start: int) -> tuple[int, int]:
    count = identity_sum = 0
    for row in rows:
        identity = start + count
        _require(
            tuple(row) == (identity, f"user{identity}@example.com", "x" * 32),
            "returned row differs from expected identity/order/value",
        )
        count += 1
        identity_sum += identity
    return count, identity_sum


async def _operation(
    connection: Any, index: int, run: Namespace, cursor_class: Any
) -> tuple[int, int, int, int]:
    writing = run.workload in {"write", "bulk"}
    size = run.batch_size if run.workload == "bulk" else 1
    start = index * size + 1 if writing else index % run.rows + 1
    if writing:
        parameters = tuple(
            value
            for identity in range(start, start + size)
            for value in (identity, f"user{identity}@example.com", "x" * 32)
        )
        sql = "INSERT INTO bench_write VALUES " + ", ".join(  # noqa: S608
            ["(%s, %s, %s)"] * size
        )
        await connection.begin()
        try:
            async with connection.cursor() as cursor:
                await cursor.execute(sql, parameters)
            await connection.commit()
        except BaseException:
            await connection.rollback()
            raise
    streaming = run.workload == "stream"
    await connection.begin()
    try:
        async with connection.cursor(cursor_class) as cursor:
            if writing:
                await cursor.execute(
                    "SELECT id, email, payload FROM bench_write WHERE id >= %s AND id < %s ORDER BY id",
                    (start, start + size),
                )
                expected_count = size
            elif run.workload == "point-read":
                await cursor.execute(
                    "SELECT id, email, payload FROM bench_user WHERE id = %s", (start,)
                )
                expected_count = 1
            else:
                await cursor.execute(
                    "SELECT id, email, payload FROM bench_user ORDER BY id"
                )
                start = 1
                expected_count = run.rows
            count = identity_sum = batches = max_batch = 0
            if streaming:
                while batch := await cursor.fetchmany(run.batch_size):
                    batch_count, identities = _check_rows(batch, start + count)
                    count += batch_count
                    identity_sum += identities
                    batches += 1
                    max_batch = max(max_batch, batch_count)
                    _require(
                        batch_count <= run.batch_size,
                        "stream exceeded requested batch size",
                    )
                    await asyncio.sleep(0)
            else:
                count, identity_sum = _check_rows(await cursor.fetchall(), start)
            _require(
                count == expected_count,
                "returned cardinality differs from expected work",
            )
        await connection.commit()
    except BaseException:
        await connection.rollback()
        raise
    return count, identity_sum, batches, max_batch


async def _reset(connection: Any) -> None:
    async with connection.cursor() as cursor:
        await cursor.execute("DELETE FROM bench_write")
    await connection.commit()


async def _audit_writes(
    config: mariadb.Config, driver: str, batch_size: int, expected: tuple[int, ...]
) -> None:
    """Prove acknowledged commits are visible on another physical connection."""
    async with _connection(config, driver) as observer, observer.cursor() as cursor:
        await cursor.execute("SELECT id, email, payload FROM bench_write ORDER BY id")
        count = identities = 0
        while batch := await cursor.fetchmany(batch_size):
            size, subtotal = _check_rows(batch, count + 1)
            count += size
            identities += subtotal
        _require(
            (count, identities) == expected,
            "writes are not visible to an independent connection",
        )


async def _trial(config: mariadb.Config, driver: str, run: Namespace) -> dict[str, Any]:
    cursors = import_module(driver).cursors
    cursor_class = cursors.SSCursor if run.workload == "stream" else cursors.Cursor
    async with AsyncExitStack() as resources:
        connections = []
        policies = []
        for _ in range(run.workers):
            connection = await resources.enter_async_context(
                _connection(config, driver)
            )
            async with connection.cursor() as cursor:
                await cursor.execute(_POLICY_QUERY)
                policies.append(_verified_policy(await cursor.fetchone()))
            await connection.rollback()
            connections.append(connection)
        writing = run.workload in {"write", "bulk"}
        if writing:
            await _reset(connections[0])
        # Warm every dedicated connection; writes use disjoint identity ranges.
        for worker, connection in enumerate(connections):
            for index in range(run.warmup):
                await _operation(
                    connection, worker * run.warmup + index, run, cursor_class
                )
        if writing:
            await _reset(connections[0])
        latency = LatencyRecorder()
        totals = [0, 0, 0, 0]
        completed = [0] * run.workers

        async def worker(worker_index: int) -> None:
            for index in range(worker_index, run.operations, run.workers):
                operation_started = perf_counter()
                count, identities, batches, max_batch = await _operation(
                    connections[worker_index], index, run, cursor_class
                )
                latency.record(perf_counter() - operation_started)
                totals[0] += count
                totals[1] += identities
                totals[2] += batches
                totals[3] = max(totals[3], max_batch)
                completed[worker_index] += 1

        async with _observe_loop() as stalls:
            started = perf_counter()
            async with asyncio.TaskGroup() as tasks:
                for worker_index in range(run.workers):
                    tasks.create_task(worker(worker_index))
            elapsed = perf_counter() - started
        if writing:
            await _audit_writes(config, driver, run.batch_size, tuple(totals[:2]))
    return {
        "driver": driver,
        "session_policies": policies,
        "per_worker_operations": completed,
        "observed": {"rows": totals[0], "identity_sum": totals[1]},
        "stream": {"batches": totals[2], "max_batch_rows": totals[3]}
        if run.workload == "stream"
        else None,
        "latency": asdict(latency.summary()),
        "loop_stall": asdict(stalls.summary()) if stalls.samples else None,
        "elapsed_seconds": elapsed,
        "throughput_ops_s": run.operations / elapsed,
    }


async def _run(run: Namespace) -> dict[str, Any]:
    # Check both imports before starting a database; no silent driver omission.
    for driver in ("aiomysql", "asyncmy"):
        import_module(driver)
    environment = await _environment()
    packages = environment["packages"]
    if not isinstance(packages, dict):
        message = "environment packages must be a mapping"
        raise TypeError(message)
    packages.update({name: version(name) for name in ("asyncmy", "pymysql")})
    measurements = []
    async with temporary_mariadb_server(transports={"tcp"}) as server:
        config = server.config(pool_size=1)
        environment["mariadb"] = await seed(config, run.rows)
        environment["server_data_directory"] = str(server.data_directory)
        for trial in range(run.trials):
            drivers = (
                ("aiomysql", "asyncmy") if trial % 2 == 0 else ("asyncmy", "aiomysql")
            )
            for driver in drivers:
                measurement = await _trial(config, driver, run)
                measurement["round"] = trial + 1
                measurements.append(measurement)
    return {
        "schema_version": 1,
        "recorded_at": datetime.now(UTC).isoformat(),
        "configuration": vars(run),
        "environment": environment,
        "measurement": {
            "setup_included": False,
            "warmup_included": False,
            "correctness_checks_included": True,
            "heartbeat_interval_seconds": 0.005,
            "transaction": "explicit-begin-commit",
            "transport": "tcp-loopback",
            "connections": run.workers,
            "pool": "none; one dedicated connection per worker",
            "write_readback_included": True,
            "independent_commit_audit_included": False,
        },
        "trials": measurements,
    }


def main() -> None:
    """Emit one JSON document only after all trials succeed."""
    parser = ArgumentParser(description=__doc__)
    for name, default in (
        ("operations", 1000),
        ("rows", 1000),
        ("trials", 4),
        ("warmup", 100),
        ("workers", 1),
        ("batch-size", 256),
    ):
        parser.add_argument(f"--{name}", type=int, default=default)
    parser.add_argument(
        "--workload",
        choices=("point-read", "buffered", "stream", "write", "bulk"),
        default="point-read",
    )
    run = parser.parse_args()
    for name, lower, upper in (
        ("operations", 1, 100000),
        ("rows", 1, 1000000),
        ("trials", 1, 30),
        ("warmup", 0, 10000),
        ("workers", 1, 128),
        ("batch_size", 1, 10000),
    ):
        if not lower <= getattr(run, name) <= upper:
            parser.error(
                f"--{name.replace('_', '-')} must be between {lower} and {upper}"
            )
    print(dumps(asyncio.run(_run(run)), allow_nan=False))


if __name__ == "__main__":
    main()

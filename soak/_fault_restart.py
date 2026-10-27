"""A real, owned server restart with provably active and queued requests."""

import asyncio
from contextlib import AsyncExitStack
from dataclasses import asdict, replace
from pathlib import Path
from typing import Any

from benchmarks._artifacts import mariadb_artifacts
from snekql import mariadb
from snekql.testing.mariadb import TemporaryMariaDBServer, temporary_mariadb_server
from soak._service_evidence import emit
from soak._service_workload import require

CAPACITY = 4


async def _active_queries(server: TemporaryMariaDBServer) -> int:
    result = await server.run_sql(
        "SELECT COUNT(*) AS active FROM INFORMATION_SCHEMA.PROCESSLIST "
        "WHERE INFO LIKE '%snekql_fault_544%' AND ID <> CONNECTION_ID()"
    )
    return int(result.stdout.strip().splitlines()[-1])


async def restart_load() -> dict[str, Any]:  # noqa: PLR0915 -- keep the owned restart lifecycle together
    """Preserve durable writes; only explicit fresh read/write work follows restart."""
    async with mariadb_artifacts() as directory:  # noqa: SIM117 - keep artifact and restartable-server lifetimes distinct
        async with AsyncExitStack() as live_server:
            server = await live_server.enter_async_context(
                temporary_mariadb_server(
                    runtime_base_directory=directory,
                    transports={"tcp"},
                    data_directory=Path(directory) / "data",
                )
            )
            config = replace(
                server.config(pool_size=CAPACITY, acquire_timeout=2),
                health_check="checkout",
                operation_timeout=10,
            )
            async with await mariadb.Database.initialize(config) as database:
                async with database.transaction() as setup:
                    version = await setup.fetch_one(
                        mariadb.raw("SELECT VERSION() AS version")
                    )
                    emit(
                        "engine",
                        backend="mariadb",
                        version=version["version"],
                        pool_size=CAPACITY,
                        transaction_timeout=10,
                        acquire_timeout=2,
                        health_check="checkout",
                    )
                    await setup.execute(
                        mariadb.raw(
                            "CREATE TABLE fault_restart (id BIGINT PRIMARY KEY) ENGINE=InnoDB"
                        )
                    )
                    await setup.execute(
                        mariadb.raw("INSERT INTO fault_restart VALUES (1),(2),(3),(4)")
                    )
                active_errors: list[str | None] = []
                queued_errors: list[str] = []

                async def request(*, active: bool) -> None:
                    try:
                        async with database.transaction() as transaction:
                            await transaction.fetch_one(
                                mariadb.raw(
                                    "SELECT SLEEP(30) AS interrupted /* snekql_fault_544 */"
                                    if active
                                    else "SELECT 42 AS queued"
                                )
                            )
                    except mariadb.DatabaseRuntimeError as error:
                        if active:
                            active_errors.append(
                                error.failure.category if error.failure else None
                            )
                        else:
                            queued_errors.append(type(error).__name__)
                        return
                    message = "interrupted request unexpectedly succeeded"
                    raise RuntimeError(message)

                async with asyncio.TaskGroup() as group:
                    active_tasks = [
                        group.create_task(request(active=True)) for _ in range(CAPACITY)
                    ]
                    async with asyncio.timeout(10):
                        while await _active_queries(server) != CAPACITY:
                            require(
                                not any(task.done() for task in active_tasks),
                                "active request ended before fault",
                            )
                            await asyncio.sleep(0.01)
                        queued_tasks = [
                            group.create_task(request(active=False))
                            for _ in range(CAPACITY)
                        ]
                        while database.pool_stats().waiters != CAPACITY:
                            require(
                                not any(task.done() for task in queued_tasks),
                                "queued request ended before fault",
                            )
                            await asyncio.sleep(0.001)
                        emit(
                            "fault",
                            scenario="restart-load",
                            active_server_queries=CAPACITY,
                            pool=asdict(database.pool_stats()),
                        )
                        await live_server.aclose()
                require(
                    active_errors == ["connection_loss"] * CAPACITY,
                    "active queries did not report connection loss",
                )
                require(
                    len(queued_errors) == CAPACITY, "queued requests were not settled"
                )
                drained = database.pool_stats()
                require(
                    drained.occupied == 0 and drained.waiters == 0,
                    "restart did not drain pool",
                )
                async with temporary_mariadb_server(
                    runtime_base_directory=directory,
                    transports={"tcp"},
                    data_directory=Path(directory) / "data",
                    port=config.port,
                ):
                    async with database.transaction() as observer:
                        rows = await observer.fetch_all(
                            mariadb.raw("SELECT id FROM fault_restart ORDER BY id")
                        )
                    require(
                        rows == [{"id": 1}, {"id": 2}, {"id": 3}, {"id": 4}],
                        "acknowledged rows changed",
                    )
                    async with database.transaction() as fresh:
                        await fresh.execute(
                            mariadb.raw("INSERT INTO fault_restart VALUES (5)")
                        )
                    async with database.transaction() as observer:
                        recovered = await observer.fetch_all(
                            mariadb.raw("SELECT id FROM fault_restart ORDER BY id")
                        )
                    require(
                        recovered
                        == [{"id": 1}, {"id": 2}, {"id": 3}, {"id": 4}, {"id": 5}],
                        "fresh write did not persist",
                    )
            closed = database.pool_stats()
            require(closed.state == "closed", "restart pool did not close")
    return {
        "active_failure_categories": active_errors,
        "queued_errors": queued_errors,
        "preserved_ids": [row["id"] for row in rows],
        "recovered_ids": [row["id"] for row in recovered],
        "drained_pool": asdict(drained),
        "closed_pool": asdict(closed),
        "recovery_verified": True,
    }

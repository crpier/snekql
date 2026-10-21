"""Cancellation probes using public Transactions and an owned server observer."""

import asyncio
from typing import Any

from snekql import mariadb


async def _wait_for_sleep(observer: mariadb.Database, identity: object) -> None:
    async with asyncio.timeout(10), observer.transaction(timeout=10) as transaction:
        while True:
            rows = await transaction.fetch_all(
                mariadb.raw(
                    "SELECT STATE AS state FROM information_schema.PROCESSLIST WHERE ID = %s",
                    params=(identity,),
                )
            )
            if rows and rows[0]["state"] == "User sleep":
                return
            await asyncio.sleep(0.01)


async def probe(  # noqa: C901, PLR0915 - keep cancellation and lease ownership in one sequence
    config: mariadb.Config, driver: str, scenario: str
) -> dict[str, Any]:
    table = f"public_cancel_{driver}"  # Fixed harness names only.
    async with (
        asyncio.timeout(30),
        await mariadb.Database.initialize(config) as database,
        await mariadb.Database.initialize(config) as observer,
    ):
        async with database.transaction() as setup:
            await setup.execute(
                mariadb.raw(f"CREATE TABLE {table} (id INT PRIMARY KEY) ENGINE=InnoDB")
            )
        deadline = scenario.startswith("deadline-")
        target_phase = scenario.split("-", 1)[1]
        transaction = database.transaction(timeout=1 if deadline else 15)
        started = asyncio.Event()
        before: object = None
        phase = "setup"
        first_identity = None
        unsafe_work_blocked = False

        async def work() -> None:
            nonlocal before, phase, first_identity, unsafe_work_blocked
            async with transaction:
                row = await transaction.fetch_one(
                    mariadb.raw("SELECT CONNECTION_ID() AS id")
                )
                before = row["id"]
                await transaction.execute(
                    mariadb.raw(f"INSERT INTO {table} VALUES (1)")  # noqa: S608 - fixed driver names
                )
                try:
                    if target_phase == "query":
                        phase = "query"
                        started.set()
                        await transaction.fetch_one(
                            mariadb.raw("SELECT SLEEP(5) AS value")
                        )
                    else:
                        async with transaction.fetch_chunks(
                            mariadb.raw(
                                "SELECT seq, REPEAT('x', 65536) AS payload, IF(seq = 2, SLEEP(5), 0) AS pause "
                                "FROM seq_1_to_2"
                            ),
                            size=1,
                        ) as chunks:
                            first = (await anext(chunks))[0]
                            if first != {"seq": 1, "payload": "x" * 65536, "pause": 0}:
                                message = "Public stream did not deliver its expected first row"
                                raise RuntimeError(message)
                            first_identity = first["seq"]
                            phase = target_phase
                            started.set()
                            if phase == "fetch":
                                await anext(chunks)
                except (
                    asyncio.CancelledError,
                    mariadb.DatabaseOperationTimeoutError,
                    mariadb.ExecutionError,
                ):
                    try:
                        await transaction.fetch_one(
                            mariadb.raw("SELECT 42 AS forbidden")
                        )
                    except mariadb.DatabaseRuntimeError as error:
                        unsafe_work_blocked = (
                            type(error) is mariadb.DatabaseRuntimeError
                        )
                    raise

        task = asyncio.create_task(work())
        error_type = None
        timeout_evidence = None
        try:
            await started.wait()
            await _wait_for_sleep(observer, before)
            if task.done():
                message = "Public operation finished before cancellation barrier"
                raise RuntimeError(message)
            if not deadline:
                task.cancel()
            try:
                await task
            except (
                asyncio.CancelledError,
                mariadb.DatabaseOperationTimeoutError,
                mariadb.ExecutionError,
            ) as error:
                error_type = type(error).__name__
                context: BaseException | None = error
                while context is not None:
                    if isinstance(context, mariadb.DatabaseOperationTimeoutError):
                        timeout_evidence = "direct" if context is error else "context"
                        break
                    context = context.__context__
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        recovery = database.transaction(timeout=10)
        async with recovery:
            after = await recovery.fetch_one(
                mariadb.raw("SELECT CONNECTION_ID() AS id")
            )
            row = await recovery.fetch_one(
                mariadb.raw(f"SELECT COUNT(*) AS n FROM {table}")  # noqa: S608 - fixed driver names
            )
            await recovery.execute(mariadb.raw(f"INSERT INTO {table} VALUES (1)"))  # noqa: S608 - fixed driver names
        async with database.transaction() as verification:
            persisted = await verification.fetch_one(
                mariadb.raw(f"SELECT COUNT(*) AS n FROM {table}")  # noqa: S608 - fixed driver names
            )
        stats = database.pool_stats()
        result = {
            "error_type": error_type,
            "timeout_evidence": timeout_evidence,
            "unsafe_work_blocked": unsafe_work_blocked,
            "phase": phase,
            "first_identity": first_identity,
            "same_connection": before == after["id"],
            "visible_writes": row["n"],
            "recovered_writes": persisted["n"],
            "commit_outcome": transaction.commit_outcome,
            "recovery_outcome": recovery.commit_outcome,
            "occupied": stats.occupied,
            "waiters": stats.waiters,
            "discarded_connections": stats.discarded_connections,
        }
    result["pool_state_after_close"] = database.pool_stats().state
    return result

"""Real, owned fault drills from a source checkout; tracking issue #544."""

import asyncio
from argparse import ArgumentParser
from dataclasses import asdict, replace
from typing import Any

from snekql import mariadb
from snekql.testing.mariadb import temporary_mariadb_server
from soak._fault_proxy import Proxy, fault_proxy
from soak._fault_restart import restart_load
from soak._fault_storage import storage_full
from soak._service_evidence import emit, environment
from soak._service_workload import require

STREAM_BATCH = 4
STREAM_ROWS = 4096


async def stream_cut(database: mariadb.Database, proxy: Proxy) -> dict[str, Any]:
    """Validate an ordered prefix, interrupt the actual socket, never replay it."""
    delivered = 0
    failure: mariadb.ExecutionError | None = None
    transaction = database.transaction()
    async with transaction:
        try:
            async with transaction.fetch_chunks(
                mariadb.raw(
                    "SELECT seq AS id, REPEAT('x', 4096) AS payload "
                    "FROM seq_1_to_4096 ORDER BY seq"
                ),
                size=4,
            ) as stream:
                batch = await anext(stream)
                require([row["id"] for row in batch] == [1, 2, 3, 4], "bad first batch")
                proxy.cut()
                emit(
                    "fault",
                    scenario="stream-cut",
                    transport_cut=True,
                    first_batch_ids=[row["id"] for row in batch],
                    server_bytes_forwarded=proxy.server_bytes_forwarded,
                )
                require(
                    proxy.server_bytes_forwarded < 4096 * 4096,
                    "stream was fully forwarded before fault injection",
                )
                while True:
                    for row in batch:
                        require(
                            row == {"id": delivered + 1, "payload": "x" * 4096},
                            "stream prefix was corrupted or replayed",
                        )
                        delivered += 1
                    batch = await anext(stream)
        except mariadb.ExecutionError as error:
            failure = error
        require(failure is not None, "cut did not cause a native stream error")
        classification = failure.failure
        if classification is None:
            message = "missing native failure classification"
            raise RuntimeError(message)
        require(
            classification.category == "connection_loss", "unexpected stream failure"
        )
        terminal = False
        try:
            await transaction.fetch_one(mariadb.raw("SELECT 99 AS unexpected"))
        except mariadb.DatabaseRuntimeError:
            terminal = True
        require(terminal, "failed transaction was reusable")
    require(
        STREAM_BATCH <= delivered < STREAM_ROWS,
        "fault did not interrupt a partial stream",
    )
    return {
        "delivered_rows": delivered,
        "failure_category": classification.category,
        "terminal_transaction": terminal,
    }


async def commit_blackhole(database: mariadb.Database, proxy: Proxy) -> dict[str, Any]:
    """Lose a real COMMIT response, then reconcile once by the durable operation key."""
    async with database.transaction() as setup:
        await setup.execute(
            mariadb.raw(
                "CREATE TABLE fault_commit (operation_id BIGINT PRIMARY KEY, value BIGINT NOT NULL) ENGINE=InnoDB"
            )
        )
    transaction = database.transaction(timeout=1)
    timed_out = False
    try:
        async with transaction:
            await transaction.execute(
                mariadb.raw("INSERT INTO fault_commit VALUES (544, 7)")
            )
            proxy.watch_commits = True
            proxy.blackhole_commit = True
    except mariadb.DatabaseOperationTimeoutError:
        timed_out = True
    proxy.watch_commits = False
    require(timed_out, "blackholed COMMIT did not hit its deadline")
    require(
        proxy.reply_held.is_set() and proxy.server_reply == "ok",
        "server OK was not withheld",
    )
    require(proxy.commit_requests_forwarded == 1, "COMMIT was missing or replayed")
    require(
        transaction.commit_outcome == "unknown", "unacknowledged commit was not unknown"
    )
    emit(
        "fault",
        scenario="commit-blackhole",
        commit_requests_forwarded=proxy.commit_requests_forwarded,
        reply_held=proxy.reply_held.is_set(),
        server_reply=proxy.server_reply,
    )
    async with database.transaction() as observer:
        rows = await observer.fetch_all(
            mariadb.raw(
                "SELECT operation_id, value FROM fault_commit ORDER BY operation_id"
            )
        )
    require(
        rows == [{"operation_id": 544, "value": 7}],
        "durable operation did not reconcile",
    )
    return {
        "error_type": "DatabaseOperationTimeoutError",
        "commit_outcome": transaction.commit_outcome,
        "reconciled_rows": rows,
        "commit_requests_forwarded": proxy.commit_requests_forwarded,
    }


async def run(scenario: str) -> None:
    await environment({"scenario": scenario})
    if scenario in ("restart-load", "sqlite-full"):
        report = await (
            restart_load() if scenario == "restart-load" else storage_full()
        )
        emit("summary", status="passed", scenario=scenario, **report)
        return
    async with temporary_mariadb_server(transports={"tcp"}) as server:
        config = server.config(pool_size=1, acquire_timeout=5)
        require(config.host is not None, "missing owned TCP host")
        async with fault_proxy(config.host, config.port) as (proxy, port):
            async with await mariadb.Database.initialize(
                replace(config, port=port, operation_timeout=5)
            ) as database:
                async with database.transaction() as observer:
                    version = await observer.fetch_one(
                        mariadb.raw("SELECT VERSION() AS version")
                    )
                emit(
                    "engine",
                    backend="mariadb",
                    version=version["version"],
                    pool_size=1,
                    transaction_timeout=1 if scenario == "commit-blackhole" else 5,
                    acquire_timeout=5,
                    transport="owned-plaintext-loopback-proxy",
                )
                if scenario == "stream-cut":
                    report = await stream_cut(database, proxy)
                else:
                    report = await commit_blackhole(database, proxy)
                drained = database.pool_stats()
                require(
                    drained.occupied == 0 and drained.waiters == 0, "pool not drained"
                )
                require(
                    drained.discarded_connections == 1, "unsafe lease not discarded"
                )
                async with database.transaction() as recovered:
                    row = await recovered.fetch_one(mariadb.raw("SELECT 42 AS alive"))
                    require(row == {"alive": 42}, "fresh work failed after cut")
            closed = database.pool_stats()
            require(closed.state == "closed", "pool did not close")
    emit(
        "summary",
        status="passed",
        scenario=scenario,
        recovery_verified=True,
        drained_pool=asdict(drained),
        closed_pool=asdict(closed),
        **report,
    )


def main() -> None:
    parser = ArgumentParser(description=__doc__)
    parser.add_argument(
        "--scenario",
        required=True,
        choices=("stream-cut", "commit-blackhole", "restart-load", "sqlite-full"),
    )
    args = parser.parse_args()
    try:
        asyncio.run(run(args.scenario))
    except Exception as error:
        emit(
            "failure",
            status="failed",
            scenario=args.scenario,
            error_type=type(error).__name__,
        )
        raise


if __name__ == "__main__":
    main()

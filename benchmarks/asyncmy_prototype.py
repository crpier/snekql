"""Observe an isolated asyncmy adapter through public snekql transactions."""

import argparse
import asyncio
import gc
import json
import warnings
from dataclasses import fields, replace
from typing import Any

from benchmarks._asyncmy_adapter import PrototypeConfig
from benchmarks._asyncmy_commit import _CommitRelay
from benchmarks._asyncmy_constraints import probe as constraint_probe
from snekql import mariadb
from snekql.errors import DatabaseRuntimeError
from snekql.testing.mariadb import temporary_mariadb_server


async def _stream(config: mariadb.Config) -> dict[str, Any]:
    async with await mariadb.Database.initialize(config) as database:
        transaction = database.transaction()
        async with transaction:
            before = await transaction.fetch_one(
                mariadb.raw("SELECT CONNECTION_ID() AS id")
            )
            async with transaction.fetch_chunks(
                mariadb.raw(
                    "SELECT seq, REPEAT('x', 1024) AS payload FROM seq_1_to_4096 ORDER BY seq"
                ),
                size=1,
            ) as stream:
                first = await anext(stream)
            after = await transaction.fetch_one(
                mariadb.raw("SELECT CONNECTION_ID() AS id, 42 AS answer")
            )
        return {
            "first_identity": first[0]["seq"],
            "same_connection": before["id"] == after["id"],
            "answer": after["answer"],
            "commit_outcome": transaction.commit_outcome,
        }


async def _extra_results(config: mariadb.Config) -> dict[str, Any]:
    async with await mariadb.Database.initialize(config) as database:
        transaction = database.transaction()
        rejected = False
        async with transaction:
            before = await transaction.fetch_one(
                mariadb.raw("SELECT CONNECTION_ID() AS id")
            )
            try:
                async with transaction.fetch_chunks(
                    mariadb.raw(
                        "SELECT seq FROM seq_1_to_4096; SELECT seq FROM seq_1_to_4096"
                    ),
                    size=1,
                ) as stream:
                    await anext(stream)
            except mariadb.RawResultShapeError:
                rejected = True
        async with database.transaction() as recovery:
            after = await recovery.fetch_one(
                mariadb.raw("SELECT CONNECTION_ID() AS id, 42 AS answer")
            )
        return {
            "rejected": rejected,
            "same_connection": before["id"] == after["id"],
            "answer": after["answer"],
            "commit_outcome": transaction.commit_outcome,
        }


async def _commit(config: mariadb.Config, scenario: str, driver: str) -> dict[str, Any]:
    relay = _CommitRelay(config.host, config.port, scenario)
    server = await asyncio.start_server(relay.handle, "127.0.0.1", 0)
    table = f"prototype_commit_{driver}"  # Fixed driver names, never user SQL.
    try:
        async with (
            asyncio.timeout(30),
            await mariadb.Database.initialize(config) as observer,
        ):
            async with observer.transaction() as setup:
                await setup.execute(
                    mariadb.raw(
                        f"CREATE TABLE {table} (id INT PRIMARY KEY) ENGINE=InnoDB"
                    )
                )
            proxy_config = replace(config, port=server.sockets[0].getsockname()[1])
            async with await mariadb.Database.initialize(proxy_config) as database:
                transaction = database.transaction()
                failure = None
                try:
                    async with transaction:
                        await transaction.execute(
                            mariadb.raw(f"INSERT INTO {table} VALUES (1)")  # noqa: S608 - fixed driver names
                        )
                except DatabaseRuntimeError as error:
                    failure = error.failure
            if relay.failure is not None:
                raise relay.failure
            async with observer.transaction() as verification:
                row = await verification.fetch_one(
                    mariadb.raw(f"SELECT COUNT(*) AS n FROM {table}")  # noqa: S608 - fixed driver names
                )
            return {
                "commit_outcome": transaction.commit_outcome,
                "failure_category": None if failure is None else failure.category,
                "failure_code": None if failure is None else failure.code,
                "visible_writes": row["n"],
                "server_ok_seen": relay.server_ok_seen,
                "commit_seen": relay.commit_seen,
                "commit_forwarded": relay.commit_forwarded,
            }
    finally:
        server.close()
        await server.wait_closed()
        await relay.close()


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--scenario",
        choices=(
            "constraint-unique",
            "constraint-no-savepoint",
            "constraint-lock-timeout",
            "constraint-not-null",
            "constraint-check",
            "constraint-foreign-insert",
            "constraint-foreign-delete",
            "stream",
            "extra-results",
            "commit-drop-ack",
            "commit-control",
            "commit-drop-before",
        ),
        required=True,
    )
    args = parser.parse_args()
    results = []
    async with temporary_mariadb_server(transports={"tcp"}) as server:
        baseline = server.config(pool_size=1)
        prototype = PrototypeConfig(
            **{field.name: getattr(baseline, field.name) for field in fields(baseline)}
        )
        for name, config in (("aiomysql", baseline), ("asyncmy", prototype)):
            with warnings.catch_warnings(record=True) as caught:
                warnings.simplefilter("always")
                if args.scenario.startswith("constraint-"):
                    result = await constraint_probe(config, name, args.scenario)
                elif args.scenario.startswith("commit-"):
                    result = await _commit(config, args.scenario, name)
                else:
                    result = await (
                        _extra_results(config)
                        if args.scenario == "extra-results"
                        else _stream(config)
                    )
                gc.collect()
            results.append(
                {
                    "driver": name,
                    **result,
                    "warnings": [str(item.message) for item in caught],
                }
            )
    print(
        json.dumps({"schema_version": 1, "scenario": args.scenario, "results": results})
    )


if __name__ == "__main__":
    asyncio.run(main())

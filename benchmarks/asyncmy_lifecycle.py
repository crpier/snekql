"""Isolated real-driver lifecycle probes; not a supported snekql backend."""

import argparse
import asyncio
import gc
import json
import tracemalloc
import warnings
from importlib import import_module
from importlib.metadata import version
from typing import Any, cast

from pymysql.constants import CLIENT

from benchmarks._asyncmy_cancellation import probe as cancellation_probe
from snekql.testing.mariadb import temporary_mariadb_server

_ANSWER = 42


async def _identity(connection: Any) -> int:
    async with connection.cursor() as cursor:
        await cursor.execute("SELECT CONNECTION_ID()")
        return cast("int", (await cursor.fetchone())[0])


async def _probe(
    driver: Any, options: dict[str, object], scenario: str
) -> dict[str, object]:
    connection = await driver.connect(**options)
    phase = "identity"
    try:
        async with asyncio.timeout(30):
            before = await _identity(connection)
            cursor = await connection.cursor(
                import_module(f"{driver.__name__}.cursors").SSCursor
            )
            try:
                phase = "execute-stream"
                sql = "SELECT seq, REPEAT('x', 1024) FROM seq_1_to_4096 ORDER BY seq"
                if scenario == "multiple-results":
                    sql += "; " + sql + "; SELECT 99"
                await cursor.execute(sql)
                phase = "fetch-first"
                first = await cursor.fetchone()
            finally:
                phase = "close-stream"
                tracemalloc.start()
                try:
                    await cursor.close()
                    _, cleanup_peak = tracemalloc.get_traced_memory()
                finally:
                    tracemalloc.stop()
            phase = "reuse"
            async with connection.cursor() as cursor:
                await cursor.execute("SELECT CONNECTION_ID(), 42")
                after, answer = await cursor.fetchone()
            if first != (1, "x" * 1024) or before != after or answer != _ANSWER:
                message = "Abandoned stream did not preserve connection reuse"
                raise RuntimeError(message)
            return {
                "status": "reused",
                "driver": driver.__name__,
                "version": version(driver.__name__),
                "first_identity": first[0],
                "same_connection": before == after,
                "answer": answer,
                "server": connection.get_server_info(),
                "cleanup_peak_python_bytes": cleanup_peak,
            }
    except driver.Error as error:
        return {
            "driver": driver.__name__,
            "version": version(driver.__name__),
            "status": "driver-error",
            "phase": phase,
            "error_type": type(error).__name__,
            "error": str(error),
            "server": connection.get_server_info(),
        }
    finally:
        connection.close()


async def _pool_probe(
    driver: Any, options: dict[str, object], *, discard: bool
) -> dict[str, object]:
    pool = await driver.create_pool(minsize=1, maxsize=1, **options)
    try:
        async with asyncio.timeout(30):
            async with pool.acquire() as connection:
                before = await _identity(connection)
                server_version = connection.get_server_info()
                cursor = await connection.cursor(
                    import_module(f"{driver.__name__}.cursors").SSCursor
                )
                sql = "SELECT seq, REPEAT('x', 1024) FROM seq_1_to_4096 ORDER BY seq"
                if discard:
                    sql += "; " + sql + "; SELECT 99"
                try:
                    await cursor.execute(sql)
                    first = await cursor.fetchone()
                    if not discard:
                        await cursor.close()
                except BaseException:
                    connection.close()
                    raise
                finally:
                    if discard:
                        # Do not drain pending results from an unsafe connection.
                        connection.close()
            async with pool.acquire() as connection, connection.cursor() as cursor:
                await cursor.execute("SELECT CONNECTION_ID(), 42")
                after, answer = await cursor.fetchone()
            if (
                first != (1, "x" * 1024)
                or (before == after) == discard
                or answer != _ANSWER
            ):
                message = "Pool did not preserve the expected connection lifecycle"
                raise RuntimeError(message)
            return {
                "driver": driver.__name__,
                "version": version(driver.__name__),
                "status": "replaced" if discard else "reused",
                "same_connection": before == after,
                "answer": answer,
                "server": server_version,
            }
    finally:
        pool.close()
        await pool.wait_closed()


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--scenario",
        choices=(
            "abandoned-stream",
            "multiple-results",
            "pool-reuse",
            "pool-discard-multiple",
            "cancel-query",
            "cancel-fetch",
            "cancel-close",
        ),
        required=True,
    )
    args = parser.parse_args()
    async with temporary_mariadb_server(transports={"tcp"}) as server:
        config = server.config()
        options: dict[str, object] = {
            "host": config.host,
            "port": config.port,
            "user": config.user,
            "password": config.password,
            "db": config.database,
            "charset": "utf8mb4",
            "autocommit": True,
            "connect_timeout": 10,
            "client_flag": CLIENT.MULTI_STATEMENTS,
        }
        results = []
        for name in ("aiomysql", "asyncmy"):
            with warnings.catch_warnings(record=True) as caught:
                warnings.simplefilter("always")
                driver = import_module(name)
                if args.scenario.startswith("cancel-"):
                    result = await cancellation_probe(driver, options, args.scenario)
                elif args.scenario.startswith("pool-"):
                    result = await _pool_probe(
                        driver,
                        options,
                        discard=args.scenario == "pool-discard-multiple",
                    )
                else:
                    result = await _probe(driver, options, args.scenario)
                gc.collect()  # Include deferred driver finalizer warnings in the report.
            result["warnings"] = [str(item.message) for item in caught]
            results.append(result)
    print(
        json.dumps({"schema_version": 1, "scenario": args.scenario, "results": results})
    )


if __name__ == "__main__":
    asyncio.run(main())

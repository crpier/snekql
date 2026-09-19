"""Controlled concurrent schedules, not timing-based race guesses."""

import asyncio
import sys
from dataclasses import replace
from importlib.metadata import version
from json import dumps
from pathlib import Path
from platform import python_version
from typing import Any

from research.concurrency.cases import configurations
from research.concurrency.observations import assess
from research.concurrency.orm import stale_objects
from research.concurrency.runtime import Runtime, runtime
from research.concurrency.schedules import held_lock, overlap
from research.concurrency.sqlalchemy_models import models


async def detached(adapter: Runtime, strategy: str) -> dict[str, Any]:
    await adapter.reset()
    ready = asyncio.Barrier(2)
    first_done = asyncio.Event()
    callers: list[dict[str, Any]] = [{}, {}]
    events: list[str] = []

    async def caller(index: int) -> None:
        observed = await adapter.fresh()
        callers[index]["read"] = observed
        events.append(f"{index}:read_committed")
        await ready.wait()
        if index:
            await first_done.wait()
        async with adapter.transaction() as transaction:
            callers[index]["rowcount"] = await adapter.write(
                transaction, strategy, observed
            )
        callers[index]["outcome"] = (
            "conflict"
            if strategy in ("cas", "atomic") and callers[index]["rowcount"] == 0
            else "committed"
        )
        events.append(f"{index}:write_committed")
        if not index:
            first_done.set()

    async with asyncio.timeout(15), asyncio.TaskGroup() as tasks:
        tasks.create_task(caller(0))
        tasks.create_task(caller(1))
    final = await adapter.fresh()
    return {
        "callers": callers,
        "final": final,
        "events": events,
        "oracle": assess(callers, final),
    }


async def observe(
    backend: str,
    library: str,
    sqlite_begin: str = "explicit",
    *,
    snapshot_isolation: bool = True,
) -> dict[str, Any]:
    """Collect a configuration through real transactions and independent readback."""
    async with runtime(
        backend, library, sqlite_begin, snapshot_isolation=snapshot_isolation
    ) as adapter:
        recorded = {
            "scenarios": {
                "detached_stale": await detached(adapter, "stale"),
                "detached_atomic": await detached(adapter, "atomic"),
                "detached_cas": await detached(adapter, "cas"),
                "overlap_stale": await overlap(adapter, "stale"),
                "overlap_cas": await overlap(adapter, "cas"),
                "overlap_retry": await overlap(adapter, "cas", retry=True),
                "lock_retry": await held_lock(adapter),
            }
        }

        await adapter.reset()
        snapshot = await adapter.fresh()
        async with adapter.transaction() as transaction:
            recorded["noop_rowcount"] = await adapter.write(
                transaction, "noop", snapshot
            )
        if library == "sqlalchemy":
            recorded["scenarios"]["orm_unversioned"] = await stale_objects(adapter)
            versioned_adapter = replace(adapter, entry=models(versioned=True))
            recorded["scenarios"]["orm_versioned"] = await stale_objects(
                versioned_adapter
            )
            recorded["scenarios"]["versioned_direct_update"] = await detached(
                versioned_adapter, "stale"
            )
        async with adapter.transaction() as first, adapter.transaction() as second:
            await adapter.read(first)
            await adapter.read(second)
            recorded["controls"] = [
                await adapter.controls(first),
                await adapter.controls(second),
            ]
        recorded["configuration"] = {
            "backend": backend,
            "library": library,
            "sqlite_begin": sqlite_begin if backend == "sqlite" else None,
            "snapshot_isolation": snapshot_isolation if backend == "mariadb" else None,
        }
        async with adapter.engine.connect() as connection:
            if backend == "sqlite":
                recorded["installed_ddl"] = (
                    await connection.exec_driver_sql(
                        "SELECT sql FROM sqlite_master WHERE name='counter'"
                    )
                ).scalar_one()
            else:
                recorded["installed_ddl"] = (
                    await connection.exec_driver_sql("SHOW CREATE TABLE counter")
                ).one()[1]
        recorded["statements"] = adapter.statements
        return recorded


async def main() -> None:
    """Reproduce all controlled configurations and retain evidence beside the runner."""
    evidence: dict[str, Any] = {
        "python": python_version(),
        "context_aware_warnings": sys.flags.context_aware_warnings,
        "versions": {
            name: version(name)
            for name in (
                "snekql",
                "sqlalchemy",
                "pydantic",
                "aiosqlite",
                "aiomysql",
                "PyMySQL",
                "greenlet",
            )
        },
        "runs": {name: await observe(**options) for name, options in configurations()},
    }
    directory = Path(__file__).parent
    await asyncio.to_thread(
        (directory / "results.json").write_text, dumps(evidence, indent=2) + "\n"
    )
    for name, recorded in evidence["runs"].items():
        ddl = (
            "\n".join(
                line.rstrip()
                for line in recorded["installed_ddl"].strip().rstrip(";").splitlines()
            )
            + ";\n"
        )
        await asyncio.to_thread(
            (directory / f"{name.replace('/', '-')}.sql").write_text, ddl
        )


if __name__ == "__main__":
    asyncio.run(main())

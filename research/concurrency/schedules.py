"""Controlled overlap keeps both read transactions open until A commits."""

import asyncio
from typing import Any

from sqlalchemy.exc import DBAPIError

from research.concurrency.observations import assess, contention
from research.concurrency.runtime import Runtime
from snekql.errors import ExecutionError


async def retry_fresh(adapter: Runtime) -> dict[str, Any]:
    """One bounded retry of this pure read/CAS unit; no external side effects."""
    attempt: dict[str, Any] = {}
    stage = "read"
    try:
        async with adapter.transaction() as transaction:
            observed = await adapter.read(transaction)
            attempt["read"] = observed
            stage = "execute"
            attempt["rowcount"] = await adapter.write(transaction, "cas", observed)
            stage = "commit"
        attempt["outcome"] = "committed" if attempt["rowcount"] == 1 else "conflict"
    except (ExecutionError, DBAPIError) as error:
        attempt.update(contention(error, stage))
    return attempt


async def overlap(
    adapter: Runtime, strategy: str, *, retry: bool = False
) -> dict[str, Any]:
    await adapter.reset()
    ready = asyncio.Barrier(2)
    first_done = asyncio.Event()
    callers: list[dict[str, Any]] = [{}, {}]
    events: list[str] = []

    async def caller(index: int) -> None:
        attempt: dict[str, Any] = {}
        stage = "read"
        try:
            async with adapter.transaction() as transaction:
                observed = await adapter.read(transaction)
                attempt["read"] = observed
                events.append(f"{index}:read_open")
                await ready.wait()
                if index:
                    await first_done.wait()
                stage = "execute"
                attempt["rowcount"] = await adapter.write(
                    transaction, strategy, observed
                )
                stage = "commit"
            attempt["outcome"] = (
                "conflict"
                if strategy == "cas" and attempt["rowcount"] == 0
                else "committed"
            )
        except (ExecutionError, DBAPIError) as error:
            attempt.update(contention(error, stage))
        callers[index] = {"outcome": attempt["outcome"], "attempts": [attempt]}
        events.append(f"{index}:transaction_closed:{attempt['outcome']}")
        if not index:
            first_done.set()
        if retry and attempt["outcome"] in ("conflict", "contention"):
            fresh_attempt = await retry_fresh(adapter)
            callers[index]["attempts"].append(fresh_attempt)
            callers[index]["outcome"] = fresh_attempt["outcome"]
            events.append(f"{index}:retry_closed:{fresh_attempt['outcome']}")

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


async def held_lock(adapter: Runtime) -> dict[str, Any]:
    """Release the holder only after contention was observed, never after a sleep."""
    await adapter.reset()
    snapshots = await asyncio.gather(adapter.fresh(), adapter.fresh())
    locked = asyncio.Event()
    attempted = asyncio.Event()
    committed = asyncio.Event()
    events: list[str] = []
    callers: list[dict[str, Any]] = [{}, {}]

    async def holder() -> None:
        async with adapter.transaction() as transaction:
            rowcount = await adapter.write(transaction, "cas", snapshots[0])
            events.append("0:write_locked")
            locked.set()
            await attempted.wait()
        callers[0] = {
            "outcome": "committed",
            "attempts": [
                {"read": snapshots[0], "rowcount": rowcount, "outcome": "committed"}
            ],
        }
        events.append("0:committed")
        committed.set()

    async def contender() -> None:
        await locked.wait()
        attempt: dict[str, Any] = {"read": snapshots[1]}
        stage = "execute"
        try:
            async with adapter.transaction() as transaction:
                attempt["rowcount"] = await adapter.write(
                    transaction, "cas", snapshots[1]
                )
                stage = "commit"
            attempt["outcome"] = "committed" if attempt["rowcount"] == 1 else "conflict"
        except (ExecutionError, DBAPIError) as error:
            attempt.update(contention(error, stage))
        finally:
            events.append("1:first_attempt_closed")
            attempted.set()
        await committed.wait()
        attempts = [attempt]
        if attempt["outcome"] in ("contention", "conflict"):
            attempts.append(await retry_fresh(adapter))
        callers[1] = {"outcome": attempts[-1]["outcome"], "attempts": attempts}
        events.append("1:retry_finished")

    async with asyncio.timeout(15), asyncio.TaskGroup() as tasks:
        tasks.create_task(holder())
        tasks.create_task(contender())
    final = await adapter.fresh()
    return {
        "callers": callers,
        "final": final,
        "events": events,
        "oracle": assess(callers, final),
    }

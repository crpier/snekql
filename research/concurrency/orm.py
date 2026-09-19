"""Normal ORM object mutation, with and without the mapper's version counter."""

import asyncio
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.exc import StaleDataError

from research.concurrency.observations import assess
from research.concurrency.runtime import Runtime


async def stale_objects(adapter: Runtime) -> dict[str, Any]:
    """End read transactions but keep independent sessions and their loaded objects."""
    await adapter.reset()
    ready = asyncio.Barrier(2)
    first_done = asyncio.Event()
    events: list[str] = []
    callers: list[dict[str, Any]] = [{}, {}]

    async def caller(index: int) -> None:
        async with AsyncSession(adapter.engine, expire_on_commit=False) as session:
            held = (
                await session.scalars(
                    select(adapter.entry).where(adapter.entry.id == 1)
                )
            ).one()
            callers[index]["read"] = {
                "quantity": held.quantity,
                "revision": held.revision,
            }
            await session.commit()
            events.append(f"{index}:read_committed")
            await ready.wait()
            if index:
                await first_done.wait()
            held.quantity -= 1
            try:
                await session.commit()
            except StaleDataError as error:
                callers[index].update(
                    outcome="conflict",
                    error_type=type(error).__name__,
                    message=str(error),
                )
                await session.rollback()
            else:
                callers[index].update(outcome="committed", held_revision=held.revision)
            events.append(f"{index}:write_finished:{callers[index]['outcome']}")
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

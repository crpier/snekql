"""Sequential worker with a process-owned Database and a transaction per job."""

from collections.abc import AsyncIterable

from examples.service_database import Entry, EntryInput, open_service
from snekql import sqlite


async def run_worker(
    config: sqlite.Config, deliveries: AsyncIterable[EntryInput]
) -> None:
    """Stop on failure; the queue owner must reconcile uncertain commit outcomes."""
    async with open_service(config) as database:
        async for entry in deliveries:
            async with database.transaction() as transaction:
                await transaction.execute(
                    sqlite.insert(Entry(entry_id=entry.entry_id, label=entry.label))
                )
            # A real queue adapter may acknowledge this delivery only here.

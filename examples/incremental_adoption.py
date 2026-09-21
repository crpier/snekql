"""Attach to an externally migrated table without taking over migration history."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from examples.service_database import Entry
from snekql import sqlite


@asynccontextmanager
async def open_existing(config: sqlite.Config) -> AsyncIterator[sqlite.Database]:
    """Verify the row contract after the existing layer's deploy job has run.

    Keep its migration runner as the sole schema owner. This function neither
    applies snekql migrations nor claims that an external migration ran.
    """
    async with await sqlite.Database.initialize(config) as database:
        await database.verify([Entry])
        yield database

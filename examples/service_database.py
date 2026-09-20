"""Service schema and explicit deployment/startup without a web dependency."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from pydantic import BaseModel, Field

from snekql import sqlite


class Entry[S = sqlite.Pending](sqlite.Model[S, "Entry[sqlite.Fetched]"]):
    """A service-owned record, with a caller-assigned primary key."""

    entry_id: sqlite.Col[int] = sqlite.Integer(primary_key=True)
    label: sqlite.Col[str] = sqlite.Text()


MIGRATIONS = {
    "0001_service_entry": (
        'CREATE TABLE "entry" ('
        '"entry_id" INTEGER PRIMARY KEY, "label" TEXT NOT NULL) STRICT'
    ),
}
"""Reviewed, literal SQL; never regenerate deployed bodies from current models."""


@asynccontextmanager
async def open_service(config: sqlite.Config) -> AsyncIterator[sqlite.Database]:
    """Open one process-owned Database and reject undeployed or drifted schema."""
    async with await sqlite.Database.initialize(config) as database:
        await database.verify_migrations(MIGRATIONS)
        await database.verify([Entry])
        yield database


async def deploy(config: sqlite.Config) -> None:
    """Run once in an authorized deploy job, before starting application replicas."""
    async with await sqlite.Database.initialize(config) as database:
        await database.migrate(MIGRATIONS)
        await database.verify_migrations(MIGRATIONS)
        await database.verify([Entry])


class EntryInput(BaseModel):
    """Validated command data shared by HTTP requests and worker deliveries."""

    entry_id: int = Field(ge=1)
    label: str = Field(min_length=1, max_length=200)

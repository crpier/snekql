"""SQLite service startup verifies deployed schema without applying migrations."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException
from pydantic import BaseModel, Field

from examples.service_database import Entry, EntryInput, open_service
from snekql import sqlite


class EntryBatch(BaseModel):
    """One bounded, atomic write request."""

    entries: list[EntryInput] = Field(min_length=1, max_length=100)


def create_app(config: sqlite.Config) -> FastAPI:
    """Build an unstarted app; lifespan owns connectivity, never schema mutation."""
    database: sqlite.Database | None = None

    async def provide_database() -> sqlite.Database:
        if database is None:
            raise HTTPException(status_code=503, detail="Database is not ready")
        return database

    @asynccontextmanager
    async def lifespan(_application: FastAPI) -> AsyncIterator[None]:
        nonlocal database
        async with open_service(config) as opened:
            database = opened
            try:
                yield
            finally:
                database = None

    application = FastAPI(lifespan=lifespan)

    @application.post("/entries", status_code=201)
    async def create_entries(
        batch: EntryBatch,
        connection: Annotated[sqlite.Database, Depends(provide_database)],
    ) -> list[EntryInput]:
        # Exit the transaction before returning. A yielded request transaction
        # could commit after the response has already been sent.
        try:
            async with connection.transaction() as transaction:
                for entry in batch.entries:
                    await transaction.execute(
                        sqlite.insert(Entry(entry_id=entry.entry_id, label=entry.label))
                    )
        except sqlite.DatabaseRuntimeError as e:
            if e.failure is not None and e.failure.category == "unique_violation":
                raise HTTPException(
                    status_code=409, detail="Entry key already exists"
                ) from e
            # Do not offer automatic replay: a failed COMMIT can be uncertain.
            raise HTTPException(
                status_code=500,
                detail="Write failed; check its outcome before retrying",
            ) from e
        return batch.entries

    return application

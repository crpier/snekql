"""Workload builders shared by the SQLite and MariaDB benchmark runners.

A workload is a factory that, given a live ``Database`` and the backend's query
constructors, returns a per-operation coroutine for ``run_concurrent``. The
backend-specific bits (``Model``, ``select``, ``insert``) are injected so the
same workload shapes run unchanged against either backend.
"""

from __future__ import annotations

import secrets
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from snekql.runtime import Database

_PAYLOAD = "x" * 200


@dataclass
class BackendQueryApi:
    """The backend-specific constructors a workload needs."""

    model: Any
    select: Callable[..., Any]
    insert: Callable[..., Any]


async def seed_rows(api: BackendQueryApi, db: Database, count: int) -> None:
    """Insert ``count`` rows so point reads and large selects have data."""

    batch = 500
    inserted = 0
    while inserted < count:
        this_batch = min(batch, count - inserted)
        async with db.transaction() as tx:
            for offset in range(this_batch):
                row = api.model(
                    email=f"user{inserted + offset}@example.com",
                    payload=_PAYLOAD,
                )
                await tx.execute(api.insert(row))
        inserted += this_batch


def point_read(
    api: BackendQueryApi, db: Database, row_count: int
) -> Callable[[int], Awaitable[None]]:
    """Build a workload that reads one random row by primary key."""

    model = api.model
    select = api.select

    async def op(_worker: int) -> None:
        target = secrets.randbelow(row_count) + 1
        query = select(model).where(model.id.eq(target)).limit(1)
        async with db.transaction() as tx:
            _ = await tx.fetch_one_or_none(query)

    return op


def write_row(api: BackendQueryApi, db: Database) -> Callable[[int], Awaitable[None]]:
    """Build a workload that inserts one row per operation."""

    model = api.model
    insert = api.insert

    async def op(worker: int) -> None:
        row = model(
            email=f"w{worker}-{secrets.token_hex(6)}@example.com", payload=_PAYLOAD
        )
        async with db.transaction() as tx:
            await tx.execute(insert(row))

    return op


def mixed_read_write(
    api: BackendQueryApi, db: Database, row_count: int
) -> Callable[[int], Awaitable[None]]:
    """Build a workload alternating point reads and inserts (~5:1)."""

    reader = point_read(api, db, row_count)
    writer = write_row(api, db)

    async def op(worker: int) -> None:
        if secrets.randbelow(6) == 0:
            await writer(worker)
        else:
            await reader(worker)

    return op


def large_select(
    api: BackendQueryApi, db: Database, limit: int
) -> Callable[[int], Awaitable[None]]:
    """Build a workload that materializes a large result set via fetch_all."""

    model = api.model
    select = api.select

    async def op(_worker: int) -> None:
        query = select(model).all().limit(limit)
        async with db.transaction() as tx:
            _ = await tx.fetch_all(query)

    return op

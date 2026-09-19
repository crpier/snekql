"""Shared evidence encoding and independent database setup/read operations."""

from sqlite3 import SQLITE_CONSTRAINT
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from snekql.errors import ExecutionError


def snapshot(entry: Any) -> dict[str, Any]:
    """Call only for loaded attributes: never initiate implicit async ORM IO."""
    row = {
        name: getattr(entry, name)
        for name in ("id", "code", "quantity", "note", "occurred_at")
    }
    row["_types"] = {name: type(value).__name__ for name, value in row.items()}
    row["_timestamp_tz"] = str(row["occurred_at"].tzinfo)
    return row


def failure(error: Exception, stage: str) -> dict[str, Any]:
    """Retain exception provenance rather than equating all failures."""
    cause = error.__cause__
    if isinstance(error, (ExecutionError, DBAPIError)):
        driver_error = error.orig if isinstance(error, DBAPIError) else cause
        code = getattr(driver_error, "sqlite_errorcode", None)
        if not (
            (isinstance(code, int) and code & 0xFF == SQLITE_CONSTRAINT)
            or (getattr(driver_error, "args", (None,))[0] in (1062, 1048, 1292, 1366))
        ):
            raise error
    return {
        "outcome": "rejected",
        "stage": stage,
        "error_type": type(error).__name__,
        "message": str(error),
        "cause_type": type(cause).__name__ if cause else None,
    }


async def seed(engine: AsyncEngine, backend: str) -> None:
    """Reset both rows outside the transaction whose semantics are under test."""
    occurred_at = (
        "2026-01-02T03:04:05.123Z" if backend == "sqlite" else "2026-01-02 03:04:05.123"
    )
    async with engine.begin() as handle:
        await handle.exec_driver_sql("DELETE FROM entries")
        await handle.execute(
            text(
                "INSERT INTO entries (id, code, quantity, note, occurred_at) VALUES (1, 'one', 1, 'keep', :instant), (2, 'two', 1, NULL, :instant)"
            ),
            {"instant": occurred_at},
        )


async def snek_read(database: Any, declarations: Any) -> dict[str, Any]:
    async with database.transaction() as transaction:
        return snapshot(
            await transaction.fetch_one(
                declarations.db.select(declarations.Entry).where(
                    declarations.Entry.id.eq(1)
                )
            )
        )


async def orm_read(engine: AsyncEngine, entry: Any) -> dict[str, Any]:
    async with AsyncSession(engine) as session:
        return snapshot(
            (await session.scalars(select(entry).where(entry.id == 1))).one()
        )

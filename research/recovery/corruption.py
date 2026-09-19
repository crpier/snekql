"""External writes are observed separately from application materialization."""

from typing import Any

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from research.recovery.common import failure, seed, snapshot
from snekql.errors import ModelValidationError


async def _snek_reads(database: Any, declarations: Any) -> dict[str, Any]:
    record: dict[str, Any] = {}
    async with database.transaction() as transaction:
        try:
            row = await transaction.fetch_one(
                declarations.db.select(declarations.Entry).where(
                    declarations.Entry.id.eq(1)
                )
            )
        except ModelValidationError as error:
            record["read"] = failure(error, "materialization")
        else:
            record["read"] = {"outcome": "accepted", "row": snapshot(row)}
        row = await transaction.fetch_one(
            declarations.db.select(declarations.Entry).where(
                declarations.Entry.id.eq(2)
            )
        )
        record["same_transaction_good_row"] = snapshot(row)
    return record


async def _orm_reads(engine: AsyncEngine, entry: Any) -> dict[str, Any]:
    record: dict[str, Any] = {}
    async with AsyncSession(engine) as session:
        try:
            row = (await session.scalars(select(entry).where(entry.id == 1))).one()
        except (ValidationError, ValueError) as error:
            record["read"] = failure(error, "materialization")
        else:
            record["read"] = {"outcome": "accepted", "row": snapshot(row)}
        row = (
            await session.scalars(
                select(entry).where(
                    entry.id == 2  # noqa: PLR2004 - Known-good control row.
                )
            )
        ).one()
        record["same_transaction_good_row"] = snapshot(row)
    return record


async def observe_corruption(
    engine: AsyncEngine, backend: str, library: str, owner: Any, declarations: Any
) -> dict[str, Any]:
    """No constraints are disabled: a raw-write rejection is not a decode failure."""
    observations: dict[str, Any] = {}
    for name, assignment in (
        ("zero_quantity", "UPDATE entries SET quantity=0 WHERE id=1"),
        ("negative_quantity", "UPDATE entries SET quantity=-1 WHERE id=1"),
        (
            "malformed_timestamp",
            "UPDATE entries SET occurred_at='not-a-date' WHERE id=1",
        ),
        (
            "naive_timestamp",
            "UPDATE entries SET occurred_at='2026-01-02 03:04:05.123' WHERE id=1",
        ),
    ):
        await seed(engine, backend)
        try:
            async with engine.begin() as handle:
                await handle.exec_driver_sql(assignment)
        except DBAPIError as error:
            observations[name] = {
                "injection": failure(error, "raw_update"),
                "read": {"outcome": "not_attempted"},
            }
            continue
        observations[name] = {
            "injection": {"outcome": "accepted"},
            **(
                await _snek_reads(owner, declarations)
                if library == "snekql"
                else await _orm_reads(engine, owner)
            ),
        }
    return observations

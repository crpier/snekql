"""Keep transaction and ORM control flow visible instead of hiding their differences."""

from typing import Any

from sqlalchemy import inspect, select, update
from sqlalchemy.exc import IntegrityError, PendingRollbackError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from research.recovery.common import failure, orm_read, seed, snapshot, snek_read
from snekql.errors import (
    DatabaseRuntimeError,
    ExecutionError,
    FrozenModelError,
    TransactionClosedError,
)


async def _snek_assignment(database: Any, declarations: Any) -> dict[str, Any]:
    namespace = declarations.db
    entry = declarations.Entry
    async with database.transaction() as reader:
        held = await reader.fetch_one(namespace.select(entry).where(entry.id.eq(1)))
    record = {}
    for name, quantity in (("valid", 3), ("invalid", 0)):
        try:
            held.quantity = quantity
        except FrozenModelError as error:
            record[name] = failure(error, "assignment")
        else:
            record[name] = {"outcome": "accepted"}
    record["held"] = snapshot(held)
    return record


async def _orm_assignment(engine: AsyncEngine, entry: Any) -> dict[str, Any]:
    async with AsyncSession(engine) as session:
        held = (await session.scalars(select(entry).where(entry.id == 1))).one()
        record = {}
        for name, quantity in (("valid", 3), ("invalid", 0)):
            held.quantity = quantity
            record[name] = {
                "outcome": "accepted",
                "held": snapshot(held),
            }
        # Assignment-only probe deliberately does not flush.
        await session.rollback()
    return record


async def _snek_reuse(transaction: Any, namespace: Any, entry: Any) -> dict[str, Any]:
    """Probe read and write reuse without exiting the failed transaction."""
    record: dict[str, Any] = {}
    try:
        record["read_after_failure"] = snapshot(
            await transaction.fetch_one(namespace.select(entry).where(entry.id.eq(1)))
        )
    except DatabaseRuntimeError as error:
        if type(error) is not DatabaseRuntimeError:
            raise
        record["read_after_failure"] = failure(error, "select")
    try:
        await transaction.execute(
            namespace.update(entry).set(entry.quantity.to(4)).where(entry.id.eq(1))
        )
    except DatabaseRuntimeError as error:
        if type(error) is not DatabaseRuntimeError:
            raise
        record["retry_write"] = failure(error, "execute")
    else:
        record["retry_write"] = {"outcome": "accepted"}
    return record


async def snek_lifecycle(
    engine: AsyncEngine, database: Any, declarations: Any, backend: str
) -> dict[str, Any]:
    namespace = declarations.db
    entry = declarations.Entry
    observations: dict[str, Any] = {}
    for name in ("commit", "escaping_error", "caught_error"):
        await seed(engine, backend)
        record: dict[str, Any] = {}
        transaction = database.transaction()
        async with database.transaction() as reader:
            held = await reader.fetch_one(namespace.select(entry).where(entry.id.eq(1)))
        try:
            async with transaction:
                await transaction.execute(
                    namespace.update(entry)
                    .set(entry.quantity.to(3))
                    .where(entry.id.eq(1))
                )
                record["after_write"] = snapshot(held)
                if name != "commit":
                    try:
                        await transaction.execute(
                            namespace.update(entry)
                            .set(entry.code.to("two"))
                            .where(entry.id.eq(1))
                        )
                    except ExecutionError as error:
                        record["failure"] = failure(error, "execute")
                        if name == "escaping_error":
                            raise
                        record.update(await _snek_reuse(transaction, namespace, entry))
        except ExecutionError as error:
            record["exit"] = failure(error, "transaction_exit")
        else:
            record["exit"] = {"outcome": "returned_normally"}
        record["held_after_exit"] = snapshot(held)
        record["fresh"] = await snek_read(database, declarations)
        try:
            await transaction.fetch_one(namespace.select(entry).where(entry.id.eq(1)))
        except TransactionClosedError as error:
            record["reuse_closed"] = failure(error, "read")
        async with database.transaction() as recovery:
            await recovery.execute(
                namespace.update(entry).set(entry.quantity.to(5)).where(entry.id.eq(1))
            )
        record["fresh_recovery"] = await snek_read(database, declarations)
        observations[name] = record
    await seed(engine, backend)
    observations["assignment"] = await _snek_assignment(database, declarations)
    return observations


async def orm_lifecycle(
    engine: AsyncEngine, entry: Any, backend: str
) -> dict[str, Any]:
    observations: dict[str, Any] = {}
    for name in ("commit", "escaping_error", "caught_error"):
        await seed(engine, backend)
        record: dict[str, Any] = {}
        async with AsyncSession(engine, expire_on_commit=False) as session:
            held = (await session.scalars(select(entry).where(entry.id == 1))).one()
            try:
                held.quantity = 3
                await session.flush()
                record["after_write"] = snapshot(held)
                if name != "commit":
                    held.code = "two"
                    try:
                        await session.flush()
                    except IntegrityError as error:
                        record["failure"] = failure(error, "flush")
                        if name == "escaping_error":
                            raise
                        try:
                            await session.scalars(select(entry).where(entry.id == 1))
                        except PendingRollbackError as error:
                            record["read_after_failure"] = failure(error, "select")
                        # A direct mapped UPDATE avoids modifying an expired object.
                        try:
                            await session.execute(
                                entry.__table__.update()
                                .where(entry.id == 1)
                                .values(quantity=4)
                            )
                        except PendingRollbackError as error:
                            record["retry_write"] = failure(error, "execute")
                await session.commit()
            except (IntegrityError, PendingRollbackError) as error:
                record["exit"] = failure(
                    error, "flush" if name == "escaping_error" else "commit"
                )
                await session.rollback()
            else:
                record["exit"] = {"outcome": "committed"}
            record["expired_after_exit"] = sorted(inspect(held).expired_attributes)
            if record["expired_after_exit"]:
                # Do not trigger implicit lazy IO by reading expired properties.
                await session.refresh(held)
                record["held_after_explicit_refresh"] = snapshot(held)
            else:
                record["held_after_exit"] = snapshot(held)
            # End the refresh's read transaction before a separate writer on SQLite.
            await session.rollback()
            record["fresh"] = await orm_read(engine, entry)
            held = (await session.scalars(select(entry).where(entry.id == 1))).one()
            held.quantity = 5
            await session.commit()
            record["same_session_recovery"] = "committed"
        record["fresh_recovery"] = await orm_read(engine, entry)
        observations[name] = record
    await seed(engine, backend)
    observations["assignment"] = await _orm_assignment(engine, entry)
    return observations


async def orm_statement_error(
    engine: AsyncEngine, entry: Any, backend: str
) -> dict[str, Any]:
    """Compare direct Session.execute with flush; neither uses a savepoint here."""
    await seed(engine, backend)
    record: dict[str, Any] = {}
    async with AsyncSession(engine) as session:
        await session.execute(update(entry).where(entry.id == 1).values(quantity=3))
        try:
            await session.execute(update(entry).where(entry.id == 1).values(code="two"))
        except IntegrityError as error:
            record["failure"] = failure(error, "execute")
        record["read_after_failure"] = snapshot(
            (await session.scalars(select(entry).where(entry.id == 1))).one()
        )
        await session.execute(update(entry).where(entry.id == 1).values(quantity=4))
        await session.commit()
        record["exit"] = {"outcome": "committed"}
    record["fresh"] = await orm_read(engine, entry)
    return record

"""Explicit Core transactions shared by both comparative database targets."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from time import perf_counter

from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from benchmarks._comparison_diagnostics import PoolDiagnostics


@asynccontextmanager
async def core_transaction(
    engine: AsyncEngine, diagnostics: PoolDiagnostics
) -> AsyncIterator[AsyncConnection]:
    """Acquire, explicitly BEGIN, acknowledge commit, and return the lease."""
    started = perf_counter() if diagnostics.active else None
    async with engine.connect() as connection:
        if started is not None:
            diagnostics.samples.record(perf_counter() - started)
        (await connection.exec_driver_sql("BEGIN")).close()
        try:
            yield connection
            await connection.commit()
        except BaseException:
            await connection.rollback()
            raise

"""Bounded native-driver checkout; no lifecycle guarantees beyond the benchmark."""

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from time import perf_counter

from benchmarks._comparison_diagnostics import PoolDiagnostics


@asynccontextmanager
async def native_lease[ConnectionT](
    available: asyncio.Queue[ConnectionT], diagnostics: PoolDiagnostics
) -> AsyncIterator[ConnectionT]:
    """Retain a bounded lease through the caller's acknowledged commit/rollback."""
    started = perf_counter() if diagnostics.collect_pool else None
    connection = await available.get()
    try:
        if started is not None:
            diagnostics.samples.record(perf_counter() - started)
        yield connection
    finally:
        available.put_nowait(connection)

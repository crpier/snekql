"""Large retry budgets retain bounded delays and native lock-failure evidence."""

from collections.abc import AsyncGenerator
from pathlib import Path

from anyio import TemporaryDirectory
from snektest import Param, assert_eq, assert_raises, fixture, load_fixture, test

from snekql import sqlite


@fixture
async def provide_contenders(
    backoffs: tuple[float, float],
) -> AsyncGenerator[tuple[sqlite.Database, sqlite.Database]]:
    """Prepare independent connections with no in-driver wait on contention."""
    async with TemporaryDirectory() as directory:
        config = sqlite.Config(
            database=Path(directory) / "retry.db",
            pool_size=1,
            busy_max_retries=1100,
            busy_base_backoff=backoffs[0],
            busy_max_backoff=backoffs[1],
        )
        async with (
            await sqlite.Database.initialize(config) as holder,
            await sqlite.Database.initialize(config) as contender,
        ):
            async with contender.transaction() as transaction:
                await transaction.fetch_one(sqlite.raw("PRAGMA busy_timeout=0"))
            yield holder, contender


@test(
    [
        Param((0.0, 0.0), name="zero-base"),
        Param((0.01, 0.0), name="zero-cap"),
        Param((0.01, 1e-300), name="positive-cap"),
    ],
    mark="medium",
)
async def large_retry_budget_keeps_native_lock_failure(
    backoffs: tuple[float, float],
) -> None:
    """Exhausting an accepted retry budget must not fail in backoff arithmetic."""
    holder, contender = await load_fixture(provide_contenders(backoffs))

    async with holder.transaction(mode="immediate"):
        with assert_raises(sqlite.DatabaseRuntimeError) as raised:
            async with contender.transaction(mode="immediate"):
                pass

    failure = raised.exception.failure
    assert failure is not None
    assert_eq((failure.category, failure.code), ("lock_conflict", 5))

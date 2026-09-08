"""MIN/MAX honor the caller's result-validation policy."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated

from annotated_types import Ge
from snektest import Param, assert_eq, assert_raises, test

from snekql import sqlite
from snekql.errors import ModelValidationError
from tests.helpers import initialized_database


class Reading[S = sqlite.Pending](sqlite.Model[S, "Reading[sqlite.Fetched]"]):
    """Logical constraints can be violated by explicitly unchecked inputs."""

    score: Reading.Col[Annotated[int, Ge(0)]] = sqlite.Integer(nullable=False)


@test(
    [
        Param(value=(extremum, method, mode), name=f"{extremum}_{method}_{mode}")
        for extremum in ("min", "max")
        for method in ("one", "all", "chunks", "scalar")
        for mode in ("raw", "validated")
    ],
    mark="medium",
)
async def extrema_respect_validation_policy(case: tuple[str, str, str]) -> None:
    """Each read path applies the chosen validation policy to MIN and MAX."""

    async with await initialized_database(
        database=":memory:", models=[Reading]
    ) as database:
        async with database.transaction() as setup:
            await setup.execute(sqlite.insert(Reading.construct(score=-1)))

        extremum = Reading.score.min() if case[0] == "min" else Reading.score.max()
        query = sqlite.select(extremum).all()
        async with database.transaction() as tx:

            async def read_extremum() -> object:
                """Exercise the selected public read method with one validation flag."""

                validate = case[2] == "validated"
                if case[1] == "one":
                    return await tx.fetch_one(query, validate=validate)
                if case[1] == "all":
                    return await tx.fetch_all(query, validate=validate)
                if case[1] == "scalar":
                    return await tx.fetch_one(
                        sqlite.select(
                            Reading.score.count(), sqlite.scalar(query)
                        ).all(),
                        validate=validate,
                    )
                values: list[object] = []
                async with tx.fetch_chunks(query, size=1, validate=validate) as chunks:
                    async for batch in chunks:
                        values.extend(batch)
                return values

            if case[2] == "validated":
                with assert_raises(ModelValidationError):
                    await read_extremum()
            else:
                value = await read_extremum()
                if case[1] == "one":
                    assert_eq(value, -1)
                elif case[1] == "scalar":
                    assert_eq(value, (1, -1))
                else:
                    assert_eq(value, [-1])


@test([Param(value=mode, name=mode) for mode in ("raw", "validated")], mark="medium")
async def empty_aggregates_keep_null_and_count_semantics(mode: str) -> None:
    """Empty extrema/SUM/AVG stay None; COUNT stays zero under both policies."""

    async with (
        await initialized_database(database=":memory:", models=[Reading]) as database,
        database.transaction() as tx,
    ):
        row = await tx.fetch_one(
            sqlite.select(
                Reading.score.min(),
                Reading.score.max(),
                Reading.score.count(),
                Reading.score.sum(),
                Reading.score.avg(),
            ).all(),
            validate=mode == "validated",
        )

    assert_eq(row, (None, None, 0, None, None))


@test([Param(value=mode, name=mode) for mode in ("raw", "validated")], mark="medium")
async def numeric_aggregate_normalization_is_unchanged(mode: str) -> None:
    """COUNT/SUM/AVG keep their numeric result types even on unchecked reads."""

    async with await initialized_database(
        database=":memory:", models=[Reading]
    ) as database:
        async with database.transaction() as setup:
            await setup.execute(sqlite.insert(Reading(score=2)))
            await setup.execute(sqlite.insert(Reading(score=4)))

        async with database.transaction() as tx:
            row = await tx.fetch_one(
                sqlite.select(
                    Reading.score.count(), Reading.score.sum(), Reading.score.avg()
                ).all(),
                validate=mode == "validated",
            )

    assert isinstance(row, tuple)
    assert_eq(row, (2, 6, 3.0))
    assert_eq(tuple(type(value) for value in row), (int, int, float))


@test(mark="medium")
async def default_extrema_decoding_preserves_logical_datetime_type() -> None:
    """Validated MIN/MAX still decode stored timestamp text to logical datetimes."""

    class Event[S = sqlite.Pending](sqlite.Model[S, "Event[sqlite.Fetched]"]):
        """An order-preserving logical timestamp over text storage."""

        timestamp: Event.Col[sqlite.UtcDatetime] = sqlite.Text(nullable=False)

    when = datetime(2026, 1, 1, tzinfo=UTC)
    async with await initialized_database(
        database=":memory:", models=[Event]
    ) as database:
        async with database.transaction() as setup:
            await setup.execute(sqlite.insert(Event(timestamp=when)))

        async with database.transaction() as tx:
            row = await tx.fetch_one(
                sqlite.select(Event.timestamp.min(), Event.timestamp.max()).all()
            )

    assert_eq(row, (when, when))
    assert_eq(tuple(type(value) for value in row), (datetime, datetime))

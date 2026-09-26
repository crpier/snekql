"""Generated data checks query composition against application-level arithmetic."""

from collections.abc import AsyncGenerator
from typing import ClassVar

from hypothesis import settings
from hypothesis.strategies import integers, lists, none, one_of
from pydantic import BaseModel
from snektest import assert_eq, fixture, test_hypothesis

from snekql import sqlite


class Sample[S = sqlite.Pending](sqlite.Model[S]):
    __row_type__: ClassVar[sqlite.ReadType[Sample[sqlite.Row]]]
    id: Sample.Col[int] = sqlite.Integer(primary_key=True)
    value: Sample.Col[int | None] = sqlite.Integer()


class Adjusted(BaseModel):
    id: int
    value: int


class ComputedRole:
    """The row-local calculation becomes an independently filtered relation."""


@fixture
async def samples(values: list[int | None]) -> AsyncGenerator[sqlite.Database]:
    """Load each generated dataset through ordinary inserts and migrations."""
    async with await sqlite.Database.initialize(database=":memory:") as database:
        await database.migrate({"001": sqlite.scaffold([Sample])})
        async with database.transaction() as transaction:
            await transaction.execute(
                sqlite.insert_many(
                    Sample,
                    [
                        Sample(id=index, value=value)
                        for index, value in enumerate(values)
                    ],
                )
            )
        yield database


@settings(max_examples=80, derandomize=True, deadline=None)
@test_hypothesis(
    lists(one_of(none(), integers(-10, 10)), max_size=12),
    integers(-30, 30),
    mark="medium",
)
async def cte_arithmetic_filter_matches_python(
    values: list[int | None], threshold: int
) -> None:
    """NULL fallback, arithmetic, labels, and CTE predicates preserve row meaning."""
    async with samples(values) as database:
        identifier = Sample.id.label("id")
        adjusted = Sample.value.coalesce(7).mul(3).sub(1).label("value")
        computed = (
            sqlite.select(Sample)
            .project(Adjusted, id=identifier, value=adjusted)
            .cte(ComputedRole, name="computed")
        )
        query = (
            sqlite.select(computed.column(identifier))
            .where(computed.column(adjusted).gt(threshold))
            .order_by(computed.column(identifier).asc())
        )

        async with database.transaction() as transaction:
            actual = await transaction.fetch_all(query)

    expected = [
        index
        for index, value in enumerate(values)
        if 3 * (7 if value is None else value) - 1 > threshold
    ]
    assert_eq(actual, expected)


@settings(max_examples=80, derandomize=True, deadline=None)
@test_hypothesis(
    lists(one_of(none(), integers(-10, 10)), max_size=12),
    integers(-10, 10),
    mark="medium",
)
async def union_all_preserves_filtered_multiplicity(
    values: list[int | None], boundary: int
) -> None:
    """Overlapping operands keep duplicates rather than applying Python-set semantics."""
    async with samples(values) as database:
        identifier = Sample.id.label("id")
        adjusted = Sample.value.coalesce(7).label("value")
        projection = sqlite.select(Sample).project(
            Adjusted, id=identifier, value=adjusted
        )
        combined = projection.where(Sample.value.coalesce(7).lte(boundary)).union_all(
            projection.where(Sample.value.coalesce(7).gte(boundary))
        )
        query = combined.order_by(combined.column(identifier).asc())

        async with database.transaction() as transaction:
            actual = await transaction.fetch_all(query)

    expected = [
        Adjusted(id=index, value=7 if value is None else value)
        for index, value in enumerate(values)
        for _ in range(2 if (7 if value is None else value) == boundary else 1)
    ]
    assert_eq(actual, expected)

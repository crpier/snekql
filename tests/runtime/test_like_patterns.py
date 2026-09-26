"""SQL patterns are not values to store in a constrained text column."""

from collections.abc import AsyncGenerator
from typing import Annotated, ClassVar

from pydantic import Field
from snektest import Param, assert_eq, fixture, load_fixture, test

from snekql import sqlite


class Name[S = sqlite.Pending](sqlite.Model[S]):
    __row_type__: ClassVar[sqlite.ReadType[Name[sqlite.Row]]]
    value: Name.Col[Annotated[str, Field(min_length=3, max_length=8)]] = sqlite.Text()


@fixture
async def names() -> AsyncGenerator[sqlite.Database]:
    """Stored values satisfy the complete column contract."""
    async with await sqlite.Database.initialize(database=":memory:") as database:
        await database.migrate({"001": sqlite.scaffold([Name])})
        async with database.transaction() as transaction:
            await transaction.execute(
                sqlite.insert_many(Name, [Name(value="Ada"), Name(value="Grace")])
            )
        yield database


@test(
    [Param("A%", name="short"), Param("%%%%%%%%%%%%A%", name="long")],
    mark="medium",
)
async def like_patterns_do_not_inherit_stored_value_constraints(pattern: str) -> None:
    """A valid wildcard pattern can be shorter or longer than every stored value."""
    database = await load_fixture(names())
    query = (
        sqlite.select(Name.value)
        .where(Name.value.like(pattern))
        .order_by(Name.value.asc())
    )

    async with database.transaction() as transaction:
        rows = await transaction.fetch_all(query)

    assert_eq(rows, ["Ada", "Grace"] if pattern.startswith("%") else ["Ada"])

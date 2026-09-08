"""SQLite pagination retains its existing unlimited-row syntax."""

from __future__ import annotations

from snektest import Param, assert_eq, assert_in, test

from snekql import sqlite


@test(
    [
        Param(value=(0, None, [1, 2, 3]), name="zero_offset"),
        Param(value=(1, None, [2, 3]), name="offset_only"),
        Param(value=(4, None, []), name="beyond_end"),
        Param(value=(1, 1, [2]), name="explicit_limit"),
        Param(value=(1, 0, []), name="zero_limit"),
    ],
    mark="medium",
)
async def pagination_returns_expected_window(
    case: tuple[int, int | None, list[int]],
) -> None:
    """Offset and explicit limits retain the existing SQLite window semantics."""

    class Item[S = sqlite.Pending](sqlite.Model[S, "Item[sqlite.Fetched]"]):
        """A deterministic pagination sequence."""

        id: Item.Col[int] = sqlite.Integer(primary_key=True)

    async with await sqlite.Database.initialize(database=":memory:") as database:
        await database.migrate(
            {
                "create": "CREATE TABLE item (id INTEGER PRIMARY KEY) STRICT",
                "seed": "INSERT INTO item VALUES (1), (2), (3)",
            }
        )
        query = (
            sqlite.select(Item.id)
            .where(Item.id.gt(0))
            .order_by(Item.id.asc())
            .offset(case[0])
        )
        if case[1] is not None:
            query = query.limit(case[1])
        async with database.transaction() as transaction:
            rows = await transaction.fetch_all(query)

    assert_eq(rows, case[2])


@test(mark="fast")
def offset_only_inspection_preserves_parameter_order() -> None:
    """The unlimited-row sentinel is dialect SQL, not an extra bound parameter."""

    class Item[S = sqlite.Pending](sqlite.Model[S, "Item[sqlite.Fetched]"]):
        """A scalar pagination projection."""

        id: Item.Col[int] = sqlite.Integer(primary_key=True)

    query = sqlite.select(Item.id).where(Item.id.gt(10)).offset(2)

    assert_in(
        'SELECT "id" FROM "item" WHERE ("id" > ?) LIMIT -1 OFFSET ? | params=(10, 2)',
        repr(query),
    )


@test(mark="fast")
def explicit_window_inspection_preserves_parameter_order() -> None:
    """Explicit limits still bind between predicate values and the offset."""

    class Item[S = sqlite.Pending](sqlite.Model[S, "Item[sqlite.Fetched]"]):
        """A scalar pagination projection."""

        id: Item.Col[int] = sqlite.Integer(primary_key=True)

    query = sqlite.select(Item.id).where(Item.id.gt(10)).limit(3).offset(2)

    assert_in(
        'SELECT "id" FROM "item" WHERE ("id" > ?) LIMIT ? OFFSET ? | params=(10, 3, 2)',
        repr(query),
    )

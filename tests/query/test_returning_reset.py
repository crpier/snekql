"""Repeated RETURNING replaces the projection while preserving earlier queries."""

from __future__ import annotations

from snektest import Param, assert_eq, assert_in, test

from snekql import sqlite
from tests.helpers import initialized_database


class Item[S = sqlite.Pending](sqlite.Model[S, "Item[sqlite.Fetched]"]):
    """Every field must be restored by whole-model RETURNING."""

    id: Item.Col[int] = sqlite.Integer(primary_key=True)
    score: Item.Col[int] = sqlite.Integer(nullable=False)
    label: Item.Col[str] = sqlite.Text(nullable=False)


@test(
    [Param(value=shape, name=shape) for shape in ("scalar", "tuple", "model")],
    mark="medium",
)
async def update_returning_resets_projection(shape: str) -> None:
    """The final no-argument call yields an updated Fetched model, not an id."""

    async with await initialized_database(
        database=":memory:", models=[Item]
    ) as database:
        async with database.transaction() as setup:
            await setup.execute(sqlite.insert(Item(id=1, score=10, label="one")))

        base = sqlite.update(Item).set(Item.score.to(20)).all()
        if shape == "scalar":
            query = base.returning(Item.id).returning()
        elif shape == "tuple":
            query = base.returning(Item.label, Item.id).returning()
        else:
            query = base.returning().returning()
        async with database.transaction() as tx:
            rows = await tx.execute(query)

    assert_eq(len(rows), 1)
    assert_eq(repr(rows[0]), "Item[Fetched](id=1, score=20, label='one')")
    assert_eq((rows[0].id, rows[0].score, rows[0].label), (1, 20, "one"))


@test(
    [Param(value=shape, name=shape) for shape in ("scalar", "tuple", "model")],
    mark="medium",
)
async def delete_returning_resets_projection(shape: str) -> None:
    """The final no-argument call yields a deleted Fetched model, not an id."""

    async with await initialized_database(
        database=":memory:", models=[Item]
    ) as database:
        async with database.transaction() as setup:
            await setup.execute(sqlite.insert(Item(id=1, score=10, label="one")))

        base = sqlite.delete(Item).all()
        if shape == "scalar":
            query = base.returning(Item.id).returning()
        elif shape == "tuple":
            query = base.returning(Item.label, Item.id).returning()
        else:
            query = base.returning().returning()
        async with database.transaction() as tx:
            rows = await tx.execute(query)

    assert_eq(len(rows), 1)
    assert_eq(repr(rows[0]), "Item[Fetched](id=1, score=10, label='one')")
    assert_eq((rows[0].id, rows[0].score, rows[0].label), (1, 10, "one"))


@test(mark="fast")
def deriving_whole_model_returning_keeps_earlier_queries_immutable() -> None:
    """Replacing a projection does not alter the earlier fluent query object."""

    for original in (
        sqlite.update(Item).set(Item.score.to(20)).all().returning(Item.id),
        sqlite.update(Item).set(Item.score.to(20)).all().returning(Item.label, Item.id),
        sqlite.delete(Item).all().returning(Item.id),
        sqlite.delete(Item).all().returning(Item.label, Item.id),
    ):
        before = repr(original)
        whole = original.returning()

        assert_eq(repr(original), before)
        assert_in('RETURNING "id", "score", "label" | params=', repr(whole))


@test([Param(value=shape, name=shape) for shape in ("scalar", "tuple")], mark="medium")
async def update_whole_model_returning_can_be_replaced_with_projection(
    shape: str,
) -> None:
    """Explicit fields after whole-model RETURNING still determine the result."""

    async with await initialized_database(
        database=":memory:", models=[Item]
    ) as database:
        async with database.transaction() as setup:
            await setup.execute(sqlite.insert(Item(id=1, score=10, label="one")))

        query = sqlite.update(Item).set(Item.score.to(20)).all().returning()
        async with database.transaction() as tx:
            if shape == "scalar":
                assert_eq(await tx.execute(query.returning(Item.score)), [20])
            else:
                assert_eq(
                    await tx.execute(query.returning(Item.label, Item.score)),
                    [("one", 20)],
                )


@test([Param(value=shape, name=shape) for shape in ("scalar", "tuple")], mark="medium")
async def delete_whole_model_returning_can_be_replaced_with_projection(
    shape: str,
) -> None:
    """Explicit fields after whole-model RETURNING still determine the result."""

    async with await initialized_database(
        database=":memory:", models=[Item]
    ) as database:
        async with database.transaction() as setup:
            await setup.execute(sqlite.insert(Item(id=1, score=10, label="one")))

        query = sqlite.delete(Item).all().returning()
        async with database.transaction() as tx:
            if shape == "scalar":
                assert_eq(await tx.execute(query.returning(Item.score)), [10])
            else:
                assert_eq(
                    await tx.execute(query.returning(Item.label, Item.score)),
                    [("one", 10)],
                )

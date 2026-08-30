"""CanonicalDecimal SQLite runtime behavior tests."""

from __future__ import annotations

from decimal import Decimal

from snektest import assert_eq, test

from snekql.sqlite import (
    CanonicalDecimal,
    Fetched,
    Integer,
    Model,
    Pending,
    Text,
    insert,
    select,
)
from tests.helpers import initialized_database


class Price[S = Pending](Model[S, "Price[Fetched]"]):
    """Price table with canonical decimal text storage."""

    id: Price.Col[Price, int] = Integer(primary_key=True)
    amount: Price.Col[Price, CanonicalDecimal] = Text(nullable=False)


@test(mark="medium")
async def canonical_decimal_text_queries_compare_by_value_equality() -> None:
    """Equality queries use canonical decimal text regardless of input scale."""

    database = await initialized_database(database=":memory:", models=[Price])
    try:
        async with database.transaction() as tx:
            await tx.execute(insert(Price(id=1, amount=Decimal("1.50"))))
            await tx.execute(insert(Price(id=2, amount=Decimal(2))))
            equal_ids = await tx.fetch_all(
                select(Price.id)
                .where(Price.amount.eq(Decimal("1.500")))
                .order_by(Price.id.asc()),
            )
    finally:
        await database.close()

    assert_eq(equal_ids, [1])

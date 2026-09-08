"""HAVING validates both direct operands without entering nested query scopes."""

from __future__ import annotations

from snektest import Param, assert_eq, assert_in, assert_raises, test

from snekql import sqlite
from snekql.errors import QueryConstructionError
from tests.helpers import initialized_database


class Sale[S = sqlite.Pending](sqlite.Model[S, "Sale[sqlite.Fetched]"]):
    """A grouped key and a separate ungrouped amount."""

    category: Sale.Col[int] = sqlite.Integer(nullable=False)
    amount: Sale.Col[int] = sqlite.Integer(nullable=False)


@test(
    [
        Param(value=(index, wrapper), name=f"{operator}_{wrapper}")
        for index, operator in enumerate(("eq", "ne", "gt", "gte", "lt", "lte"))
        for wrapper in ("direct", "and", "or", "not")
    ],
    mark="fast",
)
def having_rejects_ungrouped_right_operand(case: tuple[int, str]) -> None:
    """Table membership does not make a right operand a grouping key."""

    predicate = (
        Sale.category.eq_col(Sale.amount),
        Sale.category.ne_col(Sale.amount),
        Sale.category.gt_col(Sale.amount),
        Sale.category.gte_col(Sale.amount),
        Sale.category.lt_col(Sale.amount),
        Sale.category.lte_col(Sale.amount),
    )[case[0]]
    if case[1] == "and":
        predicate = Sale.category.gt(0) & predicate
    elif case[1] == "or":
        predicate = Sale.category.gt(0) | predicate
    elif case[1] == "not":
        predicate = ~(Sale.category.gt(0) & predicate)

    with assert_raises(QueryConstructionError) as caught:
        sqlite.select(Sale.category).all().group_by(Sale.category).having(predicate)

    assert_in("not grouped or aggregated", str(caught.exception))


@test(mark="fast")
def having_accepts_both_grouped_operands() -> None:
    """Grouped right operands compile without changing comparison SQL."""

    query = (
        sqlite.select(Sale.category, Sale.amount)
        .all()
        .group_by(Sale.category, Sale.amount)
        .having(Sale.category.gt_col(Sale.amount))
    )

    assert_in('HAVING ("category" > "amount") | params=()', repr(query))


@test(mark="fast")
def having_checks_table_membership_separately_from_grouping() -> None:
    """An unknown right-hand table fails scope validation before grouping."""

    class Other[S = sqlite.Pending](sqlite.Model[S, "Other[sqlite.Fetched]"]):
        """An unrelated table absent from the query."""

        amount: Other.Col[int] = sqlite.Integer(nullable=False)

    with assert_raises(QueryConstructionError) as caught:
        sqlite.select(Sale.category).all().group_by(Sale.category).having(
            Sale.category.gt_col(Other.amount)
        )

    assert_in("table that is not in the query", str(caught.exception))


@test(mark="medium")
async def grouped_column_comparison_filters_groups() -> None:
    """SQLite executes a valid comparison between two grouping keys."""

    async with await initialized_database(
        database=":memory:", models=[Sale]
    ) as database:
        async with database.transaction() as setup:
            await setup.execute(sqlite.insert(Sale(category=1, amount=2)))
            await setup.execute(sqlite.insert(Sale(category=1, amount=2)))
            await setup.execute(sqlite.insert(Sale(category=2, amount=1)))

        query = (
            sqlite.select(Sale.category, Sale.amount)
            .all()
            .group_by(Sale.category, Sale.amount)
            .having(Sale.category.lt_col(Sale.amount))
        )
        async with database.transaction() as tx:
            rows = await tx.fetch_all(query)

    assert_eq(rows, [(1, 2)])


@test(mark="medium")
async def having_scalar_subquery_keeps_its_own_column_scope() -> None:
    """Inner ungrouped columns do not become outer HAVING grouping operands."""

    class Detail[S = sqlite.Pending](sqlite.Model[S, "Detail[sqlite.Fetched]"]):
        """A correlated inner source with its own non-grouped columns."""

        category: Detail.Col[int] = sqlite.Integer(nullable=False)
        amount: Detail.Col[int] = sqlite.Integer(nullable=False)

    async with await initialized_database(
        database=":memory:", models=[Sale, Detail]
    ) as database:
        async with database.transaction() as setup:
            await setup.execute(sqlite.insert(Sale(category=1, amount=10)))
            await setup.execute(sqlite.insert(Sale(category=2, amount=10)))
            await setup.execute(sqlite.insert(Detail(category=1, amount=2)))
            await setup.execute(sqlite.insert(Detail(category=2, amount=1)))

        inner = sqlite.scalar(
            sqlite.select(Detail.amount.max()).where(
                Detail.category.eq_col(Sale.category)
            )
        )
        query = (
            sqlite.select(Sale.category)
            .all()
            .group_by(Sale.category)
            .having(Sale.category.lt_col(inner))
        )
        async with database.transaction() as tx:
            rows = await tx.fetch_all(query)

    assert_eq(rows, [1])

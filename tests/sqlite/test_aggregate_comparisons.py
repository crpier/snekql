"""Aggregate comparison operands obey HAVING scope and clause rules."""

from typing import ClassVar

from snektest import Param, assert_eq, assert_in, assert_raises, test

from snekql import sqlite
from tests.helpers import initialized_database


class Totals[S = sqlite.Pending](sqlite.Model[S]):
    """Two independently aggregated measurements."""

    __row_type__: ClassVar[sqlite.ReadType[Totals[sqlite.Row]]]

    category: Totals.Col[int] = sqlite.Integer()
    left: Totals.Col[int] = sqlite.Integer()
    right: Totals.Col[int] = sqlite.Integer()


@test(
    [
        Param(value=operator, name=operator)
        for operator in ("eq", "ne", "gt", "gte", "lt", "lte")
    ],
    mark="fast",
)
def aggregate_rhs_compiles(operator: str) -> None:
    """Every column comparison renders an aggregate right operand."""
    left = Totals.left.sum()
    right = Totals.right.sum()
    predicates = {
        "eq": left.eq_col(right),
        "ne": left.ne_col(right),
        "gt": left.gt_col(right),
        "gte": left.gte_col(right),
        "lt": left.lt_col(right),
        "lte": left.lte_col(right),
    }
    symbols = {"eq": "=", "ne": "!=", "gt": ">", "gte": ">=", "lt": "<", "lte": "<="}

    compiled = sqlite.select(left).having(predicates[operator]).compile()

    assert_in(f'HAVING (SUM("left") {symbols[operator]} SUM("right"))', compiled.sql)
    assert_eq(compiled.params, ())


@test(mark="fast")
def aggregate_rhs_rejected_in_where() -> None:
    """Aggregate rendering does not relax WHERE clause validation."""
    with assert_raises(sqlite.QueryConstructionError):
        sqlite.select(Totals.left).where(
            Totals.left.eq_col(Totals.right.sum())
        ).compile()


@test(mark="medium")
async def aggregate_comparison_filters_groups() -> None:
    """Totals are compared per group rather than as individual rows."""
    async with await initialized_database(
        database=":memory:", models=[Totals]
    ) as database:
        async with database.transaction() as setup:
            await setup.execute(sqlite.insert(Totals(category=1, left=3, right=1)))
            await setup.execute(sqlite.insert(Totals(category=1, left=1, right=2)))
            await setup.execute(sqlite.insert(Totals(category=2, left=1, right=2)))

        query = (
            sqlite.select(Totals.category)
            .group_by(Totals.category)
            .having(Totals.left.sum().gt_col(Totals.right.sum()))
        )
        async with database.transaction() as transaction:
            rows = await transaction.fetch_all(query)

    assert_eq(rows, [1])


class OtherTotals[S = sqlite.Pending](sqlite.Model[S]):
    """A source outside the selected table's scope."""

    __row_type__: ClassVar[sqlite.ReadType[OtherTotals[sqlite.Row]]]

    amount: OtherTotals.Col[int] = sqlite.Integer()


@test(mark="fast")
def aggregate_rhs_rejected_outside_scope() -> None:
    """HAVING cannot reference an aggregate from an invisible source."""
    with assert_raises(sqlite.QueryConstructionError):
        sqlite.select(Totals.left.sum()).having(
            Totals.left.sum().eq_col(OtherTotals.amount.sum())
        ).compile()


@test(mark="fast")
def aggregate_lhs_does_not_hide_ungrouped_rhs() -> None:
    """A bare right column still requires grouping."""
    with assert_raises(sqlite.QueryConstructionError):
        sqlite.select(Totals.left.sum()).having(
            Totals.left.sum().eq_col(Totals.right)
        ).compile()


@test(mark="fast")
def aggregate_rhs_rejected_in_join() -> None:
    """JOIN predicates cannot introduce aggregate operands."""
    with assert_raises(sqlite.QueryConstructionError):
        sqlite.select(Totals.left).join(
            OtherTotals, on=Totals.left.eq_col(OtherTotals.amount.sum())
        ).compile()

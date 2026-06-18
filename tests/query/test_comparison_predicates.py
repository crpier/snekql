"""Ordered-comparison and range predicate compilation and execution tests.

`gt`/`gte`/`lt`/`lte` render `> >= < <=` against a single placeholder, and
`between` renders `BETWEEN ? AND ?` with both bounds in order. They compose with
`&`/`|`/`~` and qualify columns across joins exactly like existing predicates.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import cast

from snektest import assert_eq, assert_raises, test

from snekql import sqlite
from snekql.sqlite import (
    MISSING,
    Database,
    Fetched,
    Integer,
    Model,
    Pending,
    Predicate,
    QueryCompilationError,
    QueryConstructionError,
    insert,
    select,
)
from snekql.sqlite.query import compile_sqlite_select_sql
from tests.helpers import NULL_LOGGER


class Reading[S = Pending](Model[S, "Reading[Fetched]"]):
    """Single table used by comparison compilation checks."""

    id: Reading.GenCol[int] = Integer(primary_key=True, default=MISSING)
    value: Reading.Col[int] = Integer(nullable=False)


@test(mark="fast")
def comparison_operators_render_expected_sql_and_params() -> None:
    """Each ordered operator emits its symbol against a single placeholder."""

    cases = {
        Reading.value.gt(5): ">",
        Reading.value.gte(5): ">=",
        Reading.value.lt(5): "<",
        Reading.value.lte(5): "<=",
    }

    for predicate, operator in cases.items():
        sql, params = compile_sqlite_select_sql(select(Reading).where(predicate))
        expected = f'SELECT "id", "value" FROM "reading" WHERE ("value" {operator} ?)'
        assert_eq(sql, expected)
        assert_eq(params, (5,))


@test(mark="fast")
def between_renders_two_ordered_placeholders() -> None:
    """`between` emits BETWEEN ? AND ? with the bounds in argument order."""

    sql, params = compile_sqlite_select_sql(
        select(Reading).where(Reading.value.between(1, 10)),
    )

    expected = 'SELECT "id", "value" FROM "reading" WHERE ("value" BETWEEN ? AND ?)'
    assert_eq(sql, expected)
    assert_eq(params, (1, 10))


@test(mark="fast")
def comparison_predicates_compose_with_boolean_operators() -> None:
    """Comparisons combine under `&`/`|`/`~` like every other predicate."""

    predicate = (Reading.value.gte(1) & Reading.value.lt(10)) | ~Reading.value.gt(100)

    sql, params = compile_sqlite_select_sql(select(Reading).where(predicate))

    expected = (
        'SELECT "id", "value" FROM "reading" '
        'WHERE ((("value" >= ?) AND ("value" < ?)) OR (NOT ("value" > ?)))'
    )
    assert_eq(sql, expected)
    assert_eq(params, (1, 10, 100))


@test(mark="fast")
def comparison_predicates_qualify_columns_across_joins() -> None:
    """Joined selects qualify comparison and range columns with their table."""

    class User[S = Pending](sqlite.Model[S, "User[Fetched]"]):
        """Referenced table."""

        id: User.GenCol[int] = sqlite.Integer(primary_key=True, default=MISSING)

    class Order[S = Pending](sqlite.Model[S, "Order[Fetched]"]):
        """Table with a foreign key to ``User`` and a numeric column."""

        id: Order.GenCol[int] = sqlite.Integer(primary_key=True, default=MISSING)
        user_id: Order.FKCol[User, int] = sqlite.ForeignKey(User.id)
        total: Order.Col[int] = sqlite.Integer(nullable=False)

    sql, params = compile_sqlite_select_sql(
        select(User)
        .join(Order, on=Order.user_id.references(User.id))
        .where(Order.total.gt(10) & Order.total.between(1, 100)),
    )

    expected = " ".join(
        [
            'SELECT "user"."id", "order"."id", "order"."user_id", "order"."total"',
            'FROM "user"',
            'INNER JOIN "order" ON "order"."user_id" = "user"."id"',
            'WHERE (("order"."total" > ?) AND',
            '("order"."total" BETWEEN ? AND ?))',
        ],
    )
    assert_eq(sql, expected)
    assert_eq(params, (10, 1, 100))


@test(mark="fast")
def comparison_predicates_reject_none_arguments() -> None:
    """None bounds are rejected up front, steering users at the null predicates."""

    value_gt = cast("Callable[[object], object]", Reading.value.gt)
    value_lte = cast("Callable[[object], object]", Reading.value.lte)
    value_between = cast("Callable[..., object]", Reading.value.between)

    with assert_raises(QueryConstructionError):
        _ = value_gt(None)

    with assert_raises(QueryConstructionError):
        _ = value_lte(None)

    with assert_raises(QueryConstructionError):
        _ = value_between(None, 5)

    with assert_raises(QueryConstructionError):
        _ = value_between(1, None)


@test(mark="medium")
async def comparison_predicates_filter_rows_end_to_end() -> None:
    """A BETWEEN filter selects only the in-range rows through the runtime."""

    database = await Database.initialize(
        logger=NULL_LOGGER, database=":memory:", models=[Reading]
    )
    try:
        async with database.transaction() as tx:
            for amount in (1, 5, 10, 15):
                await tx.execute(insert(Reading(value=amount)))
            in_range = await tx.fetch_all(
                select(Reading.value)
                .where(Reading.value.between(5, 10))
                .order_by(Reading.value.asc()),
            )
            above = await tx.fetch_all(
                select(Reading.value)
                .where(Reading.value.gt(10))
                .order_by(Reading.value.asc()),
            )
    finally:
        await database.close()

    assert_eq(in_range, [5, 10])
    assert_eq(above, [15])


@test(mark="fast")
def comparison_compilation_rejects_none_carried_into_predicate() -> None:
    """A None value reaching compilation is rejected with a null-predicate hint."""

    raw_gt: Predicate[Reading] = Predicate(kind="gt", column=Reading.value, value=None)
    raw_between: Predicate[Reading] = Predicate(
        kind="between", column=Reading.value, values=(1, None)
    )

    with assert_raises(QueryCompilationError):
        _ = compile_sqlite_select_sql(select(Reading).where(raw_gt))

    with assert_raises(QueryCompilationError):
        _ = compile_sqlite_select_sql(select(Reading).where(raw_between))

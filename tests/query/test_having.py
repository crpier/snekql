"""Grouped aggregation: HAVING filters groups by aggregate or grouped column.

Slice 3 of the aggregation epic (#113). Builds on slice 2's ``GROUP BY`` +
tuple projection: ``having(...)`` filters the grouped rows, targeting either an
aggregate (``User.id.count().gt(5)``) or a grouped column. The comparison
methods are shared between columns and aggregates by a common ``Comparable``
mixin, so ``HAVING`` predicates build exactly like ``WHERE`` predicates.
"""

from __future__ import annotations

from typing import ClassVar

from snektest import assert_eq, assert_raises, test

from snekql import mariadb, sqlite
from snekql.sqlite import (
    PENDING_GENERATION,
    Pending,
    QueryConstructionError,
    Row,
    insert,
    select,
)
from tests.helpers import initialized_database
from tests.query.aggregate_models import MariaUser


class User[S = Pending](sqlite.Model[S]):
    """Base table with a groupable column for HAVING tests."""

    __row_type__: ClassVar[sqlite.ReadType[User[Row]]]

    id: User.GenCol[int] = sqlite.Integer(
        primary_key=True,
        auto_increment=True,
        default=PENDING_GENERATION,
    )
    country: User.Col[str] = sqlite.Text(nullable=False)


class Order[S = Pending](sqlite.Model[S]):
    """Table with a numeric column to aggregate per group under a join."""

    __row_type__: ClassVar[sqlite.ReadType[Order[Row]]]

    id: Order.GenCol[int] = sqlite.Integer(
        primary_key=True,
        auto_increment=True,
        default=PENDING_GENERATION,
    )
    user_id: Order.FKCol[User, int] = sqlite.ForeignKey(User.id)
    amount: Order.Col[int] = sqlite.Integer(nullable=False)


@test(mark="fast")
def having_renders_between_group_by_and_order_by() -> None:
    """Clause order is WHERE -> GROUP BY -> HAVING -> ORDER BY."""

    compiled = (
        select(User.country, User.id.count())
        .where(User.id.gt(0))
        .group_by(User.country)
        .having(User.id.count().gt(1))
        .order_by(User.country.asc())
        .compile()
    )

    expected = " ".join(
        [
            'SELECT "country", COUNT("id") FROM "user"',
            'WHERE ("id" > ?) GROUP BY "country"',
            'HAVING (COUNT("id") > ?) ORDER BY "country" ASC',
        ],
    )
    assert_eq(compiled.sql, expected)
    assert_eq(compiled.params, (0, 1))


@test(mark="fast")
def having_over_an_aggregate_renders_the_function() -> None:
    """A HAVING predicate over an aggregate renders ``FUNC(col)`` as its LHS."""

    compiled = (
        select(User.country, User.id.count())
        .group_by(User.country)
        .having(User.id.count().gt(5))
        .compile()
    )

    expected = 'SELECT "country", COUNT("id") FROM "user" GROUP BY "country" HAVING (COUNT("id") > ?)'
    assert_eq(compiled.sql, expected)
    assert_eq(compiled.params, (5,))


@test(mark="fast")
def having_over_a_grouped_column_renders_the_column() -> None:
    """A HAVING predicate may target a grouped column instead of an aggregate."""

    compiled = (
        select(User.country, User.id.count())
        .group_by(User.country)
        .having(User.country.ne("antarctica"))
        .compile()
    )

    expected = 'SELECT "country", COUNT("id") FROM "user" GROUP BY "country" HAVING ("country" != ?)'
    assert_eq(compiled.sql, expected)
    assert_eq(compiled.params, ("antarctica",))


@test(mark="fast")
def having_qualifies_aggregates_under_a_join() -> None:
    """A joined HAVING aggregate qualifies the wrapped column with its table."""

    compiled = (
        select(User.country, Order.amount.sum())
        .join(Order, on=Order.user_id.references(User.id))
        .group_by(User.country)
        .having(Order.amount.sum().gt(10))
        .compile()
    )

    expected = " ".join(
        [
            'SELECT "user"."country", SUM("order"."amount") FROM "user"',
            'INNER JOIN "order" ON "order"."user_id" = "user"."id"',
            'GROUP BY "user"."country" HAVING (SUM("order"."amount") > ?)',
        ],
    )
    assert_eq(compiled.sql, expected)
    assert_eq(compiled.params, (10,))


@test(mark="fast")
def having_is_backend_portable() -> None:
    """HAVING is identical SQL in MariaDB save for identifier quoting."""

    compiled = (
        mariadb.select(MariaUser.country, MariaUser.id.count())
        .group_by(MariaUser.country)
        .having(MariaUser.id.count().gt(5))
        .compile()
    )

    assert_eq(
        compiled.sql,
        " ".join(
            [
                "SELECT `country`, COUNT(`id`) FROM `user`",
                "GROUP BY `country` HAVING (COUNT(`id`) > %s)",
            ],
        ),
    )
    assert_eq(compiled.params, (5,))
    assert_eq(compiled.backend, "mariadb")


@test(mark="fast")
def having_over_an_ungrouped_bare_column_is_a_construction_error() -> None:
    """Filtering a non-grouped, non-aggregate column in HAVING is rejected."""

    with assert_raises(QueryConstructionError):
        _ = (
            select(User.country, User.id.count())
            .group_by(User.country)
            .having(User.id.gt(5))
        )


@test(mark="fast")
def aggregates_are_rejected_in_where() -> None:
    """An aggregate predicate belongs in HAVING, not WHERE."""

    with assert_raises(QueryConstructionError):
        _ = select(User.country, User.id.count()).where(User.id.count().gt(5))


@test(mark="medium")
async def having_filters_groups_at_runtime() -> None:
    """HAVING keeps only the groups whose aggregate satisfies the predicate."""

    database = await initialized_database(database=":memory:", models=[User])
    try:
        async with database.transaction() as tx:
            await tx.execute(insert(User(country="us")))
            await tx.execute(insert(User(country="us")))
            await tx.execute(insert(User(country="ca")))
            rows = await tx.fetch_all(
                select(User.country, User.id.count())
                .group_by(User.country)
                .having(User.id.count().gt(1))
                .order_by(User.country.asc()),
            )
    finally:
        await database.close()

    assert_eq(rows, [("us", 2)])


@test(mark="medium")
async def having_over_a_sum_filters_per_group() -> None:
    """A HAVING over SUM compares the per-group total decoded to int."""

    database = await initialized_database(database=":memory:", models=[User, Order])
    try:
        async with database.transaction() as tx:
            await tx.execute(insert(User(country="us")))
            await tx.execute(insert(User(country="ca")))
            await tx.execute(insert(Order(user_id=1, amount=3)))
            await tx.execute(insert(Order(user_id=1, amount=4)))
            await tx.execute(insert(Order(user_id=2, amount=5)))
            rows = await tx.fetch_all(
                select(User.country, Order.amount.sum())
                .join(Order, on=Order.user_id.references(User.id))
                .group_by(User.country)
                .having(Order.amount.sum().gt(5))
                .order_by(User.country.asc()),
            )
    finally:
        await database.close()

    assert_eq(rows, [("us", 7)])

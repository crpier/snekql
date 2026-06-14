"""Grouped aggregation: GROUP BY with mixed column/aggregate tuple projection.

Slice 2 of the aggregation epic (#112). Builds on the ungrouped scalar
aggregates from slice 1: ``select(User.country, User.id.count())`` projects a
``(group key, aggregate)`` tuple, ``group_by(User.country)`` collapses rows per
group, and every non-aggregate projected column must appear in ``group_by``.
``HAVING`` is slice 3 (#113).
"""

from __future__ import annotations

from snektest import assert_eq, assert_raises, test

from snekql import (
    MISSING,
    Database,
    Fetched,
    Pending,
    QueryCompilationError,
    QueryConstructionError,
    insert,
    select,
    sqlite,
)
from snekql.mariadb.query import compile_mariadb_select_sql
from snekql.sqlite.query import compile_sqlite_select_sql
from tests.helpers import NULL_LOGGER


class User[S = Pending](sqlite.Model[S, "User[Fetched]"]):
    """Base table with a groupable column for GROUP BY tests."""

    id: User.GenCol[int] = sqlite.Integer(
        primary_key=True,
        auto_increment=True,
        default=MISSING,
    )
    country: User.Col[str] = sqlite.Text(nullable=False)


class Order[S = Pending](sqlite.Model[S, "Order[Fetched]"]):
    """Table with a numeric column to aggregate per group under a join."""

    id: Order.GenCol[int] = sqlite.Integer(
        primary_key=True,
        auto_increment=True,
        default=MISSING,
    )
    user_id: Order.FKCol[User, int] = sqlite.ForeignKey(User.id)
    amount: Order.Col[int] = sqlite.Integer(nullable=False)


@test(mark="fast")
def group_by_renders_between_where_and_order_by() -> None:
    """GROUP BY sits between WHERE and ORDER BY in the compiled clause order."""

    sql, params = compile_sqlite_select_sql(
        select(User.country, User.id.count())
        .where(User.id.gt(0))
        .group_by(User.country)
        .order_by(User.country.asc()),
    )

    expected = " ".join(
        [
            'SELECT "country", COUNT("id") FROM "user"',
            'WHERE ("id" > ?) GROUP BY "country" ORDER BY "country" ASC',
        ],
    )
    assert_eq(sql, expected)
    assert_eq(params, (0,))


@test(mark="fast")
def mixed_projection_compiles_to_group_key_and_aggregate() -> None:
    """A bare column and an aggregate project together under GROUP BY."""

    sql, params = compile_sqlite_select_sql(
        select(User.country, User.id.count()).group_by(User.country).all(),
    )

    assert_eq(sql, 'SELECT "country", COUNT("id") FROM "user" GROUP BY "country"')
    assert_eq(params, ())


@test(mark="fast")
def group_by_qualifies_columns_under_a_join() -> None:
    """Joined grouped projections qualify both the key and the aggregate."""

    sql, _ = compile_sqlite_select_sql(
        select(User.country, Order.amount.sum())
        .join(Order, on=Order.user_id.references(User.id))
        .group_by(User.country)
        .all(),
    )

    expected = " ".join(
        [
            'SELECT "user"."country", SUM("order"."amount") FROM "user"',
            'INNER JOIN "order" ON "order"."user_id" = "user"."id"',
            'GROUP BY "user"."country"',
        ],
    )
    assert_eq(sql, expected)


@test(mark="fast")
def aggregate_renders_in_order_by_position() -> None:
    """An aggregate can drive ORDER BY in a grouped query."""

    sql, _ = compile_sqlite_select_sql(
        select(User.country, User.id.count())
        .group_by(User.country)
        .order_by(User.id.count().desc())
        .all(),
    )

    expected = " ".join(
        [
            'SELECT "country", COUNT("id") FROM "user"',
            'GROUP BY "country" ORDER BY COUNT("id") DESC',
        ],
    )
    assert_eq(sql, expected)


@test(mark="fast")
def group_by_is_backend_portable() -> None:
    """GROUP BY is identical SQL in MariaDB save for identifier quoting."""

    assert_eq(
        compile_mariadb_select_sql(
            select(User.country, User.id.count()).group_by(User.country).all(),
        )[0],
        "SELECT `country`, COUNT(`id`) FROM `user` GROUP BY `country`",
    )


@test(mark="fast")
def ungrouped_bare_column_with_aggregate_is_a_compilation_error() -> None:
    """A non-aggregate projected column not in GROUP BY is rejected."""

    with assert_raises(QueryCompilationError):
        _ = compile_sqlite_select_sql(
            select(User.country, User.id.count()).all(),
        )


@test(mark="fast")
def grouping_by_an_unjoined_table_is_a_construction_error() -> None:
    """Grouping by a column from a table not in scope is rejected."""

    with assert_raises(QueryConstructionError):
        _ = select(User.country, Order.amount.sum()).group_by(Order.amount)


@test(mark="medium")
async def grouped_count_returns_a_count_per_group() -> None:
    """A grouped COUNT(*) fetches one (key, count) tuple per group."""

    database = await Database.initialize(
        logger=NULL_LOGGER, database=":memory:", models=[User]
    )
    try:
        async with database.transaction() as tx:
            await tx.execute(insert(User(country="us")))
            await tx.execute(insert(User(country="us")))
            await tx.execute(insert(User(country="ca")))
            rows = await tx.fetch_all(
                select(User.country, User.id.count())
                .group_by(User.country)
                .order_by(User.country.asc())
                .all(),
            )
    finally:
        await database.close()

    assert_eq(rows, [("ca", 1), ("us", 2)])


@test(mark="medium")
async def grouped_sum_normalizes_per_group() -> None:
    """A grouped SUM over an Integer column decodes to int per group."""

    database = await Database.initialize(
        logger=NULL_LOGGER, database=":memory:", models=[User, Order]
    )
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
                .order_by(User.country.asc())
                .all(),
            )
    finally:
        await database.close()

    assert_eq(rows, [("ca", 5), ("us", 7)])
    assert all(isinstance(total, int) for _, total in rows)

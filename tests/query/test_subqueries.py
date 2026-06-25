"""Subquery support: column comparison, IN/EXISTS, and scalar subqueries (#118).

A select can now be nested inside another query. The building blocks are:

- Column-to-column comparison (``Order.user_id.eq_col(User.id)``), the predicate
  shape a correlated subquery needs to relate its inner row to the outer row.
- ``IN (subquery)`` / ``NOT IN (subquery)`` against a single-column select.
- ``exists(subquery)`` / ``not_exists(subquery)``, including correlated cases.
- ``scalar(subquery)`` usable in a projection or as a comparison operand.

Parameter ordering follows textual SQL order so inner and outer placeholders stay
aligned on both SQLite and MariaDB.
"""

from __future__ import annotations

from snektest import assert_eq, assert_raises, test

from snekql import sqlite
from snekql.mariadb.query import compile_mariadb_select_sql
from snekql.sqlite import (
    PENDING_GENERATION,
    Fetched,
    Pending,
    QueryCompilationError,
    QueryConstructionError,
    exists,
    insert,
    not_exists,
    scalar,
    select,
)
from snekql.sqlite.query import compile_sqlite_select_sql
from tests.helpers import initialized_database


class User[S = Pending](sqlite.Model[S, "User[Fetched]"]):
    """Outer table for subquery tests."""

    id: User.GenCol[int] = sqlite.Integer(
        primary_key=True,
        auto_increment=True,
        default=PENDING_GENERATION,
    )
    country: User.Col[str] = sqlite.Text(nullable=False)


class Order[S = Pending](sqlite.Model[S, "Order[Fetched]"]):
    """Inner table with a foreign key back to ``User``."""

    id: Order.GenCol[int] = sqlite.Integer(
        primary_key=True,
        auto_increment=True,
        default=PENDING_GENERATION,
    )
    user_id: Order.FKCol[User, int] = sqlite.ForeignKey(User.id)
    amount: Order.Col[int] = sqlite.Integer(nullable=False)


# --- Slice 1: column-to-column comparison -----------------------------------


@test(mark="fast")
def column_comparison_renders_both_columns() -> None:
    """``eq_col`` compares two columns instead of a column against a value."""

    sql, params = compile_sqlite_select_sql(
        select(Order.id)
        .join(User, on=Order.user_id.references(User.id))
        .where(Order.amount.gt_col(User.id)),
    )

    expected = " ".join(
        [
            'SELECT "order"."id" FROM "order"',
            'INNER JOIN "user" ON "order"."user_id" = "user"."id"',
            'WHERE ("order"."amount" > "user"."id")',
        ],
    )
    assert_eq(sql, expected)
    assert_eq(params, ())


@test(mark="fast")
def column_comparison_against_unscoped_table_is_a_compilation_error() -> None:
    """Comparing against a column whose table is not in scope fails at compile."""

    query = select(Order.id).where(Order.amount.eq_col(User.id))
    with assert_raises(QueryCompilationError):
        _ = compile_sqlite_select_sql(query)


# --- Slice 2: IN / NOT IN subquery ------------------------------------------


@test(mark="fast")
def in_subquery_renders_nested_select() -> None:
    """``in_subquery`` nests a single-column select as the membership set."""

    sql, params = compile_sqlite_select_sql(
        select(User.id).where(
            User.id.in_subquery(select(Order.user_id).where(Order.amount.gt(100))),
        ),
    )

    expected = " ".join(
        [
            'SELECT "id" FROM "user" WHERE',
            '("id" IN (SELECT "order"."user_id" FROM "order"',
            'WHERE ("order"."amount" > ?)))',
        ],
    )
    assert_eq(sql, expected)
    assert_eq(params, (100,))


@test(mark="fast")
def not_in_subquery_renders_negated_membership() -> None:
    """``not_in_subquery`` emits ``NOT IN`` against the nested select."""

    sql, _params = compile_sqlite_select_sql(
        select(User.id).where(
            User.id.not_in_subquery(select(Order.user_id).all()),
        ),
    )

    assert_eq(
        sql,
        'SELECT "id" FROM "user" WHERE ("id" NOT IN (SELECT "order"."user_id" FROM "order"))',
    )


@test(mark="fast")
def in_subquery_requires_single_column_select() -> None:
    """A model select projects every column, so it is rejected as an IN set."""

    with assert_raises(QueryConstructionError):
        _ = select(User.id).where(User.id.in_subquery(select(Order)))  # type: ignore[arg-type]


# --- Slice 3: EXISTS / NOT EXISTS (correlated) ------------------------------


@test(mark="fast")
def correlated_exists_threads_outer_column() -> None:
    """A correlated EXISTS references the outer row via a column comparison."""

    sql, params = compile_sqlite_select_sql(
        select(User.id).where(
            exists(
                select(Order.id)
                .where(Order.user_id.eq_col(User.id))
                .where(Order.amount.gt(10)),
            ),
        ),
    )

    expected = " ".join(
        [
            'SELECT "id" FROM "user" WHERE (EXISTS (SELECT "order"."id"',
            'FROM "order" WHERE ("order"."user_id" = "user"."id")',
            'AND ("order"."amount" > ?)))',
        ],
    )
    assert_eq(sql, expected)
    assert_eq(params, (10,))


@test(mark="fast")
def not_exists_negates_the_subquery() -> None:
    """``not_exists`` emits ``NOT EXISTS`` around the nested select."""

    sql, _params = compile_sqlite_select_sql(
        select(User.id).where(
            not_exists(select(Order.id).where(Order.user_id.eq_col(User.id))),
        ),
    )

    expected = " ".join(
        [
            'SELECT "id" FROM "user" WHERE (NOT EXISTS (SELECT "order"."id"',
            'FROM "order" WHERE ("order"."user_id" = "user"."id")))',
        ],
    )
    assert_eq(sql, expected)


@test(mark="fast")
def exists_correlation_to_unscoped_table_is_a_compilation_error() -> None:
    """A correlated reference to a table in neither scope fails at compile."""

    query = select(Order.id).where(
        exists(select(Order.id).where(Order.user_id.eq_col(User.id))),
    )
    with assert_raises(QueryCompilationError):
        _ = compile_sqlite_select_sql(query)


# --- Slice 4: scalar subqueries ---------------------------------------------


@test(mark="fast")
def scalar_subquery_in_projection_renders_parenthesized_select() -> None:
    """A scalar subquery projects a single value alongside ordinary columns."""

    sql, params = compile_sqlite_select_sql(
        select(
            User.id,
            scalar(
                select(Order.amount.sum()).where(Order.user_id.eq_col(User.id)),
            ),
        ).all(),
    )

    expected = " ".join(
        [
            'SELECT "id", (SELECT SUM("order"."amount") FROM "order"',
            'WHERE ("order"."user_id" = "user"."id")) FROM "user"',
        ],
    )
    assert_eq(sql, expected)
    assert_eq(params, ())


@test(mark="fast")
def scalar_subquery_as_comparison_operand() -> None:
    """A scalar subquery can stand in as a comparison operand."""

    sql, params = compile_sqlite_select_sql(
        select(Order.id).where(
            Order.amount.gt_col(scalar(select(Order.amount.avg()).all())),
        ),
    )

    expected = " ".join(
        [
            'SELECT "id" FROM "order" WHERE',
            '("amount" > (SELECT AVG("order"."amount") FROM "order"))',
        ],
    )
    assert_eq(sql, expected)
    assert_eq(params, ())


@test(mark="fast")
def scalar_requires_single_column_select() -> None:
    """A scalar subquery must project exactly one column."""

    with assert_raises(QueryConstructionError):
        _ = scalar(select(User))  # type: ignore[arg-type]


# --- Backend portability ----------------------------------------------------


@test(mark="fast")
def subqueries_are_backend_portable() -> None:
    """Nested SQL matches MariaDB save for quoting and placeholders."""

    sql, params = compile_mariadb_select_sql(
        select(User.id).where(
            User.id.in_subquery(select(Order.user_id).where(Order.amount.gt(100))),
        ),
    )

    expected = " ".join(
        [
            "SELECT `id` FROM `user` WHERE",
            "(`id` IN (SELECT `order`.`user_id` FROM `order`",
            "WHERE (`order`.`amount` > %s)))",
        ],
    )
    assert_eq(sql, expected)
    assert_eq(params, (100,))


# --- Runtime ----------------------------------------------------------------


@test(mark="medium")
async def in_subquery_filters_rows_at_runtime() -> None:
    """IN against a subquery keeps only the correlated outer rows."""

    database = await initialized_database(database=":memory:", models=[User, Order])
    try:
        async with database.transaction() as tx:
            await tx.execute(insert(User(country="us")))
            await tx.execute(insert(User(country="ca")))
            await tx.execute(insert(Order(user_id=1, amount=200)))
            rows = await tx.fetch_all(
                select(User.id)
                .where(
                    User.id.in_subquery(
                        select(Order.user_id).where(Order.amount.gt(100)),
                    ),
                )
                .order_by(User.id.asc()),
            )
    finally:
        await database.close()

    assert_eq(rows, [1])


@test(mark="medium")
async def correlated_exists_filters_rows_at_runtime() -> None:
    """A correlated EXISTS keeps outer rows that have a matching inner row."""

    database = await initialized_database(database=":memory:", models=[User, Order])
    try:
        async with database.transaction() as tx:
            await tx.execute(insert(User(country="us")))
            await tx.execute(insert(User(country="ca")))
            await tx.execute(insert(Order(user_id=1, amount=50)))
            rows = await tx.fetch_all(
                select(User.id)
                .where(
                    exists(
                        select(Order.id).where(Order.user_id.eq_col(User.id)),
                    ),
                )
                .order_by(User.id.asc()),
            )
    finally:
        await database.close()

    assert_eq(rows, [1])


@test(mark="medium")
async def scalar_subquery_projects_per_row_value() -> None:
    """A correlated scalar subquery projects a per-outer-row aggregate."""

    database = await initialized_database(database=":memory:", models=[User, Order])
    try:
        async with database.transaction() as tx:
            await tx.execute(insert(User(country="us")))
            await tx.execute(insert(User(country="ca")))
            await tx.execute(insert(Order(user_id=1, amount=3)))
            await tx.execute(insert(Order(user_id=1, amount=4)))
            rows = await tx.fetch_all(
                select(
                    User.id,
                    scalar(
                        select(Order.amount.sum()).where(
                            Order.user_id.eq_col(User.id),
                        ),
                    ),
                )
                .all()
                .order_by(User.id.asc()),
            )
    finally:
        await database.close()

    assert_eq(rows, [(1, 7), (2, None)])

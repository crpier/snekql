"""Model-select join SQL compilation contract tests.

A joined select renders table-qualified column names, a `FROM` anchor, and one
`[INNER|LEFT] JOIN <table> ON <fk> = <target>` clause per join. Cross-table
`where`/`order_by` columns are qualified the same way.
"""

from __future__ import annotations

from snektest import assert_eq, test

from snekql import sqlite
from snekql.sqlite import MISSING, Fetched, Pending, select
from snekql.sqlite.query import compile_sqlite_select_sql


class User[S = Pending](sqlite.Model[S, "User[Fetched]"]):
    """Referenced table."""

    id: User.GenCol[int] = sqlite.Integer(
        primary_key=True,
        auto_increment=True,
        default=MISSING,
    )
    email: User.Col[str] = sqlite.Text(nullable=False)


class Order[S = Pending](sqlite.Model[S, "Order[Fetched]"]):
    """Table with a foreign key to ``User``."""

    id: Order.GenCol[int] = sqlite.Integer(
        primary_key=True,
        auto_increment=True,
        default=MISSING,
    )
    user_id: Order.FKCol[User, int] = sqlite.ForeignKey(User.id)
    note: Order.Col[str] = sqlite.Text(nullable=False)


@test(mark="fast")
def inner_join_renders_qualified_columns_and_on_clause() -> None:
    """An inner join qualifies every column and emits one ON condition."""

    sql, params = compile_sqlite_select_sql(
        select(User).join(Order, on=Order.user_id.references(User.id)).all(),
    )

    expected = " ".join(
        [
            'SELECT "user"."id", "user"."email",',
            '"order"."id", "order"."user_id", "order"."note"',
            'FROM "user"',
            'INNER JOIN "order" ON "order"."user_id" = "user"."id"',
        ],
    )
    assert_eq(sql, expected)
    assert_eq(params, ())


@test(mark="fast")
def left_join_emits_left_join_keyword() -> None:
    """A left join renders the LEFT JOIN keyword."""

    sql, _params = compile_sqlite_select_sql(
        select(User).left_join(Order, on=Order.user_id.references(User.id)).all(),
    )

    on_clause = 'LEFT JOIN "order" ON "order"."user_id" = "user"."id"'
    assert on_clause in sql


@test(mark="fast")
def cross_table_where_and_order_by_are_qualified() -> None:
    """Predicate and ordering columns from any joined table are qualified."""

    sql, params = compile_sqlite_select_sql(
        select(User)
        .join(Order, on=Order.user_id.references(User.id))
        .where(User.email.eq("a@b.c") & Order.note.eq("x"))
        .order_by(Order.note.asc()),
    )

    expected = " ".join(
        [
            'SELECT "user"."id", "user"."email",',
            '"order"."id", "order"."user_id", "order"."note"',
            'FROM "user"',
            'INNER JOIN "order" ON "order"."user_id" = "user"."id"',
            'WHERE (("user"."email" = ?) AND ("order"."note" = ?))',
            'ORDER BY "order"."note" ASC',
        ],
    )
    assert_eq(sql, expected)
    assert_eq(params, ("a@b.c", "x"))


@test(mark="fast")
def projection_join_selects_only_the_projected_columns() -> None:
    """A projection join qualifies the projected columns and joins the table.

    Unlike a model-select join, the SELECT list stays the projected columns; the
    joined table contributes only to the FROM/JOIN graph, never the result.
    """

    sql, params = compile_sqlite_select_sql(
        select(User.email, Order.note)
        .join(Order, on=Order.user_id.references(User.id))
        .all(),
    )

    expected = " ".join(
        [
            'SELECT "user"."email", "order"."note"',
            'FROM "user"',
            'INNER JOIN "order" ON "order"."user_id" = "user"."id"',
        ],
    )
    assert_eq(sql, expected)
    assert_eq(params, ())


@test(mark="fast")
def projection_join_filters_a_joined_but_unprojected_table() -> None:
    """Filtering a joined table you do not project qualifies its predicate."""

    sql, params = compile_sqlite_select_sql(
        select(User.email)
        .join(Order, on=Order.user_id.references(User.id))
        .where(Order.note.eq("x")),
    )

    expected = " ".join(
        [
            'SELECT "user"."email"',
            'FROM "user"',
            'INNER JOIN "order" ON "order"."user_id" = "user"."id"',
            'WHERE ("order"."note" = ?)',
        ],
    )
    assert_eq(sql, expected)
    assert_eq(params, ("x",))

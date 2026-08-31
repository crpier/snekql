"""Runtime guards for join-scope validity not expressible in the type system.

Because `on=` is argument-order symmetric, a valid `JoinOn[A, B]` can satisfy a
`join(C, ...)` slot the type checker accepts. These construction-time checks
back-stop the static guarantees: every join must reference the joined table and
relate it to a table already in the FROM/JOIN graph.
"""

from __future__ import annotations

from typing import Any, cast

from snektest import assert_raises, test

from snekql import sqlite
from snekql.sqlite import (
    PENDING_GENERATION,
    Fetched,
    Pending,
    QueryConstructionError,
    select,
)


class User[S = Pending](sqlite.Model[S, "User[Fetched]"]):
    """Referenced root table."""

    id: User.GenCol[int] = sqlite.Integer(
        primary_key=True,
        auto_increment=True,
        default=PENDING_GENERATION,
    )
    email: User.Col[str] = sqlite.Text(nullable=False)


class Order[S = Pending](sqlite.Model[S, "Order[Fetched]"]):
    """Table with a foreign key to ``User``."""

    id: Order.GenCol[int] = sqlite.Integer(
        primary_key=True,
        auto_increment=True,
        default=PENDING_GENERATION,
    )
    user_id: Order.FKCol[User, int] = sqlite.ForeignKey(User.id)
    note: Order.Col[str] = sqlite.Text(nullable=False)


class Item[S = Pending](sqlite.Model[S, "Item[Fetched]"]):
    """Table with a foreign key to ``Order``."""

    id: Item.GenCol[int] = sqlite.Integer(
        primary_key=True,
        auto_increment=True,
        default=PENDING_GENERATION,
    )
    order_id: Item.FKCol[Order, int] = sqlite.ForeignKey(Order.id)


@test(mark="fast")
def join_rejects_a_condition_that_does_not_reference_the_joined_table() -> None:
    """The join condition must mention the table being joined."""

    query = cast("Any", select(User))

    with assert_raises(QueryConstructionError):
        _ = query.join(Item, on=Order.user_id.references(User.id))


@test(mark="fast")
def join_rejects_relating_to_a_table_that_is_not_yet_joined() -> None:
    """A join must relate its table to one already in the FROM/JOIN graph."""

    query = cast("Any", select(User))

    with assert_raises(QueryConstructionError):
        _ = query.join(Item, on=Item.order_id.references(Order.id))


@test(mark="fast")
def join_rejects_joining_a_table_twice() -> None:
    """A table already present in the query cannot be joined again."""

    query = cast("Any", select(User).join(Order, on=Order.user_id.references(User.id)))

    with assert_raises(QueryConstructionError):
        _ = query.join(Order, on=Order.user_id.references(User.id))


@test(mark="fast")
def where_rejects_a_plain_column_from_a_table_not_in_scope() -> None:
    """A where() predicate on a column whose table is not in the query is rejected.

    This pins the construction-time scope check for the common plain-column
    (``Attr``) operand -- the fast path that resolves the concrete column before
    the structural dialect-protocol check.
    """

    query = cast("Any", select(User))

    with assert_raises(QueryConstructionError):
        _ = query.where(Order.note.eq("x"))

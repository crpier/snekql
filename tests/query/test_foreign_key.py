"""Foreign-key column relationships and join-condition construction.

A foreign-key column declares the model it references in its annotation
(`Order.FKCol[User, int]`). Building a join condition from it
(`Order.user_id.references(User.id)`) produces a `JoinOn` carrier holding the
two related columns, which `join()`/`left_join()` later compile into an
`ON <fk> = <target>` clause.
"""

from __future__ import annotations

from snektest import assert_eq, test

from snekql import MISSING, Fetched, Pending, sqlite
from snekql.expressions import JoinOn


@test(mark="fast")
def references_builds_join_condition() -> None:
    """`references` carries the FK column and its target into a `JoinOn`."""

    class User[S = Pending](sqlite.Model[S, "User[Fetched]"]):
        """Referenced table."""

        id: User.GenCol[int] = sqlite.Integer(
            primary_key=True,
            auto_increment=True,
            default=MISSING,
        )
        email: User.Col[str] = sqlite.Text(nullable=False)

    class Order[S = Pending](sqlite.Model[S, "Order[Fetched]"]):
        """Table carrying a foreign key to ``User``."""

        id: Order.GenCol[int] = sqlite.Integer(
            primary_key=True,
            auto_increment=True,
            default=MISSING,
        )
        user_id: Order.FKCol[User, int] = sqlite.Integer(foreign_key=True)
        note: Order.Col[str] = sqlite.Text(nullable=False)

    condition = Order.user_id.references(User.id)

    assert isinstance(condition, JoinOn)
    assert_eq(condition.left_column, Order.user_id)
    assert_eq(condition.right_column, User.id)


@test(mark="fast")
def foreign_key_flag_is_recorded_on_the_descriptor() -> None:
    """`foreign_key=True` is stored for later DDL emission."""

    class Order[S = Pending](sqlite.Model[S, "Order[Fetched]"]):
        """Table with one FK column and one plain column."""

        user_id: Order.Col[int] = sqlite.Integer(foreign_key=True)
        note: Order.Col[str] = sqlite.Text(nullable=False)

    assert_eq(Order.user_id.foreign_key, True)
    assert_eq(Order.note.foreign_key, False)

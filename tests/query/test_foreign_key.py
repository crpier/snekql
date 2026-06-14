"""Foreign-key column relationships and join-condition construction.

A foreign-key column declares the model it references in its annotation
(`Order.FKCol[User, int]`). Building a join condition from it
(`Order.user_id.references(User.id)`) produces a `JoinOn` carrier holding the
two related columns, which `join()`/`left_join()` later compile into an
`ON <fk> = <target>` clause.
"""

from __future__ import annotations

from snektest import assert_eq, test

from snekql import MISSING, Fetched, ForeignKey, Pending, sqlite
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
        user_id: Order.FKCol[User, int] = ForeignKey(User.id)
        note: Order.Col[str] = sqlite.Text(nullable=False)

    condition = Order.user_id.references(User.id)

    assert isinstance(condition, JoinOn)
    assert_eq(condition.left_column, Order.user_id)
    assert_eq(condition.right_column, User.id)


@test(mark="fast")
def foreign_key_records_its_target_column_on_the_descriptor() -> None:
    """`ForeignKey` stores the referenced column for later DDL resolution."""

    class User[S = Pending](sqlite.Model[S, "User[Fetched]"]):
        """Referenced table whose primary key anchors the constraint."""

        id: User.GenCol[int] = sqlite.Integer(
            primary_key=True,
            auto_increment=True,
            default=MISSING,
        )

    class Order[S = Pending](sqlite.Model[S, "Order[Fetched]"]):
        """Table with one FK column and one plain column."""

        user_id: Order.FKCol[User, int] = ForeignKey(User.id)
        note: Order.Col[str] = sqlite.Text(nullable=False)

    assert_eq(Order.user_id.foreign_key_target, User.id)
    assert Order.note.foreign_key_target is None


@test(mark="fast")
def foreign_key_derives_its_storage_class_from_the_target_column() -> None:
    """An FK to a TEXT column is itself TEXT; storage is never restated."""

    class User[S = Pending](sqlite.Model[S, "User[Fetched]"]):
        """Referenced table whose unique email is a non-PK target."""

        id: User.GenCol[int] = sqlite.Integer(primary_key=True, default=MISSING)
        email: User.Col[str] = sqlite.Text(nullable=False, unique=True)

    class Order[S = Pending](sqlite.Model[S, "Order[Fetched]"]):
        """Table referencing the target's TEXT email column."""

        owner_email: Order.FKCol[User, str] = ForeignKey(User.email, nullable=False)

    assert_eq(Order.owner_email.storage_type_name, "Text")
    assert_eq(Order.owner_email.sqlite_storage_class, "TEXT")

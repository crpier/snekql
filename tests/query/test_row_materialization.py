"""Backend-neutral select-row materialization tests.

Row materialization shared by every backend turns one database row into the
result shape implied by the select query: a Fetched Model, a single scalar, or
a tuple of scalars. These tests pin that shared seam directly.
"""

from __future__ import annotations

from typing import cast

from snektest import assert_eq, assert_raises, test

from snekql import sqlite
from snekql._query_materialize import materialize_select_row_for_backend
from snekql.sqlite import MISSING, Fetched, Integer, Pending, Text, select


class Widget[S = Pending](sqlite.Model[S, "Widget[Fetched]"]):
    """Model exposing columns whose codecs make decoding observable."""

    label: Widget.Col[str] = Text(nullable=False)
    enabled: Widget.Col[bool] = Integer(nullable=False)


class JoinUser[S = Pending](sqlite.Model[S, "JoinUser[Fetched]"]):
    """Referenced table for join materialization tests."""

    id: JoinUser.GenCol[int] = sqlite.Integer(
        primary_key=True,
        auto_increment=True,
        default=MISSING,
    )
    email: JoinUser.Col[str] = Text(nullable=False)


class JoinOrder[S = Pending](sqlite.Model[S, "JoinOrder[Fetched]"]):
    """Table with a foreign key to ``JoinUser``."""

    id: JoinOrder.GenCol[int] = sqlite.Integer(
        primary_key=True,
        auto_increment=True,
        default=MISSING,
    )
    user_id: JoinOrder.FKCol[JoinUser, int] = sqlite.ForeignKey(JoinUser.id)
    note: JoinOrder.Col[str] = Text(nullable=False)


@test(mark="fast")
def model_select_materializes_a_fetched_model() -> None:
    """A model select decodes the whole row into a Fetched Model instance."""

    query = select(Widget).all()

    fetched = cast(
        "Widget[Fetched]",
        materialize_select_row_for_backend(query.state, ("hi", 0), backend="sqlite"),
    )

    assert_eq(fetched.label, "hi")
    assert_eq(fetched.enabled, False)


@test(mark="fast")
def single_value_select_unwraps_to_one_decoded_scalar() -> None:
    """A one-column select returns the decoded scalar, not a 1-tuple."""

    query = select(Widget.enabled).all()

    value = materialize_select_row_for_backend(query.state, (1,), backend="sqlite")

    assert_eq(value, True)


@test(mark="fast")
def multi_value_select_returns_a_decoded_tuple() -> None:
    """A multi-column select returns a tuple of decoded scalars in order."""

    query = select(Widget.label, Widget.enabled).all()

    values = materialize_select_row_for_backend(
        query.state, ("hi", 1), backend="sqlite"
    )

    assert_eq(values, ("hi", True))


@test(mark="fast")
def inner_join_materializes_a_tuple_of_fetched_models() -> None:
    """An inner join splits the flat row into one Fetched model per table."""

    query = (
        select(JoinUser)
        .join(JoinOrder, on=JoinOrder.user_id.references(JoinUser.id))
        .all()
    )

    result = cast(
        "tuple[JoinUser[Fetched], JoinOrder[Fetched]]",
        materialize_select_row_for_backend(
            query.state,
            (1, "a@b.c", 10, 1, "hello"),
            backend="sqlite",
        ),
    )

    assert_eq(result[0].id, 1)
    assert_eq(result[0].email, "a@b.c")
    assert_eq(result[1].id, 10)
    assert_eq(result[1].user_id, 1)
    assert_eq(result[1].note, "hello")


@test(mark="fast")
def left_join_yields_none_when_the_right_side_is_all_null() -> None:
    """A left join with no matching right row materializes the right as None."""

    query = (
        select(JoinUser)
        .left_join(JoinOrder, on=JoinOrder.user_id.references(JoinUser.id))
        .all()
    )

    result = cast(
        "tuple[JoinUser[Fetched], JoinOrder[Fetched] | None]",
        materialize_select_row_for_backend(
            query.state,
            (1, "a@b.c", None, None, None),
            backend="sqlite",
        ),
    )

    assert_eq(result[0].email, "a@b.c")
    assert result[1] is None


@test(mark="fast")
def projection_join_materializes_a_tuple_of_scalars() -> None:
    """A projection join decodes the row into the projected scalar tuple."""

    query = (
        select(JoinUser.email, JoinOrder.note)
        .join(JoinOrder, on=JoinOrder.user_id.references(JoinUser.id))
        .all()
    )

    values = materialize_select_row_for_backend(
        query.state,
        ("a@b.c", "hello"),
        backend="sqlite",
    )

    assert_eq(values, ("a@b.c", "hello"))


@test(mark="fast")
def single_column_projection_join_unwraps_to_one_scalar() -> None:
    """A single projected column over a join still returns a bare scalar."""

    query = (
        select(JoinUser.email)
        .join(JoinOrder, on=JoinOrder.user_id.references(JoinUser.id))
        .where(JoinOrder.note.eq("x"))
    )

    value = materialize_select_row_for_backend(
        query.state, ("a@b.c",), backend="sqlite"
    )

    assert_eq(value, "a@b.c")


@test(mark="fast")
def row_shape_mismatch_is_an_invariant_failure() -> None:
    """A row whose width differs from the select fields fails the invariant."""

    query = select(Widget.label, Widget.enabled).all()

    with assert_raises(AssertionError):
        _ = materialize_select_row_for_backend(query.state, ("hi",), backend="sqlite")

"""Backend-neutral select-row materialization tests.

Row materialization shared by every backend turns one database row into the
result shape implied by the select query: a Fetched Model, a single scalar, or
a tuple of scalars. These tests pin that shared seam directly.
"""

from __future__ import annotations

from typing import cast

from snektest import assert_eq, assert_raises, test

from snekql import Boolean, Fetched, Pending, Text, select, sqlite
from snekql.query import materialize_select_row_for_backend


class Widget[S = Pending](sqlite.Model[S, "Widget[Fetched]"]):
    """Model exposing columns whose codecs make decoding observable."""

    label: Widget.Col[str] = Text(nullable=False)
    enabled: Widget.Col[bool] = Boolean(nullable=False)


@test(mark="fast")
def model_select_materializes_a_fetched_model() -> None:
    """A model select decodes the whole row into a Fetched Model instance."""

    query = select(Widget).all()

    fetched = cast(
        "Widget[Fetched]",
        materialize_select_row_for_backend(query, ("hi", 0), backend="sqlite"),
    )

    assert_eq(fetched.label, "hi")
    assert_eq(fetched.enabled, False)


@test(mark="fast")
def single_value_select_unwraps_to_one_decoded_scalar() -> None:
    """A one-column select returns the decoded scalar, not a 1-tuple."""

    query = select(Widget.enabled).all()

    value = materialize_select_row_for_backend(query, (1,), backend="sqlite")

    assert_eq(value, True)


@test(mark="fast")
def multi_value_select_returns_a_decoded_tuple() -> None:
    """A multi-column select returns a tuple of decoded scalars in order."""

    query = select(Widget.label, Widget.enabled).all()

    values = materialize_select_row_for_backend(query, ("hi", 1), backend="sqlite")

    assert_eq(values, ("hi", True))


@test(mark="fast")
def row_shape_mismatch_is_an_invariant_failure() -> None:
    """A row whose width differs from the select fields fails the invariant."""

    query = select(Widget.label, Widget.enabled).all()

    with assert_raises(AssertionError):
        _ = materialize_select_row_for_backend(query, ("hi",), backend="sqlite")

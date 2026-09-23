"""Reference behavior that limits claims about the existing typing guarantees."""

from typing import assert_type

from snektest import assert_is, test

from snekql import sqlite


@test(mark="fast")
def explicit_fetched_constructor_can_still_hold_pending_id() -> None:
    """An explicit fetched specialization does not change constructor runtime state."""

    class Reference[S = sqlite.Pending](sqlite.Model[S, "Reference[sqlite.Fetched]"]):
        id: sqlite.GenCol[int] = sqlite.Integer(default=sqlite.PENDING_GENERATION)
        name: sqlite.Col[str] = sqlite.Text()

    row = Reference[sqlite.Fetched](name="Ada")

    assert_type(row.id, int)
    assert_is(row.id, sqlite.PENDING_GENERATION)

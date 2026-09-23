"""Feed production labels through the proposed explicit schema carrier."""

from typing import assert_type

from schema import Expr, Fields, project

from snekql import sqlite


class Event[S = sqlite.Pending](sqlite.Model[S, "Event[sqlite.Fetched]"]):
    """Real production model supplying expression types."""

    event_id: sqlite.Col[int] = sqlite.Integer()
    optional_id: sqlite.Col[int | None] = sqlite.Integer()
    title: sqlite.Col[str] = sqlite.Text()


left = project(
    Fields(event_id=Event.event_id.label("event_id"), title=Event.title.label("title"))
)
right = project(
    Fields(
        title=Event.title.label("title"), event_id=Event.optional_id.label("event_id")
    )
)
assert_type(
    left.union_all(right).column(lambda fields: fields.event_id), Expr[int | None]
)
assert_type(left.union_all(right).column(lambda fields: fields.title), Expr[str])

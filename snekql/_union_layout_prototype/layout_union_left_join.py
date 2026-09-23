"""Existing CTE rebinding can supply accurate contextual nullability."""

from typing import assert_type

from layout_union import Fields, project, value
from pydantic import BaseModel

from snekql import sqlite


class Source[S = sqlite.Pending](sqlite.Model[S, "Source[sqlite.Fetched]"]):
    """A real table supplying columns to nullable and required scopes."""

    event_id: sqlite.Col[int] = sqlite.Integer(primary_key=True)
    title: sqlite.Col[str] = sqlite.Text()


class Row(BaseModel):
    event_id: int | None
    title: str


class PeerRole: ...


class DefinitionRole: ...


peer = sqlite.alias(Source, PeerRole, name="peer")
id_token = peer.column(Source.event_id).label("event_id")
title_token = Source.title.label("title")
joined = (
    sqlite.select(Source)
    .left_join(peer, on=Source.event_id.eq_col(peer.column(Source.event_id)))
    .all()
)
cte = joined.project(Row, event_id=id_token, title=title_token).cte(
    DefinitionRole, name="joined_rows"
)
left = project(Fields(event_id=Source.event_id.label("event_id"), title=title_token))
right = project(
    Fields(
        event_id=cte.column(id_token).label("event_id"),
        title=cte.column(title_token).label("title"),
    )
)
assert_type(value(left.union_all(right).columns.event_id), int | None)
assert_type(value(left.union_all(right).columns.title), str)

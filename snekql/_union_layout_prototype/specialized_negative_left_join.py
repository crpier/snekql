"""A source label does not carry contextual LEFT-join null extension."""

from specialized import ID, Expr, SQLite, project

from snekql import sqlite


class Source[S = sqlite.Pending](sqlite.Model[S, "Source[sqlite.Fetched]"]):
    """The same integer expression may belong to a nullable joined owner."""

    event_id: sqlite.Col[int] = sqlite.Integer(primary_key=True)
    title: sqlite.Col[str] = sqlite.Text()


class PeerRole: ...


peer = sqlite.alias(Source, PeerRole, name="peer")
joined = (
    sqlite.select(Source)
    .left_join(peer, on=Source.event_id.eq_col(peer.column(Source.event_id)))
    .all()
)
# A hypothetical projection adapter using only these expressions loses joined's owner facts.
projection = project(
    SQLite,
    event_id=peer.column(Source.event_id).label("event_id"),
    title=Source.title.label("title"),
)
required: Expr[int] = projection.union_all(projection).column(ID)

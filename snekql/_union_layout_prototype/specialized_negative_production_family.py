"""Must not accept MariaDB labels into an SQLite projection."""

from specialized import SQLite, project

from snekql import mariadb


class Source[S = mariadb.Pending](mariadb.Model[S, "Source[mariadb.Fetched]"]):
    """Actual backend-owned source, not a stand-in family witness."""

    event_id: mariadb.Col[int] = mariadb.Integer()
    title: mariadb.Col[str] = mariadb.Text()


project(
    SQLite,
    event_id=Source.event_id.label("event_id"),
    title=Source.title.label("title"),
)

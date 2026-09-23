"""Inspect wire-policy information carried by real production labels."""

from typing import reveal_type

from snekql import sqlite


class Source[S = sqlite.Pending](sqlite.Model[S, "Source[sqlite.Fetched]"]):
    """Same logical type, different SQLite wire representation."""

    native: sqlite.Col[int] = sqlite.Integer()
    encoded: sqlite.Col[int] = sqlite.Text()


reveal_type(Source.native.label("value"))
reveal_type(Source.encoded.label("value"))

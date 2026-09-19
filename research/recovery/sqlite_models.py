"""Native SQLite declarations; no added database quantity constraint."""

from typing import Annotated

from pydantic import Field

from snekql import sqlite as db


class Entry[S = db.Pending](db.Model[S, "Entry[db.Fetched]"]):
    __tablename__ = "entries"
    id: db.Col[int] = db.Integer(primary_key=True)
    code: db.Col[str] = db.Text(unique=True)
    quantity: db.Col[Annotated[int, Field(strict=True, gt=0)]] = db.Integer()
    note: db.Col[str | None] = db.Text(nullable=True)
    occurred_at: db.Col[db.UtcDatetime] = db.Text()

"""SQLite counter declaration without an implicit concurrency policy."""

from snekql import sqlite as db


class Counter[S = db.Pending](db.Model[S, "Counter[db.Fetched]"]):
    __tablename__ = "counter"
    id: db.Col[int] = db.Integer(primary_key=True)
    quantity: db.Col[int] = db.Integer()
    revision: db.Col[int] = db.Integer()

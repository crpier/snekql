"""SQLite runtime contract; migration SQL owns literal defaults and CHECKs."""

from typing import Annotated

from pydantic import Field

from snekql import sqlite as db


class Order[S = db.Pending](db.Model[S, "Order[db.Fetched]"]):
    __tablename__ = "orders"
    id: db.GenCol[int] = db.Integer(
        primary_key=True, auto_increment=True, default=db.PENDING_GENERATION
    )
    price_cents: db.Col[Annotated[int, Field(strict=True, ge=0, le=9999999999)]] = (
        db.Integer()
    )
    quantity: db.Col[Annotated[int, Field(strict=True, ge=1, le=2147483647)]] = (
        db.Integer()
    )
    status: db.GenCol[str] = db.Text(default=db.PENDING_GENERATION)
    created_at: db.GenCol[db.UtcDatetime] = db.Text(default=db.CurrentTimestamp)


MIGRATIONS = {
    "001_orders": """CREATE TABLE orders (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        price_cents INTEGER NOT NULL CHECK (price_cents BETWEEN 0 AND 9999999999),
        quantity INTEGER NOT NULL CHECK (quantity BETWEEN 1 AND 2147483647),
        status TEXT NOT NULL DEFAULT 'pending',
        created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
    ) STRICT"""
}

"""Minimal runnable snekql application."""

from __future__ import annotations

import asyncio
from datetime import datetime

from snekql import sqlite
from snekql.sqlite import Database, Fetched, Pending, insert, scaffold, select


class User[S = Pending](sqlite.Model[S, "User[Fetched]"]):
    """Example table model used by the basic application."""

    id: User.GenCol[int] = sqlite.Integer(
        primary_key=True,
        auto_increment=True,
        default=sqlite.PENDING_GENERATION,
    )
    email: User.Col[str] = sqlite.Text(nullable=False, unique=True)
    created_at: User.GenCol[datetime] = sqlite.Text(default=sqlite.CurrentTimestamp)


async def main() -> None:
    """Create a table, insert a row, and read it back."""

    async with await Database.initialize(sqlite.Config(database=":memory:")) as db:
        await db.migrate({"0001_create_user": scaffold([User])})
        await db.verify([User])
        async with db.transaction() as transaction:
            await transaction.execute(insert(User(email="alice@example.com")))
            user = await transaction.fetch_one(
                select(User).where(User.email.eq("alice@example.com")),
            )
            print(user.email)


if __name__ == "__main__":
    asyncio.run(main())

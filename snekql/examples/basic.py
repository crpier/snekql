"""Minimal runnable snekql application."""

from __future__ import annotations

import asyncio
from datetime import datetime

from snekql import sqlite
from snekql.sqlite import Database, Fetched, Pending, insert, select


class User[S = Pending](sqlite.Model[S, "User[Fetched]"]):
    """Example table model used by the basic application."""

    id: sqlite.GenCol[int] = sqlite.Integer(
        primary_key=True,
        auto_increment=True,
        default=sqlite.PENDING_GENERATION,
    )
    email: sqlite.Col[str] = sqlite.Text(unique=True)
    created_at: sqlite.GenCol[datetime] = sqlite.Text(default=sqlite.CurrentTimestamp)


MIGRATIONS = {
    "0001_create_user": (
        'CREATE TABLE "user" ('
        '"id" INTEGER PRIMARY KEY AUTOINCREMENT, '
        '"email" TEXT NOT NULL, '
        '"created_at" TEXT NOT NULL DEFAULT '
        "(strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))"
        ") STRICT"
    ),
    "0002_user_email_unique": (
        'CREATE UNIQUE INDEX "ux_user_email" ON "user" ("email")'
    ),
}


async def main() -> None:
    """Create a table, insert a row, and read it back."""

    async with await Database.initialize(sqlite.Config(database=":memory:")) as db:
        await db.migrate(MIGRATIONS)
        await db.verify_migrations(MIGRATIONS)
        await db.verify([User])
        async with db.transaction() as transaction:
            await transaction.execute(insert(User(email="alice@example.com")))
            user = await transaction.fetch_one(
                select(User).where(User.email.eq("alice@example.com")),
            )
            print(user.email)


if __name__ == "__main__":
    asyncio.run(main())

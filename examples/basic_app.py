"""Minimal runnable snekql application.

Run from the repository root with:

    uv run python -m examples.basic_app
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime

from snekql import sqlite
from snekql.sqlite import (
    Database,
    Fetched,
    Pending,
    delete,
    insert,
    select,
    update,
)


class User[S = Pending](sqlite.Model[S, "User[Fetched]"]):
    """Example table model used by the basic application."""

    id: User.GenCol[int] = sqlite.Integer(
        primary_key=True,
        auto_increment=True,
        default=sqlite.PENDING_GENERATION,
    )
    email: User.Col[str] = sqlite.Text(nullable=False)
    status: User.Col[str] = sqlite.Text(nullable=False, default="active")
    created_at: User.GenCol[datetime] = sqlite.Text(default=sqlite.CurrentTimestamp)


async def main() -> None:
    """Exercise v1 create, read, update, and delete behavior."""

    db = await Database.initialize(
        sqlite.Config(database=":memory:", pool_size=1),
        models=[User],
    )
    try:
        async with db.transaction() as tx:
            await tx.execute(insert(User(email="alice@example.com")))
            await tx.execute(insert(User(email="bob@example.com")))

            active_emails = await tx.fetch_all(
                select(User.email)
                .where(User.status.eq("active"))
                .order_by(
                    User.email.asc(),
                ),
            )
            print("active users:", active_emails)

            disabled_count = await tx.execute(
                update(User)
                .set(User.status.to("disabled"))
                .where(User.email.eq("bob@example.com")),
            )
            print("rows disabled:", disabled_count)

            disabled_user = await tx.fetch_one(
                select(User).where(User.status.eq("disabled")),
            )
            print("disabled user:", disabled_user)

            deleted_count = await tx.execute(
                delete(User).where(User.email.eq("alice@example.com")),
            )
            print("rows deleted:", deleted_count)
    finally:
        await db.close()


if __name__ == "__main__":
    # snekql logs through the stdlib ``snekql`` logger; the application decides
    # where those records go. Configure logging before running, and tune snekql's
    # verbosity from its one parent logger.
    logging.basicConfig(level=logging.INFO)
    logging.getLogger("snekql").setLevel(logging.DEBUG)
    asyncio.run(main())

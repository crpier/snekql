"""Minimal runnable snekql application.

Run from the repository root with:

    uv run python -m examples.basic_app
"""

from __future__ import annotations

import asyncio
from datetime import datetime

from snekql import (
    MISSING,
    CurrentTimestamp,
    Database,
    DateTime,
    Fetched,  # noqa: F401 - used by the forward reference in the model base.
    Integer,
    Model,
    Pending,
    Text,
    delete,
    insert,
    select,
    update,
)


class User[S = Pending](Model[S, "User[Fetched]"]):
    """Example table model used by the basic application."""

    id: User.GenCol[int] = Integer(
        primary_key=True,
        auto_increment=True,
        default=MISSING,
    )
    email: User.Col[str] = Text(nullable=False)
    status: User.Col[str] = Text(nullable=False, default="active")
    created_at: User.GenCol[datetime] = DateTime(
        server_default=CurrentTimestamp(),
        default=MISSING,
    )


async def main() -> None:
    """Exercise v1 create, read, update, and delete behavior."""

    db = await Database.initialize(
        database=":memory:",
        models=[User],
        pool_size=1,
    )
    try:
        async with db.transaction() as transaction:
            await transaction.execute(insert(User(email="alice@example.com")))
            await transaction.execute(insert(User(email="bob@example.com")))

            active_emails = await transaction.fetch_all(
                select(User.email)
                .where(User.status.eq("active"))
                .order_by(
                    User.email.asc(),
                ),
            )
            print("active users:", active_emails)

            await transaction.execute(
                update(User)
                .set(User.status.to("disabled"))
                .where(User.email.eq("bob@example.com")),
            )

            disabled_user = await transaction.fetch_one(
                select(User).where(User.status.eq("disabled")),
            )
            print("disabled user:", disabled_user)

            await transaction.execute(
                delete(User).where(User.email.eq("alice@example.com")),
            )
    finally:
        await db.close()


if __name__ == "__main__":
    asyncio.run(main())

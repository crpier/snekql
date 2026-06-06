"""Minimal runnable snekql application.

Run from the repository root with:

    uv run python -m examples.basic_app
"""

from __future__ import annotations

import asyncio
from datetime import datetime

from snekql import (
    Database,
    Fetched,
    Pending,
    StructuredLogger,
    delete,
    insert,
    select,
    sqlite,
    update,
)


class ExampleLogger:
    """Tiny structured logger for the runnable example."""

    def debug(self, event: str, **fields: object) -> None:
        print("debug", event, fields)

    def info(self, event: str, **fields: object) -> None:
        print("info", event, fields)

    def warning(self, event: str, **fields: object) -> None:
        print("warning", event, fields)

    def error(self, event: str, **fields: object) -> None:
        print("error", event, fields)


class User[S = Pending](sqlite.Model[S, "User[Fetched]"]):
    """Example table model used by the basic application."""

    id: User.GenCol[int] = sqlite.Integer(
        primary_key=True,
        auto_increment=True,
        default=sqlite.MISSING,
    )
    email: User.Col[str] = sqlite.Text(nullable=False)
    status: User.Col[str] = sqlite.Text(nullable=False, default="active")
    created_at: User.GenCol[datetime] = sqlite.DateTime(
        server_default=sqlite.CurrentTimestamp(),
        default=sqlite.MISSING,
    )


async def main(*, logger: StructuredLogger) -> None:
    """Exercise v1 create, read, update, and delete behavior."""

    db = await Database.initialize(
        sqlite.Config(database=":memory:", pool_size=1),
        logger=logger,
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

            await tx.execute(
                update(User)
                .set(User.status.to("disabled"))
                .where(User.email.eq("bob@example.com")),
            )

            disabled_user = await tx.fetch_one(
                select(User).where(User.status.eq("disabled")),
            )
            print("disabled user:", disabled_user)

            await tx.execute(
                delete(User).where(User.email.eq("alice@example.com")),
            )
    finally:
        await db.close()


if __name__ == "__main__":
    asyncio.run(main(logger=ExampleLogger()))

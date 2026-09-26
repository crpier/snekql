"""Minimal runnable snekql application.

Run from the repository root with:

    uv run python -m examples.basic_app
"""

from __future__ import annotations

import asyncio
import logging
from typing import ClassVar

from snekql import sqlite
from snekql.sqlite import (
    Database,
    Pending,
    Row,
    delete,
    insert,
    select,
    update,
)


class User[S = Pending](sqlite.Model[S]):
    """Example table model used by the basic application."""

    __row_type__: ClassVar[sqlite.ReadType[User[Row]]]

    id: sqlite.GenCol[int] = sqlite.Integer(
        primary_key=True,
        auto_increment=True,
        default=sqlite.PENDING_GENERATION,
    )
    email: sqlite.Col[str] = sqlite.Text()
    status: sqlite.Col[str] = sqlite.Text(default="active")
    created_at: sqlite.GenCol[sqlite.UtcDatetime] = sqlite.Text(
        default=sqlite.CurrentTimestamp
    )


MIGRATIONS = {
    "0001_create_user": (
        'CREATE TABLE "user" ('
        '"id" INTEGER PRIMARY KEY AUTOINCREMENT, '
        '"email" TEXT NOT NULL, '
        '"status" TEXT NOT NULL, '
        '"created_at" TEXT NOT NULL DEFAULT '
        "(strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))"
        ") STRICT"
    ),
    "0003_create_user_temporal": (
        'CREATE TABLE "user_temporal" ('
        '"id" INTEGER PRIMARY KEY AUTOINCREMENT, '
        '"email" TEXT NOT NULL, '
        '"status" TEXT NOT NULL, '
        '"created_at" TEXT NOT NULL DEFAULT '
        "(strftime('%Y-%m-%dT%H:%M:%f', 'now') || '000Z')) STRICT"
    ),
    "0004_copy_user_temporal": (
        "INSERT INTO user_temporal (id, email, status, created_at) "
        "SELECT id, email, status, CASE "
        "WHEN length(created_at) = 24 AND "
        "strftime('%Y-%m-%dT%H:%M:%fZ', created_at) = created_at "
        "THEN substr(created_at, 1, 23) || '000Z' ELSE NULL END FROM user"
    ),
    "0005_drop_old_user": 'DROP TABLE "user"',
    "0006_rename_user_temporal": 'ALTER TABLE "user_temporal" RENAME TO "user"',
}


async def main() -> None:
    """Exercise v1 create, read, update, and delete behavior."""

    # Initialization only connects. The migration is committed literal SQL,
    # separate from current model metadata.
    db = await Database.initialize(
        sqlite.Config(database=":memory:", pool_size=1),
    )
    try:
        await db.migrate(MIGRATIONS)
        await db.verify_migrations(MIGRATIONS)
        await db.verify([User])
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

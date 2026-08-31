"""SQLite insert conflict execution tests."""

from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory

from snektest import assert_eq, test

from snekql import sqlite
from tests.helpers import initialized_database


@test(mark="medium")
async def conflict_update_replaces_columns_on_existing_row() -> None:
    """A conflicting SQLite insert updates and returns the stored row."""

    class User[S = sqlite.Pending](sqlite.Model[S, "User[sqlite.Fetched]"]):
        """Table model with a unique email conflict target."""

        email: User.Col[str] = sqlite.Text(nullable=False, unique=True)
        name: User.Col[str] = sqlite.Text(nullable=False)
        status: User.Col[str] = sqlite.Text(nullable=False)

    with TemporaryDirectory() as directory:
        database = await initialized_database(
            database=Path(directory) / "app.db",
            models=[User],
        )
        try:
            async with database.transaction() as tx:
                await tx.execute(
                    sqlite.insert(
                        User(email="a@example.com", name="Old", status="inactive")
                    )
                )

            async with database.transaction() as tx:
                stored = await tx.execute(
                    sqlite.insert(
                        User(email="a@example.com", name="Alice", status="active")
                    )
                    .on_conflict(
                        User.email,
                        action=sqlite.DoUpdate(
                            User.name.to_inserted(),
                            User.status.to_inserted(),
                        ),
                    )
                    .returning()
                )
        finally:
            await database.close()

    assert_eq(stored.name, "Alice")
    assert_eq(stored.status, "active")


@test(mark="medium")
async def conflict_do_nothing_preserves_existing_row() -> None:
    """A conflicting SQLite insert leaves the stored row unchanged."""

    class User[S = sqlite.Pending](sqlite.Model[S, "User[sqlite.Fetched]"]):
        """Table model with a unique email conflict target."""

        email: User.Col[str] = sqlite.Text(nullable=False, unique=True)
        name: User.Col[str] = sqlite.Text(nullable=False)

    with TemporaryDirectory() as directory:
        database = await initialized_database(
            database=Path(directory) / "app.db",
            models=[User],
        )
        try:
            async with database.transaction() as tx:
                await tx.execute(
                    sqlite.insert(User(email="a@example.com", name="Original"))
                )

            async with database.transaction() as tx:
                await tx.execute(
                    sqlite.insert(
                        User(email="a@example.com", name="Replacement")
                    ).on_conflict(User.email, action=sqlite.DoNothing)
                )

            async with database.transaction() as tx:
                stored = await tx.fetch_one(
                    sqlite.select(User).where(User.email.eq("a@example.com"))
                )
        finally:
            await database.close()

    assert_eq(stored.name, "Original")


@test(mark="medium")
async def bulk_conflict_update_returns_each_upserted_row() -> None:
    """A bulk SQLite upsert updates conflicts and inserts new rows."""

    class User[S = sqlite.Pending](sqlite.Model[S, "User[sqlite.Fetched]"]):
        """Table model with a unique email conflict target."""

        email: User.Col[str] = sqlite.Text(nullable=False, unique=True)
        status: User.Col[str] = sqlite.Text(nullable=False)

    with TemporaryDirectory() as directory:
        database = await initialized_database(
            database=Path(directory) / "app.db",
            models=[User],
        )
        try:
            async with database.transaction() as tx:
                await tx.execute(
                    sqlite.insert(User(email="a@example.com", status="old"))
                )

            async with database.transaction() as tx:
                stored = await tx.execute(
                    sqlite.insert(
                        [
                            User(email="a@example.com", status="updated"),
                            User(email="b@example.com", status="inserted"),
                        ]
                    )
                    .on_conflict(
                        User.email,
                        action=sqlite.DoUpdate(User.status.to_inserted()),
                    )
                    .returning(User.email, User.status)
                )
        finally:
            await database.close()

    assert_eq(stored, [("a@example.com", "updated"), ("b@example.com", "inserted")])

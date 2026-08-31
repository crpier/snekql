"""MariaDB insert conflict execution tests."""

from __future__ import annotations

from collections.abc import AsyncGenerator

from snektest import assert_eq, fixture, load_fixture, test

from snekql import mariadb
from tests.helpers import initialized_database, provide_mariadb_server


class User[S = mariadb.Pending](mariadb.Model[S, "User[mariadb.Fetched]"]):
    """Table model with a unique email conflict target."""

    __tablename__ = "issue239_upsert_user"

    email: User.Col[str] = mariadb.Text(nullable=False, unique=True)
    name: User.Col[str] = mariadb.Text(nullable=False)
    status: User.Col[str] = mariadb.Text(nullable=False)


@fixture
async def database_session() -> AsyncGenerator[mariadb.Database]:
    """Provide an initialized MariaDB database for conflict tests."""

    server = await load_fixture(provide_mariadb_server())
    database = await initialized_database(server.config(pool_size=1), models=[User])
    async with database.transaction() as tx:
        _ = await tx.execute(mariadb.delete(User).all())
    try:
        yield database
    finally:
        await database.close()


@test(mark="medium")
async def conflict_update_replaces_columns_on_existing_row() -> None:
    """A conflicting MariaDB insert updates and returns the stored row."""

    database = await load_fixture(database_session())
    async with database.transaction() as tx:
        await tx.execute(
            mariadb.insert(User(email="a@example.com", name="Old", status="inactive"))
        )

    async with database.transaction() as tx:
        stored = await tx.execute(
            mariadb.insert(User(email="a@example.com", name="Alice", status="active"))
            .on_conflict(
                User.email,
                action=mariadb.DoUpdate(
                    User.name.to_inserted(),
                    User.status.to_inserted(),
                ),
            )
            .returning()
        )

    assert_eq(stored.name, "Alice")
    assert_eq(stored.status, "active")


@test(mark="medium")
async def conflict_do_nothing_preserves_existing_row() -> None:
    """A conflicting MariaDB insert leaves the stored row unchanged."""

    database = await load_fixture(database_session())
    async with database.transaction() as tx:
        await tx.execute(
            mariadb.insert(
                User(email="a@example.com", name="Original", status="active")
            )
        )

    async with database.transaction() as tx:
        await tx.execute(
            mariadb.insert(
                User(email="a@example.com", name="Replacement", status="inactive")
            ).on_conflict(User.email, action=mariadb.DoNothing)
        )

    async with database.transaction() as tx:
        stored = await tx.fetch_one(
            mariadb.select(User).where(User.email.eq("a@example.com"))
        )

    assert_eq(stored.name, "Original")
    assert_eq(stored.status, "active")


@test(mark="medium")
async def bulk_conflict_update_returns_each_upserted_row() -> None:
    """A bulk MariaDB upsert updates conflicts and inserts new rows."""

    database = await load_fixture(database_session())
    async with database.transaction() as tx:
        await tx.execute(
            mariadb.insert(User(email="a@example.com", name="Alice", status="old"))
        )

    async with database.transaction() as tx:
        stored = await tx.execute(
            mariadb.insert(
                [
                    User(email="a@example.com", name="Alice", status="updated"),
                    User(email="b@example.com", name="Bob", status="inserted"),
                ]
            )
            .on_conflict(
                User.email,
                action=mariadb.DoUpdate(User.status.to_inserted()),
            )
            .returning(User.email, User.status)
        )

    assert_eq(stored, [("a@example.com", "updated"), ("b@example.com", "inserted")])

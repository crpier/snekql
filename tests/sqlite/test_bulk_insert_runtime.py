"""SQLite execution tests for bulk inserts and RETURNING-backed writes."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from sqlite3 import connect
from tempfile import TemporaryDirectory

from snektest import assert_eq, assert_is_none, test

from snekql.sqlite import (
    PENDING_GENERATION,
    CurrentTimestamp,
    Database,
    Fetched,
    Integer,
    Model,
    Pending,
    Text,
    insert,
)


class User[S = Pending](Model[S, "User[Fetched]"]):
    """Table model with an auto-increment key and a server-default timestamp."""

    id: User.GenCol[int] = Integer(
        primary_key=True, auto_increment=True, default=PENDING_GENERATION
    )
    email: User.Col[str] = Text(nullable=False)
    status: User.Col[str] = Text(nullable=False, default="active")
    created_at: User.GenCol[datetime] = Text(default=CurrentTimestamp)


def _count_rows(database_path: Path) -> int:
    connection = connect(database_path)
    try:
        cursor = connection.execute('SELECT COUNT(*) FROM "user"')
        return int(cursor.fetchone()[0])
    finally:
        connection.close()


@test(mark="medium")
async def bulk_insert_persists_every_row_in_one_statement() -> None:
    """A bulk insert writes each pending row to the table."""

    with TemporaryDirectory() as directory:
        database_path = Path(directory) / "app.db"
        database = await Database.initialize(database=database_path, models=[User])
        try:
            async with database.transaction() as tx:
                result = await tx.execute(
                    insert(
                        [
                            User(email="a@example.com"),
                            User(email="b@example.com"),
                            User(email="c@example.com"),
                        ]
                    )
                )
        finally:
            await database.close()
        count = _count_rows(database_path)

    assert_is_none(result)
    assert_eq(count, 3)


@test(mark="medium")
async def empty_bulk_insert_is_a_no_op() -> None:
    """A zero-row bulk insert issues no SQL and writes nothing."""

    with TemporaryDirectory() as directory:
        database_path = Path(directory) / "app.db"
        database = await Database.initialize(database=database_path, models=[User])
        try:
            async with database.transaction() as tx:
                no_rows: list[User[Pending]] = []
                result = await tx.execute(insert(no_rows))
        finally:
            await database.close()
        count = _count_rows(database_path)

    assert_is_none(result)
    assert_eq(count, 0)


@test(mark="medium")
async def single_returning_yields_generated_values() -> None:
    """A single returning insert recovers the auto-increment key and timestamp."""

    with TemporaryDirectory() as directory:
        database_path = Path(directory) / "app.db"
        database = await Database.initialize(database=database_path, models=[User])
        try:
            async with database.transaction() as tx:
                created = await tx.execute(
                    insert(User(email="a@example.com")).returning()
                )
        finally:
            await database.close()

    assert_eq(created.id, 1)
    assert_eq(created.email, "a@example.com")
    assert_eq(created.status, "active")
    assert isinstance(created.created_at, datetime)


@test(mark="medium")
async def single_returning_one_column_yields_scalar() -> None:
    """returning(col) on a single insert yields just that column's value."""

    with TemporaryDirectory() as directory:
        database_path = Path(directory) / "app.db"
        database = await Database.initialize(database=database_path, models=[User])
        try:
            async with database.transaction() as tx:
                new_id = await tx.execute(
                    insert(User(email="a@example.com")).returning(User.id)
                )
        finally:
            await database.close()

    assert_eq(new_id, 1)


@test(mark="medium")
async def single_returning_several_columns_yields_tuple() -> None:
    """returning(col, col) on a single insert yields a tuple in the given order."""

    with TemporaryDirectory() as directory:
        database_path = Path(directory) / "app.db"
        database = await Database.initialize(database=database_path, models=[User])
        try:
            async with database.transaction() as tx:
                row = await tx.execute(
                    insert(User(email="a@example.com")).returning(User.id, User.email)
                )
        finally:
            await database.close()

    assert_eq(row, (1, "a@example.com"))


@test(mark="medium")
async def bulk_returning_one_column_yields_scalar_list() -> None:
    """returning(col) on a bulk insert yields one decoded scalar per row."""

    with TemporaryDirectory() as directory:
        database_path = Path(directory) / "app.db"
        database = await Database.initialize(database=database_path, models=[User])
        try:
            async with database.transaction() as tx:
                ids = await tx.execute(
                    insert(
                        [
                            User(email="a@example.com"),
                            User(email="b@example.com"),
                        ]
                    ).returning(User.id)
                )
        finally:
            await database.close()

    assert_eq(ids, [1, 2])


@test(mark="medium")
async def bulk_returning_several_columns_yields_tuple_list() -> None:
    """returning(col, col) on a bulk insert yields one tuple per row in order."""

    with TemporaryDirectory() as directory:
        database_path = Path(directory) / "app.db"
        database = await Database.initialize(database=database_path, models=[User])
        try:
            async with database.transaction() as tx:
                rows = await tx.execute(
                    insert(
                        [
                            User(email="a@example.com"),
                            User(email="b@example.com"),
                        ]
                    ).returning(User.id, User.email)
                )
        finally:
            await database.close()

    assert_eq(rows, [(1, "a@example.com"), (2, "b@example.com")])


@test(mark="medium")
async def empty_bulk_returning_columns_yields_empty_list() -> None:
    """A zero-row bulk insert with a column projection yields [] without SQL."""

    with TemporaryDirectory() as directory:
        database_path = Path(directory) / "app.db"
        database = await Database.initialize(database=database_path, models=[User])
        try:
            async with database.transaction() as tx:
                no_rows: list[User[Pending]] = []
                rows = await tx.execute(insert(no_rows).returning(User.id))
        finally:
            await database.close()

    assert_eq(rows, [])


@test(mark="medium")
async def bulk_returning_yields_one_fetched_model_per_row() -> None:
    """A bulk returning insert recovers a Fetched model for every row in order."""

    with TemporaryDirectory() as directory:
        database_path = Path(directory) / "app.db"
        database = await Database.initialize(database=database_path, models=[User])
        try:
            async with database.transaction() as tx:
                created = await tx.execute(
                    insert(
                        [
                            User(email="a@example.com"),
                            User(email="b@example.com"),
                        ]
                    ).returning()
                )
        finally:
            await database.close()

    assert_eq(len(created), 2)
    assert_eq([user.id for user in created], [1, 2])
    assert_eq([user.email for user in created], ["a@example.com", "b@example.com"])


@test(mark="medium")
async def empty_bulk_returning_yields_empty_list() -> None:
    """A zero-row bulk returning insert yields an empty list without SQL."""

    with TemporaryDirectory() as directory:
        database_path = Path(directory) / "app.db"
        database = await Database.initialize(database=database_path, models=[User])
        try:
            async with database.transaction() as tx:
                no_rows: list[User[Pending]] = []
                created = await tx.execute(insert(no_rows).returning())
        finally:
            await database.close()

    assert_eq(created, [])

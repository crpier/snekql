"""MariaDB execution tests for bulk inserts and RETURNING-backed writes."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import Any

from snektest import AsyncFixture, assert_eq, assert_is_none, load_fixture, test

from snekql import mariadb
from snekql.mariadb import (
    MISSING,
    CurrentTimestamp,
    Database,
    Fetched,
    Pending,
    insert,
    select,
)
from snekql.model import Table
from tests.helpers import provide_mariadb_server


class _BulkUser[S = Pending](mariadb.Model[S, "_BulkUser[Fetched]"]):
    """Table model for MariaDB bulk-insert coverage."""

    __tablename__ = "issue117_bulk_user"

    id: _BulkUser.GenCol[int] = mariadb.Integer(
        primary_key=True,
        auto_increment=True,
        default=MISSING,
    )
    email: _BulkUser.Col[str] = mariadb.Text(nullable=False)
    status: _BulkUser.Col[str] = mariadb.Text(nullable=False, default="active")
    created_at: _BulkUser.GenCol[datetime] = mariadb.DateTime(
        server_default=CurrentTimestamp,
        default=MISSING,
    )


async def database_session(
    models: Sequence[type[Table[Any]]] = (),
) -> AsyncFixture[Database]:
    """Provide an initialized MariaDB Database and close it after the test."""

    server = await load_fixture(provide_mariadb_server())
    database = await Database.initialize(server.config(pool_size=1), models=models)
    try:
        yield database
    finally:
        await database.close()


@test(mark="medium")
async def mariadb_bulk_insert_persists_every_row() -> None:
    """A MariaDB bulk insert writes each pending row in one statement."""

    database = await load_fixture(database_session([_BulkUser]))
    async with database.transaction() as tx:
        before = await tx.fetch_one(select(_BulkUser.id.count()).all())
        result = await tx.execute(
            insert(
                [
                    _BulkUser(email="a@example.com"),
                    _BulkUser(email="b@example.com"),
                    _BulkUser(email="c@example.com"),
                ]
            )
        )
        stored = await tx.execute(insert(_BulkUser(email="d@example.com")))
        after = await tx.fetch_one(select(_BulkUser.id.count()).all())

    assert_is_none(result)
    assert_is_none(stored)
    assert_eq((after or 0) - (before or 0), 4)


@test(mark="medium")
async def mariadb_single_returning_yields_generated_values() -> None:
    """A MariaDB returning insert recovers the auto-increment key and timestamp."""

    database = await load_fixture(database_session([_BulkUser]))
    async with database.transaction() as tx:
        created = await tx.execute(insert(_BulkUser(email="a@example.com")).returning())

    assert_eq(created.email, "a@example.com")
    assert_eq(created.status, "active")
    assert created.id >= 1
    assert isinstance(created.created_at, datetime)


@test(mark="medium")
async def mariadb_bulk_returning_yields_one_model_per_row() -> None:
    """A MariaDB bulk returning insert recovers a Fetched model for every row."""

    database = await load_fixture(database_session([_BulkUser]))
    async with database.transaction() as tx:
        created = await tx.execute(
            insert(
                [
                    _BulkUser(email="a@example.com"),
                    _BulkUser(email="b@example.com"),
                ]
            ).returning()
        )

    assert_eq(len(created), 2)
    assert_eq(
        sorted(user.email for user in created),
        ["a@example.com", "b@example.com"],
    )


@test(mark="medium")
async def mariadb_single_returning_columns_yields_scalar_and_tuple() -> None:
    """A MariaDB returning projection yields a scalar for one column, a tuple for several."""

    database = await load_fixture(database_session([_BulkUser]))
    async with database.transaction() as tx:
        new_id = await tx.execute(
            insert(_BulkUser(email="a@example.com")).returning(_BulkUser.id)
        )
        row = await tx.execute(
            insert(_BulkUser(email="b@example.com")).returning(
                _BulkUser.id, _BulkUser.email
            )
        )

    assert new_id >= 1
    assert_eq(row[1], "b@example.com")
    assert row[0] > new_id


@test(mark="medium")
async def mariadb_bulk_returning_columns_yields_projection_per_row() -> None:
    """A MariaDB bulk returning projection yields one scalar/tuple per row."""

    database = await load_fixture(database_session([_BulkUser]))
    async with database.transaction() as tx:
        ids = await tx.execute(
            insert(
                [
                    _BulkUser(email="a@example.com"),
                    _BulkUser(email="b@example.com"),
                ]
            ).returning(_BulkUser.id)
        )
        rows = await tx.execute(
            insert(
                [
                    _BulkUser(email="c@example.com"),
                    _BulkUser(email="d@example.com"),
                ]
            ).returning(_BulkUser.id, _BulkUser.email)
        )

    assert_eq(len(ids), 2)
    assert all(isinstance(value, int) for value in ids)
    assert_eq(
        sorted(email for _, email in rows),
        ["c@example.com", "d@example.com"],
    )


@test(mark="medium")
async def mariadb_empty_bulk_insert_is_a_no_op() -> None:
    """A zero-row MariaDB bulk insert issues no SQL and writes nothing."""

    database = await load_fixture(database_session([_BulkUser]))
    async with database.transaction() as tx:
        no_rows: list[_BulkUser[Pending]] = []
        before = await tx.fetch_one(select(_BulkUser.id.count()).all())
        result = await tx.execute(insert(no_rows))
        returning = await tx.execute(insert(no_rows).returning())
        after = await tx.fetch_one(select(_BulkUser.id.count()).all())

    assert_is_none(result)
    assert_eq(returning, [])
    assert_eq(after, before)

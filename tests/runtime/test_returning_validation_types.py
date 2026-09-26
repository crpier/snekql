"""Unvalidated scalar RETURNING values expose storage values, not logical types."""

from typing import ClassVar, assert_type

from snektest import assert_eq, load_fixture, test

from snekql import mariadb, sqlite
from tests.helpers import initialized_database, provide_mariadb_server


@test(mark="medium")
async def unvalidated_integer_returning_exposes_text_storage() -> None:
    """An integer Logical Type stored in TEXT returns str without validation."""

    class Account[State = sqlite.Pending](sqlite.Model[State]):
        __row_type__: ClassVar[sqlite.ReadType[Account[sqlite.Row]]]
        number: sqlite.Col[int] = sqlite.Text()

    async with (
        await initialized_database(database=":memory:", models=[Account]) as database,
        database.transaction() as transaction,
    ):
        number = await transaction.execute(
            sqlite.insert(Account(number=7)).returning(Account.number),
            validate=False,
        )

    assert_eq(number, "7")
    assert_type(number, object)


@test(mark="slow")
async def mariadb_unvalidated_integer_returning_exposes_text_storage() -> None:
    """MariaDB also returns the storage value when logical validation is disabled."""
    server = await load_fixture(provide_mariadb_server())

    class Account[State = mariadb.Pending](mariadb.Model[State]):
        __row_type__: ClassVar[mariadb.ReadType[Account[mariadb.Row]]]
        number: mariadb.Col[int] = mariadb.Text()

    async with (
        await initialized_database(server.config(), models=[Account]) as database,
        database.transaction() as transaction,
    ):
        number = await transaction.execute(
            mariadb.insert(Account(number=7)).returning(Account.number),
            validate=False,
        )

    assert_eq(number, "7")
    assert_type(number, object)

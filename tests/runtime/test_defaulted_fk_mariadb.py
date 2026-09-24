"""Defaulted typed references through native transactions."""

from collections.abc import AsyncGenerator
from typing import assert_type

from snektest import assert_eq, assert_raises, fixture, load_fixture, test

from snekql import mariadb
from tests.helpers import provide_mariadb_server
from tests.test_defaulted_fk_typing_mariadb import Account, Defaults


class ManagerRole:
    """Separate query occurrence of the account table."""


@fixture
async def provide_accounts() -> AsyncGenerator[mariadb.Database]:
    """A root, its child and a soft reference with constructor defaults."""
    server = await load_fixture(provide_mariadb_server())
    async with await mariadb.Database.initialize(server.config()) as database:
        await database.migrate({"001_accounts": mariadb.scaffold([Account, Defaults])})
        async with database.transaction() as transaction:
            await transaction.execute(mariadb.insert(Account()))
            await transaction.execute(mariadb.insert(Account(manager_id=1)))
            await transaction.execute(mariadb.insert(Defaults()))
        yield database


@test(mark="slow")
async def omitted_nullable_reference_round_trips() -> None:
    """Omitting the typed self reference materializes SQL NULL."""
    database = await load_fixture(provide_accounts())

    async with database.transaction() as transaction:
        row = await transaction.fetch_one(
            mariadb.select(Account).where(Account.account_id.eq(1))
        )

    assert_type(row, Account[mariadb.Fetched])
    assert_eq(row.manager_id, None)


@test(mark="slow")
async def typed_self_reference_joins_an_alias() -> None:
    """The table-level self constraint supports ordinary aliased joins."""
    database = await load_fixture(provide_accounts())
    manager = mariadb.alias(Account, ManagerRole, name="manager")
    query = (
        mariadb.select(Account.account_id, manager.column(Account.account_id))
        .join(manager, on=Account.manager_id.eq_col(manager.column(Account.account_id)))
        .where(Account.account_id.eq(2))
    )

    async with database.transaction() as transaction:
        rows = await transaction.fetch_all(query)

    assert_type(rows, list[tuple[int, int]])
    assert_eq(rows, [(2, 1)])


@test(mark="slow")
async def typed_self_constraint_rejects_an_orphan() -> None:
    """Preserving FKCol does not bypass the explicit database constraint."""
    database = await load_fixture(provide_accounts())

    with assert_raises(mariadb.ExecutionError):
        async with database.transaction() as transaction:
            await transaction.execute(mariadb.insert(Account(manager_id=999)))


@test(mark="slow")
async def soft_reference_does_not_create_a_constraint() -> None:
    """Plain storage retains a typed target without enforcing its existence."""
    database = await load_fixture(provide_accounts())

    async with database.transaction() as transaction:
        await transaction.execute(mariadb.insert(Defaults(account_id=2, literal=999)))
    async with database.transaction() as transaction:
        rows = await transaction.fetch_all(
            mariadb.select(Defaults.literal).where(Defaults.account_id.eq(2))
        )

    assert_eq(rows, [999])


@test(mark="slow")
async def soft_reference_retains_the_typed_join_helper() -> None:
    """A defaulted FKCol still exposes its target-checked references helper."""
    database = await load_fixture(provide_accounts())
    query = (
        mariadb.select(Defaults.account_id, Account.account_id)
        .join(Account, on=Defaults.literal.references(Account.account_id))
        .all()
    )

    async with database.transaction() as transaction:
        rows = await transaction.fetch_all(query)

    assert_eq(rows, [(1, 1)])


@test(mark="slow")
async def soft_defaults_round_trip() -> None:
    """Literal and factory defaults survive typed reference materialization."""
    database = await load_fixture(provide_accounts())

    async with database.transaction() as transaction:
        rows = await transaction.fetch_all(
            mariadb.select(
                Defaults.literal, Defaults.factory, Defaults.null_factory
            ).all()
        )

    assert_type(rows, list[tuple[int, int, int | None]])
    assert_eq(rows, [(1, 1, None)])

"""Callable self targets through native statements and materialization."""

from collections.abc import AsyncGenerator
from typing import ClassVar, assert_type
from uuid import UUID

from snektest import assert_eq, assert_raises, fixture, load_fixture, test

from snekql import sqlite
from tests.test_callable_fk_typing_sqlite import Account, Other


class ManagerRole:
    """An independent occurrence of the same account table."""


@fixture
async def provide_accounts() -> AsyncGenerator[sqlite.Database]:
    """Seed a root and child using generated primary keys and callable defaults."""
    async with await sqlite.Database.initialize(database=":memory:") as database:
        await database.migrate({"001": sqlite.scaffold([Other, Account])})
        async with database.transaction() as transaction:
            await transaction.execute(sqlite.insert(Other(account_id=1, label="root")))
            await transaction.execute(sqlite.insert(Account()))
            await transaction.execute(sqlite.insert(Account(manager_id=1)))
        yield database


@test(mark="medium")
async def omitted_reference_round_trips() -> None:
    """The callable declaration keeps a nullable, omittable constructor field."""
    database = await load_fixture(provide_accounts())

    async with database.transaction() as transaction:
        account = await transaction.fetch_one(
            sqlite.select(Account).where(Account.account_id.eq(1))
        )

    assert_type(account, Account[sqlite.Row])
    assert_eq(account.manager_id, None)
    assert_eq(account.defaulted, 1)


@test(mark="medium")
async def self_reference_joins_an_alias() -> None:
    """Resolved descriptor identity survives independent alias occurrences."""
    database = await load_fixture(provide_accounts())
    manager = sqlite.alias(Account, ManagerRole, name="manager")
    query = (
        sqlite.select(Account.account_id, manager.column(Account.account_id))
        .join(
            manager,
            on=Account.manager_id.eq_col(manager.column(Account.account_id)),
        )
        .where(Account.account_id.eq(2))
    )

    async with database.transaction() as transaction:
        rows = await transaction.fetch_all(query)

    assert_type(rows, list[tuple[int, int]])
    assert_eq(rows, [(2, 1)])


@test(mark="medium")
async def scalar_constraint_rejects_an_orphan() -> None:
    """A callable physical target must not silently become a soft reference."""
    database = await load_fixture(provide_accounts())

    with assert_raises(sqlite.ExecutionError):
        async with database.transaction() as transaction:
            await transaction.execute(sqlite.insert(Account(manager_id=999)))


@test(mark="medium")
async def aliased_reference_keeps_its_decoder() -> None:
    """Copying a column for an alias retains the frozen derived storage."""
    database = await load_fixture(provide_accounts())
    account = sqlite.alias(Account, ManagerRole, name="account_copy")
    query = sqlite.select(account.column(Account.manager_id)).where(
        account.column(Account.account_id).eq(2),
    )

    async with database.transaction() as transaction:
        rows = await transaction.fetch_all(query)

    assert_type(rows, list[int | None])
    assert_eq(rows, [1])


class UuidAccount[S = sqlite.Pending](sqlite.Model[S]):
    """A logical UUID key with backend-specific physical storage."""

    __row_type__: ClassVar[sqlite.ReadType[UuidAccount[sqlite.Row]]]

    account_id: sqlite.Col[UUID] = sqlite.Blob(primary_key=True)
    manager_id: sqlite.FKCol[UuidAccount, UUID | None] = sqlite.ForeignKey(
        lambda: UuidAccount.account_id, default=None
    )


@fixture
async def provide_uuid_accounts() -> AsyncGenerator[sqlite.Database]:
    """Seed one reference whose Python domain differs from wire values."""
    async with await sqlite.Database.initialize(database=":memory:") as database:
        await database.migrate({"001": sqlite.scaffold([UuidAccount])})
        async with database.transaction() as transaction:
            await transaction.execute(
                sqlite.insert(UuidAccount(account_id=UUID(int=1)))
            )
            await transaction.execute(
                sqlite.insert(
                    UuidAccount(account_id=UUID(int=2), manager_id=UUID(int=1))
                )
            )
        yield database


@test(mark="medium")
async def reference_preserves_logical_uuid_codec() -> None:
    """Derived storage materializes UUIDs rather than leaking driver values."""
    database = await load_fixture(provide_uuid_accounts())

    async with database.transaction() as transaction:
        account = await transaction.fetch_one(
            sqlite.select(UuidAccount).where(UuidAccount.account_id.eq(UUID(int=2)))
        )

    assert_type(account.manager_id, UUID | None)
    assert_eq(account.manager_id, UUID(int=1))

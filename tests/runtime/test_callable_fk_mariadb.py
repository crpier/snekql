"""Callable self targets through native statements and materialization."""

from collections.abc import AsyncGenerator
from decimal import Decimal
from typing import ClassVar, assert_type
from uuid import UUID

from snektest import assert_eq, assert_raises, fixture, load_fixture, test

from snekql import mariadb
from tests.helpers import provide_mariadb_server
from tests.test_callable_fk_typing_mariadb import Account, Other


class ManagerRole:
    """An independent occurrence of the same account table."""


@fixture
async def provide_accounts() -> AsyncGenerator[mariadb.Database]:
    """Seed a root and child using generated primary keys and callable defaults."""
    server = await load_fixture(provide_mariadb_server())
    async with await mariadb.Database.initialize(server.config()) as database:
        await database.migrate({"001": mariadb.scaffold([Other, Account])})
        async with database.transaction() as transaction:
            await transaction.execute(mariadb.insert(Other(account_id=1, label="root")))
            await transaction.execute(mariadb.insert(Account()))
            await transaction.execute(mariadb.insert(Account(manager_id=1)))
        yield database


@test(mark="slow")
async def omitted_reference_round_trips() -> None:
    """The callable declaration keeps a nullable, omittable constructor field."""
    database = await load_fixture(provide_accounts())

    async with database.transaction() as transaction:
        account = await transaction.fetch_one(
            mariadb.select(Account).where(Account.account_id.eq(1))
        )

    assert_type(account, Account[mariadb.Row])
    assert_eq(account.manager_id, None)
    assert_eq(account.defaulted, 1)


@test(mark="slow")
async def self_reference_joins_an_alias() -> None:
    """Resolved descriptor identity survives independent alias occurrences."""
    database = await load_fixture(provide_accounts())
    manager = mariadb.alias(Account, ManagerRole, name="manager")
    query = (
        mariadb.select(Account.account_id, manager.column(Account.account_id))
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


@test(mark="slow")
async def scalar_constraint_rejects_an_orphan() -> None:
    """A callable physical target must not silently become a soft reference."""
    database = await load_fixture(provide_accounts())

    with assert_raises(mariadb.ExecutionError):
        async with database.transaction() as transaction:
            await transaction.execute(mariadb.insert(Account(manager_id=999)))


@test(mark="slow")
async def aliased_reference_keeps_its_decoder() -> None:
    """Copying a column for an alias retains the frozen derived storage."""
    database = await load_fixture(provide_accounts())
    account = mariadb.alias(Account, ManagerRole, name="account_copy")
    query = mariadb.select(account.column(Account.manager_id)).where(
        account.column(Account.account_id).eq(2),
    )

    async with database.transaction() as transaction:
        rows = await transaction.fetch_all(query)

    assert_type(rows, list[int | None])
    assert_eq(rows, [1])


@fixture
async def provide_decimal_accounts() -> AsyncGenerator[mariadb.Database]:
    """A decimal key exercises native precision and scale derivation."""
    server = await load_fixture(provide_mariadb_server())
    async with await mariadb.Database.initialize(server.config()) as database:
        await database.migrate({"001": mariadb.scaffold([DecimalAccount])})
        async with database.transaction() as transaction:
            await transaction.execute(
                mariadb.insert(DecimalAccount(account_id=Decimal("1.20")))
            )
            await transaction.execute(
                mariadb.insert(
                    DecimalAccount(
                        account_id=Decimal("2.30"), manager_id=Decimal("1.20")
                    )
                )
            )
        yield database


class DecimalAccount[S = mariadb.Pending](mariadb.Model[S]):
    """A self relationship whose storage requires explicit native dimensions."""

    __row_type__: ClassVar[mariadb.ReadType[DecimalAccount[mariadb.Row]]]

    account_id: mariadb.Col[Decimal] = mariadb.Decimal(
        precision=12, scale=2, primary_key=True
    )
    manager_id: mariadb.FKCol[DecimalAccount, Decimal | None] = mariadb.ForeignKey(
        lambda: DecimalAccount.account_id, default=None
    )


@test(mark="slow")
async def decimal_reference_derives_native_dimensions() -> None:
    """The FK retains the target precision, scale and logical decimal codec."""
    database = await load_fixture(provide_decimal_accounts())

    async with database.transaction() as transaction:
        account = await transaction.fetch_one(
            mariadb.select(DecimalAccount).where(
                DecimalAccount.account_id.eq(Decimal("2.30"))
            )
        )

    assert_eq(account.manager_id, Decimal("1.20"))


class UuidAccount[S = mariadb.Pending](mariadb.Model[S]):
    """A logical UUID key with backend-specific physical storage."""

    __row_type__: ClassVar[mariadb.ReadType[UuidAccount[mariadb.Row]]]

    account_id: mariadb.Col[UUID] = mariadb.Uuid(primary_key=True)
    manager_id: mariadb.FKCol[UuidAccount, UUID | None] = mariadb.ForeignKey(
        lambda: UuidAccount.account_id, default=None
    )


@fixture
async def provide_uuid_accounts() -> AsyncGenerator[mariadb.Database]:
    """Seed one reference whose Python domain differs from wire values."""
    server = await load_fixture(provide_mariadb_server())
    async with await mariadb.Database.initialize(server.config()) as database:
        await database.migrate({"001": mariadb.scaffold([UuidAccount])})
        async with database.transaction() as transaction:
            await transaction.execute(
                mariadb.insert(UuidAccount(account_id=UUID(int=1)))
            )
            await transaction.execute(
                mariadb.insert(
                    UuidAccount(account_id=UUID(int=2), manager_id=UUID(int=1))
                )
            )
        yield database


@test(mark="slow")
async def reference_preserves_logical_uuid_codec() -> None:
    """Derived storage materializes UUIDs rather than leaking driver values."""
    database = await load_fixture(provide_uuid_accounts())

    async with database.transaction() as transaction:
        account = await transaction.fetch_one(
            mariadb.select(UuidAccount).where(UuidAccount.account_id.eq(UUID(int=2)))
        )

    assert_type(account.manager_id, UUID | None)
    assert_eq(account.manager_id, UUID(int=1))

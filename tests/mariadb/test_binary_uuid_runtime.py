"""Binary UUID persistence through MariaDB's public runtime."""

from __future__ import annotations

from uuid import UUID

from snektest import assert_eq, load_fixture, test

from snekql import mariadb
from snekql.mariadb import Fetched, Pending, insert, select
from tests.helpers import initialized_database, provide_mariadb_server


@test(mark="slow")
async def uuid_blob_uses_binary_wire_form() -> None:
    """Blob must persist UUID bytes, not the driver's string fallback."""
    server = await load_fixture(provide_mariadb_server())

    class Account[S = Pending](mariadb.Model[S, "Account[Fetched]"]):
        """A binary account key with a separate integer primary key."""

        __tablename__ = "binary_uuid_account"

        account_id: Account.Col[UUID] = mariadb.Blob()
        id: Account.Col[int] = mariadb.Integer(primary_key=True)

    account_id = UUID("00112233-4455-6677-8899-aabbccddeeff")
    async with await initialized_database(
        server.config(), models=[Account]
    ) as database:
        async with database.transaction() as tx:
            await tx.execute(insert(Account(account_id=account_id, id=1)))

        async with database.transaction() as tx:
            stored_bytes = await tx.fetch_one(
                select(Account.account_id).all(), validate=False
            )

    assert_eq(stored_bytes, account_id.bytes)

"""Binary UUID persistence through SQLite's public runtime."""

from __future__ import annotations

from uuid import UUID

from snektest import assert_eq, test

from snekql.sqlite import Blob, Fetched, Model, Pending, insert, select
from tests.helpers import initialized_database


@test(mark="medium")
async def uuid_blob_round_trips() -> None:
    """A UUID paired with Blob stores its 16 bytes and decodes as a UUID."""

    class Account[S = Pending](Model[S, "Account[Fetched]"]):
        """A client-assigned binary account key."""

        account_id: Account.Col[UUID] = Blob(primary_key=True)

    account_id = UUID("00112233-4455-6677-8899-aabbccddeeff")
    async with await initialized_database(
        database=":memory:", models=[Account]
    ) as database:
        async with database.transaction() as tx:
            await tx.execute(insert(Account(account_id=account_id)))

        async with database.transaction() as tx:
            stored_key = await tx.fetch_one(select(Account.account_id).all())

    assert_eq(stored_key, account_id)

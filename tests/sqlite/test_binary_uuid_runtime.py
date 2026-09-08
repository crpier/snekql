"""UUID Blob values use binary wire encoding through public database operations."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from pydantic import UUID4, BeforeValidator, PlainSerializer
from snektest import Param, assert_eq, assert_raises, test

from snekql import sqlite
from snekql.errors import ModelValidationError
from tests.helpers import initialized_database


class Account[S = sqlite.Pending](sqlite.Model[S, "Account[sqlite.Fetched]"]):
    """A UUID stored in a binary column rather than text."""

    id: Account.Col[int] = sqlite.Integer(primary_key=True)
    account_id: Account.Col[UUID] = sqlite.Blob(nullable=False)


@test(mark="medium")
async def uuid_blob_stores_sixteen_bytes() -> None:
    """The driver must receive UUID bytes, not a UUID object or its ASCII text."""

    async with await initialized_database(
        database=":memory:", models=[Account]
    ) as database:
        async with database.transaction() as setup:
            await setup.execute(
                sqlite.insert(
                    Account(
                        id=1, account_id=UUID("00112233-4455-4677-8899-aabbccddeeff")
                    )
                )
            )

        async with database.transaction() as tx:
            raw = await tx.fetch_one(
                sqlite.select(Account.account_id).all(), validate=False
            )

    assert_eq(raw, bytes.fromhex("00112233445546778899aabbccddeeff"))


@test([Param(value=form, name=form) for form in ("eq", "in")], mark="medium")
async def uuid_predicates_find_binary_rows(form: str) -> None:
    """Equality and membership share the binary encoding used by writes."""

    account_id = UUID("00112233-4455-4677-8899-aabbccddeeff")
    async with await initialized_database(
        database=":memory:", models=[Account]
    ) as database:
        async with database.transaction() as setup:
            await setup.execute(sqlite.insert(Account(id=1, account_id=account_id)))

        predicate = (
            Account.account_id.eq(account_id)
            if form == "eq"
            else Account.account_id.in_(account_id, UUID(int=0))
        )
        async with database.transaction() as tx:
            rows = await tx.fetch_all(
                sqlite.select(Account.account_id).where(predicate)
            )

    assert_eq(rows, [account_id])


@test(mark="medium")
async def uuid_update_writes_binary_values() -> None:
    """Assignments use the corrected Blob encoding as well as inserts."""

    async with await initialized_database(
        database=":memory:", models=[Account]
    ) as database:
        async with database.transaction() as setup:
            await setup.execute(sqlite.insert(Account(id=1, account_id=UUID(int=0))))

        async with database.transaction() as tx:
            await tx.execute(
                sqlite.update(Account)
                .set(
                    Account.account_id.to(UUID("00112233-4455-4677-8899-aabbccddeeff"))
                )
                .where(Account.id.eq(1))
            )

        async with database.transaction() as tx:
            raw = await tx.fetch_one(
                sqlite.select(Account.account_id).all(), validate=False
            )

    assert_eq(raw, bytes.fromhex("00112233445546778899aabbccddeeff"))


@test(mark="medium")
async def constrained_uuid_versions_still_validate_on_fetch() -> None:
    """Binary wire shaping does not replace Pydantic's UUID version validation."""

    class Versioned[S = sqlite.Pending](sqlite.Model[S, "Versioned[sqlite.Fetched]"]):
        """A UUID field constrained to version four."""

        id: Versioned.Col[int] = sqlite.Integer(primary_key=True)
        account_id: Versioned.Col[UUID4] = sqlite.Blob(nullable=False)

    account_id = UUID("00112233-4455-4677-8899-aabbccddeeff")
    async with await initialized_database(
        database=":memory:", models=[Versioned]
    ) as database:
        async with database.transaction() as setup:
            await setup.execute(sqlite.insert(Versioned(id=1, account_id=account_id)))
            await setup.execute(
                sqlite.insert(Versioned.construct(id=2, account_id=UUID(int=0)))
            )

        async with database.transaction() as tx:
            valid = await tx.fetch_one(
                sqlite.select(Versioned.account_id).where(Versioned.id.eq(1))
            )
            with assert_raises(ModelValidationError):
                await tx.fetch_one(
                    sqlite.select(Versioned.account_id).where(Versioned.id.eq(2))
                )

    assert_eq(valid, account_id)


@test(mark="medium")
async def custom_uuid_bytes_serializer_keeps_control_of_wire_form() -> None:
    """A user-selected little-endian byte representation is not replaced."""

    def decode_little_endian(value: object) -> object:
        """Restore the logical UUID for this custom binary representation."""

        return UUID(bytes_le=value) if isinstance(value, bytes) else value

    def encode_little_endian(value: UUID) -> bytes:
        """Select the custom UUID byte order at the serializer boundary."""

        return value.bytes_le

    class Custom[S = sqlite.Pending](sqlite.Model[S, "Custom[sqlite.Fetched]"]):
        """An explicitly serialized UUID uses its chosen bytes."""

        account_id: Custom.Col[
            Annotated[
                UUID,
                BeforeValidator(decode_little_endian),
                PlainSerializer(encode_little_endian, return_type=bytes),
            ]
        ] = sqlite.Blob(nullable=False)

    account_id = UUID("00112233-4455-4677-8899-aabbccddeeff")
    async with await initialized_database(
        database=":memory:", models=[Custom]
    ) as database:
        async with database.transaction() as setup:
            await setup.execute(sqlite.insert(Custom(account_id=account_id)))

        async with database.transaction() as tx:
            raw = await tx.fetch_one(
                sqlite.select(Custom.account_id).all(), validate=False
            )
            logical = await tx.fetch_one(
                sqlite.select(Custom.account_id).where(Custom.account_id.eq(account_id))
            )

    assert_eq(raw, bytes.fromhex("33221100554477468899aabbccddeeff"))
    assert_eq(logical, account_id)


@test(mark="medium")
async def text_uuid_encoding_is_unchanged() -> None:
    """Text UUID columns retain their hyphenated string encoding."""

    class TextAccount[S = sqlite.Pending](
        sqlite.Model[S, "TextAccount[sqlite.Fetched]"]
    ):
        """Text storage remains an independent wire choice."""

        account_id: TextAccount.Col[UUID] = sqlite.Text(nullable=False)

    async with await initialized_database(
        database=":memory:", models=[TextAccount]
    ) as database:
        async with database.transaction() as setup:
            await setup.execute(
                sqlite.insert(
                    TextAccount(account_id=UUID("00112233-4455-4677-8899-aabbccddeeff"))
                )
            )

        async with database.transaction() as tx:
            raw = await tx.fetch_one(
                sqlite.select(TextAccount.account_id).all(), validate=False
            )

    assert_eq(raw, "00112233-4455-4677-8899-aabbccddeeff")

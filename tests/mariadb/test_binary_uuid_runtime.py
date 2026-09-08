"""UUID Blob values use binary wire encoding through public database operations."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from pydantic import UUID4, BeforeValidator, PlainSerializer
from snektest import Param, assert_eq, assert_raises, load_fixture, test

from snekql import mariadb
from snekql.errors import ModelValidationError
from tests.helpers import initialized_database, provide_mariadb_server


class Account[S = mariadb.Pending](mariadb.Model[S, "Account[mariadb.Fetched]"]):
    """A UUID stored in a binary column rather than text."""

    id: Account.Col[int] = mariadb.Integer(primary_key=True)
    account_id: Account.Col[UUID] = mariadb.Blob(nullable=False)


@test(mark="medium")
async def uuid_blob_stores_sixteen_bytes() -> None:
    """The driver must receive UUID bytes, not a UUID object or its ASCII text."""

    server = await load_fixture(provide_mariadb_server())

    async with await initialized_database(
        server.config(), models=[Account]
    ) as database:
        async with database.transaction() as setup:
            await setup.execute(
                mariadb.insert(
                    Account(
                        id=1, account_id=UUID("00112233-4455-4677-8899-aabbccddeeff")
                    )
                )
            )

        async with database.transaction() as tx:
            raw = await tx.fetch_one(
                mariadb.select(Account.account_id).all(), validate=False
            )

    assert_eq(raw, bytes.fromhex("00112233445546778899aabbccddeeff"))


@test([Param(value=form, name=form) for form in ("eq", "in")], mark="medium")
async def uuid_predicates_find_binary_rows(form: str) -> None:
    """Equality and membership share the binary encoding used by writes."""

    server = await load_fixture(provide_mariadb_server())

    account_id = UUID("00112233-4455-4677-8899-aabbccddeeff")
    async with await initialized_database(
        server.config(), models=[Account]
    ) as database:
        async with database.transaction() as setup:
            await setup.execute(mariadb.insert(Account(id=1, account_id=account_id)))

        predicate = (
            Account.account_id.eq(account_id)
            if form == "eq"
            else Account.account_id.in_(account_id, UUID(int=0))
        )
        async with database.transaction() as tx:
            rows = await tx.fetch_all(
                mariadb.select(Account.account_id).where(predicate)
            )

    assert_eq(rows, [account_id])


@test(mark="medium")
async def uuid_update_writes_binary_values() -> None:
    """Assignments use the corrected Blob encoding as well as inserts."""

    server = await load_fixture(provide_mariadb_server())

    async with await initialized_database(
        server.config(), models=[Account]
    ) as database:
        async with database.transaction() as setup:
            await setup.execute(mariadb.insert(Account(id=1, account_id=UUID(int=0))))

        async with database.transaction() as tx:
            await tx.execute(
                mariadb.update(Account)
                .set(
                    Account.account_id.to(UUID("00112233-4455-4677-8899-aabbccddeeff"))
                )
                .where(Account.id.eq(1))
            )

        async with database.transaction() as tx:
            raw = await tx.fetch_one(
                mariadb.select(Account.account_id).all(), validate=False
            )

    assert_eq(raw, bytes.fromhex("00112233445546778899aabbccddeeff"))


@test(mark="medium")
async def constrained_uuid_versions_still_validate_on_fetch() -> None:
    """Binary wire shaping does not replace Pydantic's UUID version validation."""

    server = await load_fixture(provide_mariadb_server())

    class Versioned[S = mariadb.Pending](
        mariadb.Model[S, "Versioned[mariadb.Fetched]"]
    ):
        """A UUID field constrained to version four."""

        id: Versioned.Col[int] = mariadb.Integer(primary_key=True)
        account_id: Versioned.Col[UUID4] = mariadb.Blob(nullable=False)

    account_id = UUID("00112233-4455-4677-8899-aabbccddeeff")
    async with await initialized_database(
        server.config(), models=[Versioned]
    ) as database:
        async with database.transaction() as setup:
            await setup.execute(mariadb.insert(Versioned(id=1, account_id=account_id)))
            await setup.execute(
                mariadb.insert(Versioned.construct(id=2, account_id=UUID(int=0)))
            )

        async with database.transaction() as tx:
            valid = await tx.fetch_one(
                mariadb.select(Versioned.account_id).where(Versioned.id.eq(1))
            )
            with assert_raises(ModelValidationError):
                await tx.fetch_one(
                    mariadb.select(Versioned.account_id).where(Versioned.id.eq(2))
                )

    assert_eq(valid, account_id)


@test(mark="medium")
async def custom_uuid_bytes_serializer_keeps_control_of_wire_form() -> None:
    """A user-selected little-endian byte representation is not replaced."""

    server = await load_fixture(provide_mariadb_server())

    def decode_little_endian(value: object) -> object:
        """Restore the logical UUID for this custom binary representation."""

        return UUID(bytes_le=value) if isinstance(value, bytes) else value

    def encode_little_endian(value: UUID) -> bytes:
        """Select the custom UUID byte order at the serializer boundary."""

        return value.bytes_le

    class Custom[S = mariadb.Pending](mariadb.Model[S, "Custom[mariadb.Fetched]"]):
        """An explicitly serialized UUID uses its chosen bytes."""

        account_id: Custom.Col[
            Annotated[
                UUID,
                BeforeValidator(decode_little_endian),
                PlainSerializer(encode_little_endian, return_type=bytes),
            ]
        ] = mariadb.Blob(nullable=False)

    account_id = UUID("00112233-4455-4677-8899-aabbccddeeff")
    async with await initialized_database(server.config(), models=[Custom]) as database:
        async with database.transaction() as setup:
            await setup.execute(mariadb.insert(Custom(account_id=account_id)))

        async with database.transaction() as tx:
            raw = await tx.fetch_one(
                mariadb.select(Custom.account_id).all(), validate=False
            )
            logical = await tx.fetch_one(
                mariadb.select(Custom.account_id).where(
                    Custom.account_id.eq(account_id)
                )
            )

    assert_eq(raw, bytes.fromhex("33221100554477468899aabbccddeeff"))
    assert_eq(logical, account_id)


@test(mark="medium")
async def text_uuid_encoding_is_unchanged() -> None:
    """Text UUID columns retain their hyphenated string encoding."""

    server = await load_fixture(provide_mariadb_server())

    class TextAccount[S = mariadb.Pending](
        mariadb.Model[S, "TextAccount[mariadb.Fetched]"]
    ):
        """Text storage remains an independent wire choice."""

        account_id: TextAccount.Col[UUID] = mariadb.Text(nullable=False)

    async with await initialized_database(
        server.config(), models=[TextAccount]
    ) as database:
        async with database.transaction() as setup:
            await setup.execute(
                mariadb.insert(
                    TextAccount(account_id=UUID("00112233-4455-4677-8899-aabbccddeeff"))
                )
            )

        async with database.transaction() as tx:
            raw = await tx.fetch_one(
                mariadb.select(TextAccount.account_id).all(), validate=False
            )

    assert_eq(raw, "00112233-4455-4677-8899-aabbccddeeff")


class LegacyAccount[S = mariadb.Pending](
    mariadb.Model[S, "LegacyAccount[mariadb.Fetched]"]
):
    """A byte-oriented view used to seed historical ASCII UUID storage."""

    __tablename__ = "account"
    id: LegacyAccount.Col[int] = mariadb.Integer(primary_key=True)
    account_id: LegacyAccount.Col[bytes] = mariadb.Blob(nullable=False)


@test(mark="medium")
async def legacy_ascii_uuids_remain_readable_but_need_equality_migration() -> None:
    """Typed reads preserve legacy compatibility without dual-format predicates."""

    server = await load_fixture(provide_mariadb_server())
    async with await initialized_database(
        server.config(), models=[Account]
    ) as database:
        async with database.transaction() as setup:
            await setup.execute(
                mariadb.insert(
                    LegacyAccount(
                        id=1, account_id=b"00112233-4455-4677-8899-aabbccddeeff"
                    )
                )
            )

        account_id = UUID("00112233-4455-4677-8899-aabbccddeeff")
        async with database.transaction() as tx:
            logical = await tx.fetch_one(mariadb.select(Account.account_id).all())
            matched = await tx.fetch_all(
                mariadb.select(Account.id).where(Account.account_id.eq(account_id))
            )
            raw = await tx.fetch_one(
                mariadb.select(Account.account_id).all(), validate=False
            )

    assert_eq(logical, account_id)
    assert_eq(matched, [])
    assert_eq(raw, b"00112233-4455-4677-8899-aabbccddeeff")


@test(mark="medium")
async def explicit_rewrite_by_stable_key_restores_binary_uuid_equality() -> None:
    """Migration must find legacy rows independently of corrected UUID predicates."""

    server = await load_fixture(provide_mariadb_server())
    async with await initialized_database(
        server.config(), models=[Account]
    ) as database:
        async with database.transaction() as setup:
            await setup.execute(
                mariadb.insert(
                    LegacyAccount(
                        id=1, account_id=b"00112233-4455-4677-8899-aabbccddeeff"
                    )
                )
            )

        async with database.transaction() as migration:
            logical = await migration.fetch_one(
                mariadb.select(Account.account_id).where(Account.id.eq(1))
            )
            await migration.execute(
                mariadb.update(Account)
                .set(Account.account_id.to(logical))
                .where(Account.id.eq(1))
            )

        async with database.transaction() as tx:
            raw = await tx.fetch_one(
                mariadb.select(Account.account_id).where(
                    Account.account_id.eq(UUID("00112233-4455-4677-8899-aabbccddeeff"))
                ),
                validate=False,
            )

    assert_eq(raw, bytes.fromhex("00112233445546778899aabbccddeeff"))

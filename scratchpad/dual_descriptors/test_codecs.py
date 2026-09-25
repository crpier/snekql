"""Native descriptor assembly must preserve storage codecs and value contracts."""

from collections.abc import AsyncGenerator
from datetime import UTC, datetime
from typing import assert_type
from uuid import UUID

from pydantic import Json
from snekql import sqlite as native
from snektest import assert_eq, fixture, load_fixture, test

from scratchpad.dual_descriptors import sqlite


@fixture
async def database() -> AsyncGenerator[native.Database]:
    async with await native.Database.initialize(database=":memory:") as connected:
        yield connected


@test(mark="medium")
async def direct_blob_projection_keeps_bytes() -> None:
    connected = await load_fixture(database())

    class Payload(sqlite.Model):
        __row__ = sqlite.paired(lambda: PayloadRow)
        content: sqlite.Col[bytes] = sqlite.Blob()

    class PayloadRow(Payload, sqlite.Row):
        table_name = "payloads"

    await connected.migrate({"001": sqlite.scaffold(PayloadRow)})
    async with connected.transaction() as native_transaction:
        transaction = sqlite.Transaction(native_transaction)
        await transaction.execute(sqlite.insert(Payload(content=b"\x00\xff")))
    async with connected.transaction() as transaction:
        rows = await transaction.fetch_all(native.select(PayloadRow.content).all())
    assert_type(rows, list[bytes])
    assert_eq(rows, [b"\x00\xff"])


@test(mark="medium")
async def direct_real_projection_keeps_float() -> None:
    connected = await load_fixture(database())

    class Reading(sqlite.Model):
        __row__ = sqlite.paired(lambda: ReadingRow)
        value: sqlite.Col[float] = sqlite.Real()

    class ReadingRow(Reading, sqlite.Row):
        table_name = "readings"

    await connected.migrate({"001": sqlite.scaffold(ReadingRow)})
    async with connected.transaction() as native_transaction:
        await sqlite.Transaction(native_transaction).execute(
            sqlite.insert(Reading(value=1.25))
        )
    async with connected.transaction() as transaction:
        rows = await transaction.fetch_all(
            native.select(ReadingRow.value.add(0.5)).all()
        )
    assert_type(rows, list[float])
    assert_eq(rows, [1.75])


@test(mark="medium")
async def direct_text_projection_decodes_logical_types() -> None:
    connected = await load_fixture(database())

    class Payload(sqlite.Model):
        __row__ = sqlite.paired(lambda: PayloadRow)
        identity: sqlite.Col[UUID] = sqlite.Text()
        created: sqlite.Col[datetime] = sqlite.Text()
        data: sqlite.Col[Json[dict[str, int]]] = sqlite.Text()

    class PayloadRow(Payload, sqlite.Row):
        table_name = "payloads"

    await connected.migrate({"001": sqlite.scaffold(PayloadRow)})
    async with connected.transaction() as native_transaction:
        await sqlite.Transaction(native_transaction).execute(
            sqlite.insert(
                Payload(
                    identity=UUID(int=1),
                    created=datetime(2026, 1, 2, tzinfo=UTC),
                    data={"count": 2},
                )
            )
        )
    async with connected.transaction() as transaction:
        rows = await transaction.fetch_all(
            native.select(
                PayloadRow.identity, PayloadRow.created, PayloadRow.data
            ).all()
        )
    assert_type(rows, list[tuple[UUID, datetime, dict[str, int]]])
    assert_eq(rows, [(UUID(int=1), datetime(2026, 1, 2, tzinfo=UTC), {"count": 2})])

"""Blob SQLite runtime behavior tests."""

from __future__ import annotations

from snektest import assert_eq, assert_true, test

from snekql.sqlite import Blob, Fetched, Integer, Model, Pending, insert, select
from tests.helpers import initialized_database


class BinaryRecord[S = Pending](Model[S, "BinaryRecord[Fetched]"]):
    """Binary record table with blob payload storage."""

    id: BinaryRecord.Col[BinaryRecord, int] = Integer(primary_key=True)
    payload: BinaryRecord.Col[BinaryRecord, bytes] = Blob(nullable=False)


class OptionalBinaryRecord[S = Pending](Model[S, "OptionalBinaryRecord[Fetched]"]):
    """Binary record table with a nullable blob payload."""

    id: OptionalBinaryRecord.Col[OptionalBinaryRecord, int] = Integer(primary_key=True)
    payload: OptionalBinaryRecord.Col[OptionalBinaryRecord, bytes | None] = Blob(
        nullable=True, default=None
    )


@test(mark="medium")
async def blob_storage_round_trips_bytes() -> None:
    """Bytes values round-trip through SQLite Blob storage as ``bytes``."""

    database = await initialized_database(database=":memory:", models=[BinaryRecord])
    try:
        async with database.transaction() as tx:
            await tx.execute(insert(BinaryRecord(id=1, payload=b"\x00snek\xff")))
            fetched = await tx.fetch_one(select(BinaryRecord.payload).all())
    finally:
        await database.close()

    assert_eq(fetched, b"\x00snek\xff")
    assert_true(type(fetched) is bytes)


@test(mark="medium")
async def blob_storage_round_trips_payload_variants() -> None:
    """Empty, NUL/0xFF-laden, and megabyte-sized payloads survive the round trip."""

    payloads = [b"", b"\x00\xff\x00\xff", b"\x00\xff" * 524_288]
    database = await initialized_database(database=":memory:", models=[BinaryRecord])
    try:
        async with database.transaction() as tx:
            for index, payload in enumerate(payloads, start=1):
                await tx.execute(insert(BinaryRecord(id=index, payload=payload)))
            fetched = await tx.fetch_all(
                select(BinaryRecord.payload).all().order_by(BinaryRecord.id.asc())
            )
    finally:
        await database.close()

    assert_eq(fetched, payloads)
    for payload in fetched:
        assert_true(type(payload) is bytes)


@test(mark="medium")
async def nullable_blob_storage_round_trips_null() -> None:
    """A nullable blob column stores SQL ``NULL`` and reads it back as ``None``."""

    database = await initialized_database(
        database=":memory:", models=[OptionalBinaryRecord]
    )
    try:
        async with database.transaction() as tx:
            await tx.execute(insert(OptionalBinaryRecord(id=1)))
            await tx.execute(insert(OptionalBinaryRecord(id=2, payload=b"present")))
            fetched = await tx.fetch_all(
                select(OptionalBinaryRecord.payload)
                .all()
                .order_by(OptionalBinaryRecord.id.asc())
            )
    finally:
        await database.close()

    assert_eq(fetched, [None, b"present"])

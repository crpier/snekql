"""Blob MariaDB runtime behavior tests."""

from __future__ import annotations

from snektest import assert_eq, assert_true, load_fixture, test

from snekql import mariadb
from snekql.mariadb import Fetched, Pending, insert, select
from tests.helpers import initialized_database, provide_mariadb_server


@test(mark="medium")
async def mariadb_blob_storage_round_trips_bytes() -> None:
    """Bytes values round-trip through MariaDB Blob storage as ``bytes``."""

    server = await load_fixture(provide_mariadb_server())

    class BinaryRecord[S = Pending](mariadb.Model[S, "BinaryRecord[Fetched]"]):
        """Binary record table with blob payload storage."""

        __tablename__ = "blob_roundtrip"

        id: BinaryRecord.Col[int] = mariadb.Integer(primary_key=True)
        payload: BinaryRecord.Col[bytes] = mariadb.Blob(nullable=False)

    database = await initialized_database(server.config(), models=[BinaryRecord])
    try:
        async with database.transaction() as tx:
            await tx.execute(insert(BinaryRecord(id=1, payload=b"\x00snek\xff")))
            fetched = await tx.fetch_one(select(BinaryRecord.payload).all())
    finally:
        await database.close()

    assert_eq(fetched, b"\x00snek\xff")
    assert_true(type(fetched) is bytes)


@test(mark="medium")
async def mariadb_blob_storage_round_trips_payload_variants() -> None:
    """Empty, NUL/0xFF-laden, and cap-sized (64 KiB - 1) payloads survive the
    round trip."""

    server = await load_fixture(provide_mariadb_server())

    class BinaryRecord[S = Pending](mariadb.Model[S, "BinaryRecord[Fetched]"]):
        """Binary record table with blob payload storage."""

        __tablename__ = "blob_payload_variants"

        id: BinaryRecord.Col[int] = mariadb.Integer(primary_key=True)
        payload: BinaryRecord.Col[bytes] = mariadb.Blob(nullable=False)

    cap_sized = b"\x00\xff" * 32_767 + b"\x00"
    assert_eq(len(cap_sized), 65_535)
    payloads = [b"", b"\x00\xff\x00\xff", cap_sized]
    database = await initialized_database(server.config(), models=[BinaryRecord])
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
async def mariadb_nullable_blob_storage_round_trips_null() -> None:
    """A nullable blob column stores SQL ``NULL`` and reads it back as ``None``."""

    server = await load_fixture(provide_mariadb_server())

    class OptionalBinaryRecord[S = Pending](
        mariadb.Model[S, "OptionalBinaryRecord[Fetched]"]
    ):
        """Binary record table with a nullable blob payload."""

        __tablename__ = "blob_nullable"

        id: OptionalBinaryRecord.Col[int] = mariadb.Integer(primary_key=True)
        payload: OptionalBinaryRecord.Col[bytes | None] = mariadb.Blob(
            nullable=True, default=None
        )

    database = await initialized_database(
        server.config(), models=[OptionalBinaryRecord]
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

"""Whole-model joins distinguish absent rows from rows containing only NULLs."""

from collections.abc import AsyncGenerator
from typing import ClassVar

from snektest import Param, assert_eq, fixture, load_fixture, test

from snekql import mariadb, sqlite
from tests.helpers import provide_mariadb_server


class Anchor[S = sqlite.Pending](sqlite.Model[S]):
    __row_type__: ClassVar[sqlite.ReadType[Anchor[sqlite.Row]]]
    id: Anchor.Col[int] = sqlite.Integer(primary_key=True)


class NullableRow[S = sqlite.Pending](sqlite.Model[S]):
    __row_type__: ClassVar[sqlite.ReadType[NullableRow[sqlite.Row]]]
    value: NullableRow.Col[int | None] = sqlite.Integer()


@fixture
async def nullable_rows() -> AsyncGenerator[sqlite.Database]:
    """Two anchors, one actual row whose entire declared payload is NULL."""
    async with await sqlite.Database.initialize(database=":memory:") as database:
        await database.migrate({"001": sqlite.scaffold([Anchor, NullableRow])})
        async with database.transaction() as transaction:
            await transaction.execute(
                sqlite.insert_many(Anchor, [Anchor(id=1), Anchor(id=2)])
            )
            await transaction.execute(sqlite.insert(NullableRow(value=None)))
        yield database


class PeerRole:
    """An independent query role for the nullable physical table."""


@test([Param("table", name="table"), Param("alias", name="alias")], mark="medium")
async def matched_all_null_table_row_is_not_absent(source_kind: str) -> None:
    """A predicate on the anchor can match an actual all-NULL right row."""
    database = await load_fixture(nullable_rows())
    query = (
        sqlite.select(Anchor)
        .left_join(
            sqlite.alias(NullableRow, PeerRole, name="peer")
            if source_kind == "alias"
            else NullableRow,
            on=Anchor.id.eq(1),
        )
        .all()
        .order_by(Anchor.id.asc())
    )

    async with database.transaction() as transaction:
        rows = await transaction.fetch_all(query)

    assert_eq(
        [(anchor.id, right is not None) for anchor, right in rows],
        [(1, True), (2, False)],
    )


class NativeAnchor[S = mariadb.Pending](mariadb.Model[S]):
    __row_type__: ClassVar[mariadb.ReadType[NativeAnchor[mariadb.Row]]]
    id: NativeAnchor.Col[int] = mariadb.Integer(primary_key=True)


class NativeNullableRow[S = mariadb.Pending](mariadb.Model[S]):
    __row_type__: ClassVar[mariadb.ReadType[NativeNullableRow[mariadb.Row]]]
    value: NativeNullableRow.Col[int | None] = mariadb.Integer()


@fixture
async def native_nullable_rows() -> AsyncGenerator[mariadb.Database]:
    """Two anchors, one actual row whose entire declared payload is NULL."""
    server = await load_fixture(provide_mariadb_server())
    async with await mariadb.Database.initialize(server.config()) as database:
        await database.migrate(
            {"001": mariadb.scaffold([NativeAnchor, NativeNullableRow])}
        )
        async with database.transaction() as transaction:
            await transaction.execute(
                mariadb.insert_many(
                    NativeAnchor, [NativeAnchor(id=1), NativeAnchor(id=2)]
                )
            )
            await transaction.execute(mariadb.insert(NativeNullableRow(value=None)))
        yield database


@test([Param("table", name="table"), Param("alias", name="alias")], mark="slow")
async def native_matched_all_null_table_row_is_not_absent(source_kind: str) -> None:
    """A predicate on the anchor can match an actual all-NULL right row."""
    database = await load_fixture(native_nullable_rows())
    query = (
        mariadb.select(NativeAnchor)
        .left_join(
            mariadb.alias(NativeNullableRow, PeerRole, name="peer")
            if source_kind == "alias"
            else NativeNullableRow,
            on=NativeAnchor.id.eq(1),
        )
        .all()
        .order_by(NativeAnchor.id.asc())
    )

    async with database.transaction() as transaction:
        rows = await transaction.fetch_all(query)

    assert_eq(
        [(anchor.id, right is not None) for anchor, right in rows],
        [(1, True), (2, False)],
    )


@test(mark="medium")
async def nullable_anchor_keeps_joined_row_boundaries() -> None:
    """A presence field on the anchor must not shift the joined model's values."""
    database = await load_fixture(nullable_rows())
    peer = sqlite.alias(NullableRow, PeerRole, name="peer")
    query = (
        sqlite.select(NullableRow)
        .left_join(peer, on=NullableRow.value.is_null())
        .join(Anchor, on=Anchor.id.eq(1))
        .all()
    )

    async with database.transaction() as transaction:
        rows = await transaction.fetch_all(query)

    assert_eq(
        [(left.value, peer is not None, anchor.id) for left, peer, anchor in rows],
        [(None, True, 1)],
    )


@test(mark="slow")
async def native_nullable_anchor_keeps_joined_row_boundaries() -> None:
    """MariaDB must preserve offsets around two all-NULL model payloads."""
    database = await load_fixture(native_nullable_rows())
    peer = mariadb.alias(NativeNullableRow, PeerRole, name="peer")
    query = (
        mariadb.select(NativeNullableRow)
        .left_join(peer, on=NativeNullableRow.value.is_null())
        .join(NativeAnchor, on=NativeAnchor.id.eq(1))
        .all()
    )

    async with database.transaction() as transaction:
        rows = await transaction.fetch_all(query)

    assert_eq(
        [(left.value, peer is not None, anchor.id) for left, peer, anchor in rows],
        [(None, True, 1)],
    )

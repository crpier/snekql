"""Native integer constants through real transactions and recursive SQL anchors."""

from collections.abc import AsyncGenerator
from typing import assert_type

from snektest import Param, assert_eq, fixture, load_fixture, test

from snekql import mariadb, sqlite
from tests.helpers import provide_mariadb_server
from tests.query.test_literals import Depth, NativeSource, SeedRole, Source


@fixture
async def provide_literal_source() -> AsyncGenerator[sqlite.Database]:
    """Provide an explicit FROM row without borrowing its column's value type."""
    async with await sqlite.Database.initialize(database=":memory:") as database:
        await database.migrate({"001_source": sqlite.scaffold([Source])})
        async with database.transaction() as transaction:
            await transaction.execute(sqlite.insert(Source(id=1)))
        yield database


@fixture
async def provide_native_literal_source() -> AsyncGenerator[mariadb.Database]:
    """Run literal typing probes against the native SQL engine."""
    server = await load_fixture(provide_mariadb_server())
    async with await mariadb.Database.initialize(server.config()) as database:
        await database.migrate({"001_source": mariadb.scaffold([NativeSource])})
        async with database.transaction() as transaction:
            await transaction.execute(mariadb.insert(NativeSource(id=1)))
        yield database


@test(
    [Param(value, name=str(value)) for value in (0, -(2**63), 2**63 - 1)], mark="medium"
)
async def sqlite_literal_materializes_as_integer(value: int) -> None:
    """The full accepted native range remains int through result validation."""
    database = await load_fixture(provide_literal_source())
    query = sqlite.select(Source).all().project(Depth, depth=sqlite.literal(value))

    async with database.transaction() as transaction:
        row = await transaction.fetch_one(query)

    assert_type(row, Depth)
    assert_eq(row.depth, value)


@test(
    [Param(value, name=str(value)) for value in (0, -(2**63), 2**63 - 1)], mark="slow"
)
async def mariadb_literal_materializes_as_integer(value: int) -> None:
    """The width-preserving SQL lowering must return int, not Decimal."""
    database = await load_fixture(provide_native_literal_source())
    query = (
        mariadb.select(NativeSource).all().project(Depth, depth=mariadb.literal(value))
    )

    async with database.transaction() as transaction:
        row = await transaction.fetch_one(query)

    assert_type(row, Depth)
    assert_eq(row.depth, value)


@test(
    [
        Param((0, 2**31), name="above_int32"),
        Param((0, -(2**31) - 1), name="below_int32"),
        Param((2**63 - 2, 1), name="int64_max"),
        Param((-(2**63), 1), name="int64_min"),
    ],
    mark="slow",
)
async def mariadb_literal_establishes_recursive_anchor_width(
    case: tuple[int, int],
) -> None:
    """Compile the real literal into raw recursive SQL until the builder exists."""
    database = await load_fixture(provide_native_literal_source())
    start, increment = case
    anchor = (
        mariadb.select(NativeSource)
        .all()
        .project(Depth, depth=mariadb.literal(start))
        .compile()
    )
    sql = f"WITH RECURSIVE walk(depth) AS ({anchor.sql} UNION ALL SELECT depth + %s FROM walk WHERE depth = %s) SELECT depth FROM walk ORDER BY depth"
    query = mariadb.raw(sql, params=(*anchor.params, increment, start), validate=Depth)

    async with database.transaction() as transaction:
        rows = await transaction.fetch_all(query)

    assert_eq([row.depth for row in rows], sorted((start, start + increment)))


@test(mark="medium")
async def owner_free_literal_is_not_null_extended_by_a_join() -> None:
    """A missing joined row cannot turn a constant output into SQL NULL."""
    database = await load_fixture(provide_literal_source())

    class PeerRole:
        pass

    peer = sqlite.alias(Source, PeerRole, name="peer")
    token = sqlite.literal(0).label("depth")
    seed = (
        sqlite.select(Source)
        .left_join(peer, on=peer.column(Source.id).eq(2))
        .all()
        .project(Depth, depth=token)
        .cte(SeedRole, name="seed")
    )

    async with database.transaction() as transaction:
        rows = await transaction.fetch_all(sqlite.select(seed.column(token)).all())

    assert_type(rows, list[int])
    assert_eq(rows, [0])


@test(mark="medium")
async def literal_cte_composes_with_an_incremented_output() -> None:
    """UNION compatibility sees the same native integer decoder on both sides."""
    database = await load_fixture(provide_literal_source())
    token = sqlite.literal(0).label("depth")
    anchor = sqlite.select(Source).all().project(Depth, depth=token)
    seed = anchor.cte(SeedRole, name="seed")
    step = (
        sqlite.select(seed)
        .where(seed.column(token).lt(3))
        .project(Depth, depth=seed.column(token).add(1))
    )

    async with database.transaction() as transaction:
        rows = await transaction.fetch_all(anchor.union_all(step))

    assert_eq(rows, [Depth(depth=0), Depth(depth=1)])

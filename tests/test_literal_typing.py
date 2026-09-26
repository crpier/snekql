"""Native literal labels retain precise integer outputs across query boundaries."""

from typing import TYPE_CHECKING, assert_type

from snekql import mariadb, sqlite
from tests.query.test_literals import Depth, NativeSource, SeedRole, Source

if TYPE_CHECKING:
    local_token = sqlite.literal(0).label("depth")
    local = (
        sqlite.select(Source)
        .project(Depth, depth=local_token)
        .cte(SeedRole, name="local_depth")
    )
    native_token = mariadb.literal(0).label("depth")
    native = (
        mariadb.select(NativeSource)
        .project(Depth, depth=native_token)
        .cte(SeedRole, name="native_depth")
    )

    async def consume_local(transaction: sqlite.Transaction) -> None:
        assert_type(
            await transaction.fetch_all(sqlite.select(local.column(local_token))),
            list[int],
        )

    async def consume_native(transaction: mariadb.Transaction) -> None:
        assert_type(
            await transaction.fetch_all(mariadb.select(native.column(native_token))),
            list[int],
        )

    sqlite.literal(None)  # ty: ignore[invalid-argument-type]
    sqlite.literal("0")  # ty: ignore[invalid-argument-type]
    mariadb.literal(1.5)  # ty: ignore[invalid-argument-type]
    local.column(local_token).eq("wrong")  # ty: ignore[invalid-argument-type]

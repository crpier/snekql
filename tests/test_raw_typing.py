"""Exact backend-owned raw types and consumption-only Transaction overloads."""

from typing import TYPE_CHECKING, Literal, assert_type

from snekql import mariadb, sqlite

if TYPE_CHECKING:

    async def sqlite_results(
        transaction: sqlite.Transaction,
        mode: Literal["mapping", "tuple"],
        typed: sqlite.RawStatement[int],
    ) -> None:
        mapping = sqlite.raw("UPDATE values SET value=1")
        positional = sqlite.raw("SELECT 1", row_mode="tuple")
        dynamic = sqlite.raw("SELECT 1", row_mode=mode)
        assert_type(mapping, sqlite.RawStatement[dict[str, object]])
        assert_type(
            sqlite.raw("", validate=None), sqlite.RawStatement[dict[str, object]]
        )
        assert_type(positional, sqlite.RawStatement[tuple[object, ...]])
        assert_type(
            dynamic, sqlite.RawStatement[dict[str, object] | tuple[object, ...]]
        )
        assert_type(await transaction.fetch_all(mapping), list[dict[str, object]])
        assert_type(await transaction.fetch_one(mapping), dict[str, object])
        assert_type(
            await transaction.fetch_one_or_none(mapping), dict[str, object] | None
        )
        assert_type(
            transaction.fetch_chunks(mapping, size=2),
            sqlite.ChunkStream[dict[str, object]],
        )
        assert_type(await transaction.execute(mapping), int)
        assert_type(await transaction.fetch_all(positional), list[tuple[object, ...]])
        assert_type(await transaction.fetch_one(positional), tuple[object, ...])
        assert_type(
            await transaction.fetch_one_or_none(positional), tuple[object, ...] | None
        )
        assert_type(
            transaction.fetch_chunks(positional, size=2),
            sqlite.ChunkStream[tuple[object, ...]],
        )
        assert_type(await transaction.execute(typed), int)
        assert_type(
            await transaction.fetch_all(dynamic),
            list[dict[str, object] | tuple[object, ...]],
        )
        assert_type(
            await transaction.fetch_one(dynamic), dict[str, object] | tuple[object, ...]
        )
        assert_type(
            await transaction.fetch_one_or_none(dynamic),
            dict[str, object] | tuple[object, ...] | None,
        )
        assert_type(
            transaction.fetch_chunks(dynamic, size=2),
            sqlite.ChunkStream[dict[str, object] | tuple[object, ...]],
        )
        assert_type(await transaction.execute(dynamic), int)

    async def mariadb_results(
        transaction: mariadb.Transaction,
        mode: Literal["mapping", "tuple"],
        typed: mariadb.RawStatement[int],
    ) -> None:
        mapping = mariadb.raw("UPDATE values SET value=1")
        positional = mariadb.raw("SELECT 1", row_mode="tuple")
        dynamic = mariadb.raw("SELECT 1", row_mode=mode)
        assert_type(mapping, mariadb.RawStatement[dict[str, object]])
        assert_type(
            mariadb.raw("", validate=None), mariadb.RawStatement[dict[str, object]]
        )
        assert_type(positional, mariadb.RawStatement[tuple[object, ...]])
        assert_type(
            dynamic, mariadb.RawStatement[dict[str, object] | tuple[object, ...]]
        )
        assert_type(await transaction.fetch_all(mapping), list[dict[str, object]])
        assert_type(await transaction.fetch_one(mapping), dict[str, object])
        assert_type(
            await transaction.fetch_one_or_none(mapping), dict[str, object] | None
        )
        assert_type(
            transaction.fetch_chunks(mapping, size=2),
            mariadb.ChunkStream[dict[str, object]],
        )
        assert_type(await transaction.execute(mapping), int)
        assert_type(await transaction.fetch_all(positional), list[tuple[object, ...]])
        assert_type(await transaction.fetch_one(positional), tuple[object, ...])
        assert_type(
            await transaction.fetch_one_or_none(positional), tuple[object, ...] | None
        )
        assert_type(
            transaction.fetch_chunks(positional, size=2),
            mariadb.ChunkStream[tuple[object, ...]],
        )
        assert_type(await transaction.execute(typed), int)
        assert_type(
            await transaction.fetch_all(dynamic),
            list[dict[str, object] | tuple[object, ...]],
        )
        assert_type(
            await transaction.fetch_one(dynamic), dict[str, object] | tuple[object, ...]
        )
        assert_type(
            await transaction.fetch_one_or_none(dynamic),
            dict[str, object] | tuple[object, ...] | None,
        )
        assert_type(
            transaction.fetch_chunks(dynamic, size=2),
            mariadb.ChunkStream[dict[str, object] | tuple[object, ...]],
        )
        assert_type(await transaction.execute(dynamic), int)

    async def reject_sqlite_misuse(
        transaction: sqlite.Transaction, *, flag: bool, mode: str
    ) -> None:
        statement = sqlite.raw("SELECT 1")
        foreign = mariadb.raw("SELECT 1")
        sqlite.raw("SELECT 1", row_mode=mode)  # ty: ignore[no-matching-overload]
        await transaction.execute(foreign)  # ty: ignore[no-matching-overload]
        await transaction.execute(statement, validate=False)  # ty: ignore[no-matching-overload]
        await transaction.execute(statement, validate=flag)  # ty: ignore[no-matching-overload]
        await transaction.fetch_all(foreign)  # ty: ignore[no-matching-overload]
        await transaction.fetch_all(statement, validate=False)  # ty: ignore[no-matching-overload]
        await transaction.fetch_all(statement, validate=flag)  # ty: ignore[no-matching-overload]
        await transaction.fetch_one(foreign)  # ty: ignore[no-matching-overload]
        await transaction.fetch_one(statement, validate=False)  # ty: ignore[no-matching-overload]
        await transaction.fetch_one(statement, validate=flag)  # ty: ignore[no-matching-overload]
        await transaction.fetch_one_or_none(foreign)  # ty: ignore[no-matching-overload]
        await transaction.fetch_one_or_none(statement, validate=False)  # ty: ignore[no-matching-overload]
        await transaction.fetch_one_or_none(statement, validate=flag)  # ty: ignore[no-matching-overload]
        transaction.fetch_chunks(foreign, size=2)  # ty: ignore[no-matching-overload]
        transaction.fetch_chunks(statement, validate=False, size=2)  # ty: ignore[no-matching-overload]
        transaction.fetch_chunks(statement, validate=flag, size=2)  # ty: ignore[no-matching-overload]

    async def reject_mariadb_misuse(
        transaction: mariadb.Transaction, *, flag: bool, mode: str
    ) -> None:
        statement = mariadb.raw("SELECT 1")
        foreign = sqlite.raw("SELECT 1")
        mariadb.raw("SELECT 1", row_mode=mode)  # ty: ignore[no-matching-overload]
        await transaction.execute(foreign)  # ty: ignore[no-matching-overload]
        await transaction.execute(statement, validate=False)  # ty: ignore[no-matching-overload]
        await transaction.execute(statement, validate=flag)  # ty: ignore[no-matching-overload]
        await transaction.fetch_all(foreign)  # ty: ignore[no-matching-overload]
        await transaction.fetch_all(statement, validate=False)  # ty: ignore[no-matching-overload]
        await transaction.fetch_all(statement, validate=flag)  # ty: ignore[no-matching-overload]
        await transaction.fetch_one(foreign)  # ty: ignore[no-matching-overload]
        await transaction.fetch_one(statement, validate=False)  # ty: ignore[no-matching-overload]
        await transaction.fetch_one(statement, validate=flag)  # ty: ignore[no-matching-overload]
        await transaction.fetch_one_or_none(foreign)  # ty: ignore[no-matching-overload]
        await transaction.fetch_one_or_none(statement, validate=False)  # ty: ignore[no-matching-overload]
        await transaction.fetch_one_or_none(statement, validate=flag)  # ty: ignore[no-matching-overload]
        transaction.fetch_chunks(foreign, size=2)  # ty: ignore[no-matching-overload]
        transaction.fetch_chunks(statement, validate=False, size=2)  # ty: ignore[no-matching-overload]
        transaction.fetch_chunks(statement, validate=flag, size=2)  # ty: ignore[no-matching-overload]

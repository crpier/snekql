"""Consumer typing for query-only definitions and token-derived outputs."""

from typing import TYPE_CHECKING, assert_type

from pydantic import BaseModel

from snekql import mariadb, sqlite

if TYPE_CHECKING:

    class Local[S = sqlite.Pending](sqlite.Model[S, "Local[sqlite.Fetched]"]):
        id: sqlite.Col[int] = sqlite.Integer(primary_key=True)

    class Native[S = mariadb.Pending](mariadb.Model[S, "Native[mariadb.Fetched]"]):
        id: mariadb.Col[int] = mariadb.Integer(primary_key=True)

    class Result(BaseModel):
        id: int

    class LocalRole:
        pass

    class NativeRole:
        pass

    local_id = Local.id.label("id")
    native_id = Native.id.label("id")
    local = (
        sqlite.select(Local)
        .all()
        .project(Result, id=local_id)
        .cte(LocalRole, name="local_rows")
    )
    native = (
        mariadb.select(Native)
        .all()
        .project(Result, id=native_id)
        .cte(NativeRole, name="native_rows")
    )
    local_query: sqlite.Select[Result] = sqlite.select(local).all()
    native_query: mariadb.Select[Result] = mariadb.select(native).all()

    async def consume_local(transaction: sqlite.Transaction) -> None:
        """Named rows, optional fetches and scalar tokens retain their types."""
        assert_type(await transaction.fetch_all(local_query), list[Result])
        assert_type(
            await transaction.fetch_one_or_none(sqlite.select(local).all()),
            Result | None,
        )
        assert_type(
            await transaction.fetch_all(sqlite.select(local.column(local_id)).all()),
            list[int],
        )
        async with transaction.fetch_chunks(local_query, size=2) as chunks:
            assert_type(chunks, sqlite.ChunkStream[Result])

    async def consume_native(transaction: mariadb.Transaction) -> None:
        """The same contract holds without erasing the native backend coordinate."""
        assert_type(await transaction.fetch_all(native_query), list[Result])
        assert_type(
            await transaction.fetch_one_or_none(mariadb.select(native).all()),
            Result | None,
        )
        assert_type(
            await transaction.fetch_all(mariadb.select(native.column(native_id)).all()),
            list[int],
        )
        async with transaction.fetch_chunks(native_query, size=2) as chunks:
            assert_type(chunks, mariadb.ChunkStream[Result])

    sqlite.select(native)  # ty: ignore[no-matching-overload]
    mariadb.select(local)  # ty: ignore[no-matching-overload]
    sqlite.select(native.column(native_id))  # ty: ignore[no-matching-overload]
    mariadb.select(local.column(local_id))  # ty: ignore[no-matching-overload]
    local.column(local_id).eq("wrong")  # ty: ignore[invalid-argument-type]
    native.column(native_id).eq("wrong")  # ty: ignore[invalid-argument-type]
    sqlite.select(local).where(Local.id.gt(0))  # ty: ignore[invalid-argument-type]
    local.column("id")  # ty: ignore[invalid-argument-type]
    local.column(local_id).to(1)  # ty: ignore[unresolved-attribute]
    sqlite.select(Local).project(Result, id=local_id).cte(LocalRole, name="incomplete")  # ty: ignore[invalid-argument-type]
    sqlite.update(local)  # ty: ignore[invalid-argument-type]
    mariadb.delete(native)  # ty: ignore[invalid-argument-type]
    sqlite.scaffold([local])  # ty: ignore[invalid-argument-type]

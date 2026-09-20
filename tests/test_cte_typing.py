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
    local.column("id")  # ty: ignore[no-matching-overload]
    local.column(local_id).to(1)  # ty: ignore[unresolved-attribute]
    sqlite.select(Local).project(Result, id=local_id).cte(LocalRole, name="incomplete")  # ty: ignore[invalid-argument-type]
    sqlite.update(local)  # ty: ignore[invalid-argument-type]
    mariadb.delete(native)  # ty: ignore[invalid-argument-type]
    sqlite.scaffold([local])  # ty: ignore[invalid-argument-type]

    class PeerRole:
        pass

    class ExtraRole:
        pass

    class OptionalResult(BaseModel):
        id: int | None

    async def local_join_ownership(
        transaction: sqlite.Transaction, *, choose_peer: bool
    ) -> None:
        """Conditional owners preserve NULL; proven INNER owners and COUNT do not widen."""
        peer = sqlite.alias(Local, PeerRole, name="peer")
        extra = sqlite.alias(Local, ExtraRole, name="extra")
        chosen = peer.column(Local.id) if choose_peer else Local.id
        token = chosen.label("id")
        joined = sqlite.select(Local).left_join(
            peer, on=Local.id.eq_col(peer.column(Local.id))
        )
        conditional = (
            joined.project(OptionalResult, id=token)
            .where(Local.id.gt(0))
            .cte(LocalRole, name="conditional")
        )
        assert_type(
            await transaction.fetch_all(sqlite.select(conditional.column(token)).all()),
            list[int | None],
        )
        conditional.column(token).eq("wrong")  # ty: ignore[invalid-argument-type]
        reference = sqlite.alias(conditional, ExtraRole, name="reference")
        assert_type(
            await transaction.fetch_all(sqlite.select(reference.column(token)).all()),
            list[int | None],
        )
        count = peer.column(Local.id).count().label("id")
        counted = joined.all().project(Result, id=count).cte(LocalRole, name="counted")
        assert_type(
            await transaction.fetch_all(sqlite.select(counted.column(count)).all()),
            list[int],
        )
        extra_id = extra.column(Local.id).label("id")
        mixed = (
            joined.join(extra, on=Local.id.eq_col(extra.column(Local.id)))
            .all()
            .project(Result, id=extra_id)
            .cte(LocalRole, name="mixed")
        )
        assert_type(
            await transaction.fetch_all(sqlite.select(mixed.column(extra_id)).all()),
            list[int],
        )

    async def native_join_ownership(
        transaction: mariadb.Transaction, *, choose_peer: bool
    ) -> None:
        """Native output domains follow the same proven-present owner coordinate."""
        peer = mariadb.alias(Native, PeerRole, name="peer")
        extra = mariadb.alias(Native, ExtraRole, name="extra")
        chosen = peer.column(Native.id).add(1) if choose_peer else Native.id.add(1)
        token = chosen.label("id")
        joined = mariadb.select(Native).left_join(
            peer, on=Native.id.eq_col(peer.column(Native.id))
        )
        conditional = (
            joined.project(OptionalResult, id=token)
            .where(Native.id.gt(0))
            .cte(NativeRole, name="conditional")
        )
        assert_type(
            await transaction.fetch_all(
                mariadb.select(conditional.column(token)).all()
            ),
            list[int | None],
        )
        conditional.column(token).eq("wrong")  # ty: ignore[invalid-argument-type]
        reference = mariadb.alias(conditional, ExtraRole, name="reference")
        assert_type(
            await transaction.fetch_all(mariadb.select(reference.column(token)).all()),
            list[int | None],
        )
        count = peer.column(Native.id).count().label("id")
        counted = joined.all().project(Result, id=count).cte(NativeRole, name="counted")
        assert_type(
            await transaction.fetch_all(mariadb.select(counted.column(count)).all()),
            list[int],
        )
        extra_id = extra.column(Native.id).label("id")
        mixed = (
            joined.join(extra, on=Native.id.eq_col(extra.column(Native.id)))
            .all()
            .project(Result, id=extra_id)
            .cte(NativeRole, name="mixed")
        )
        assert_type(
            await transaction.fetch_all(mariadb.select(mixed.column(extra_id)).all()),
            list[int],
        )

    local_reference = sqlite.alias(local, PeerRole, name="reference")
    native_reference = mariadb.alias(native, PeerRole, name="reference")
    sqlite.select(local).where(local_reference.column(local_id).gt(0))  # ty: ignore[invalid-argument-type]
    mariadb.select(native).where(native_reference.column(native_id).gt(0))  # ty: ignore[invalid-argument-type]
    mariadb.alias(local, PeerRole, name="wrong")  # ty: ignore[no-matching-overload]
    sqlite.alias(native, PeerRole, name="wrong")  # ty: ignore[no-matching-overload]

    async def verify_only_schema_declarations(
        local_database: sqlite.Database, native_database: mariadb.Database
    ) -> None:
        """Selectable role witnesses never grant schema registration capability."""
        await local_database.verify([Local])
        await native_database.verify([Native])
        await local_database.verify([local])  # ty: ignore[invalid-argument-type]
        await native_database.verify([native])  # ty: ignore[invalid-argument-type]
        await local_database.verify([local_reference])  # ty: ignore[invalid-argument-type]

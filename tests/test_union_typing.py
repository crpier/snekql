"""Consumer contracts for completed named set operations."""

from typing import TYPE_CHECKING, assert_type

from snekql import mariadb, sqlite
from tests.query.test_unions import (
    CombinedRole,
    Event,
    MariaEvent,
    NullableEvent,
    OptionalRow,
    OtherRow,
    Row,
)

if TYPE_CHECKING:
    token = Event.event_id.label("event_id")
    query = sqlite.select(Event).project(Row, event_id=token)
    combined = query.union_all(query)
    stored: sqlite.ClosedRead[Row] = sqlite.ready(combined)
    cte = combined.cte(CombinedRole, name="combined")
    nullable_token = NullableEvent.event_id.label("event_id")
    nullable = sqlite.select(NullableEvent).project(
        OptionalRow, event_id=nullable_token
    )
    required = sqlite.select(Event).project(OptionalRow, event_id=token)
    nullable_combined = nullable.union(required)
    native_token = MariaEvent.event_id.label("event_id")
    native = mariadb.select(MariaEvent).project(Row, event_id=native_token)
    native_combined = native.union_all(native)
    native_stored: mariadb.ClosedRead[Row] = mariadb.ready(native_combined)

    async def consume_local(transaction: sqlite.Transaction) -> None:
        """Rows, optional fetches, streams and output references keep their types."""
        assert_type(await transaction.fetch_all(stored), list[Row])
        assert_type(await transaction.fetch_one_or_none(combined), Row | None)
        assert_type(
            await transaction.fetch_all(sqlite.select(cte.column(token))),
            list[int],
        )
        nullable_cte = nullable_combined.cte(CombinedRole, name="optional_combined")
        assert_type(
            await transaction.fetch_all(
                sqlite.select(nullable_cte.column(nullable_token))
            ),
            list[int | None],
        )
        async with transaction.fetch_chunks(combined, size=2) as chunks:
            assert_type(chunks, sqlite.ChunkStream[Row])

    async def consume_native(transaction: mariadb.Transaction) -> None:
        """Native set queries do not erase their backend or final row contract."""
        assert_type(await transaction.fetch_all(native_stored), list[Row])
        assert_type(await transaction.fetch_one_or_none(native_combined), Row | None)

    query.union(native)  # ty: ignore[invalid-argument-type]
    native.union(query)  # ty: ignore[invalid-argument-type]
    combined.union(native)  # ty: ignore[invalid-argument-type]
    other_result = sqlite.select(Event).project(OtherRow, event_id=token)
    query.union(other_result)  # ty: ignore[invalid-argument-type]
    query.union(sqlite.select(Event).project(Row, event_id=token))
    sqlite.select(Event).project(Row, event_id=token).union(query)
    query.union(sqlite.select(Event.event_id))  # ty: ignore[invalid-argument-type]
    query.union(sqlite.select(Event.event_id, Event.event_id))  # ty: ignore[invalid-argument-type]
    combined.order_by(Event.event_id.asc())  # ty: ignore[invalid-argument-type]
    combined.column(token).eq("wrong")  # ty: ignore[invalid-argument-type]
    combined.column("event_id")  # ty: ignore[no-matching-overload]
    combined.where(Event.event_id.eq(1))  # ty: ignore[unresolved-attribute]
    combined.for_update()  # ty: ignore[unresolved-attribute]

if TYPE_CHECKING:

    class PeerRole:
        pass

    async def left_join_output_remains_nullable(
        transaction: sqlite.Transaction,
    ) -> None:
        """Combined outputs retain the left query's contextual null extension."""
        peer = sqlite.alias(Event, PeerRole, name="peer")
        peer_token = peer.column(Event.event_id).label("event_id")
        left = (
            sqlite.select(Event)
            .left_join(peer, on=Event.event_id.eq_col(peer.column(Event.event_id)))
            .project(OptionalRow, event_id=peer_token)
        )
        right = sqlite.select(Event).project(OptionalRow, event_id=token)
        combined_join = left.union_all(right).cte(CombinedRole, name="joined_union")
        assert_type(
            await transaction.fetch_all(
                sqlite.select(combined_join.column(peer_token))
            ),
            list[int | None],
        )

    def conditional_backend_is_not_widened(*, choose_native: bool) -> None:
        """A conditional operand cannot silently lose its family witness."""
        other = native if choose_native else query
        query.union_all(other)  # ty: ignore[invalid-argument-type]

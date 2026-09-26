"""Named set operations through public compilation and construction."""

from typing import ClassVar

from pydantic import BaseModel
from snektest import Param, assert_eq, assert_raises, test

from snekql import mariadb, sqlite


class Event[S = sqlite.Pending](sqlite.Model[S]):
    """A physical source shared by filtered operands."""

    __row_type__: ClassVar[sqlite.ReadType[Event[sqlite.Row]]]

    event_id: sqlite.Col[int] = sqlite.Integer(primary_key=True)


class Row(BaseModel):
    """The exact result contract shared by both operands."""

    event_id: int


@test(mark="fast")
def named_union_all_compiles_in_operand_parameter_order() -> None:
    """The combined SELECT retains both operand scopes without Python evaluation."""
    event_id = Event.event_id.label("event_id")
    left = (
        sqlite.select(Event).where(Event.event_id.gt(2)).project(Row, event_id=event_id)
    )
    right = (
        sqlite.select(Event).where(Event.event_id.lt(8)).project(Row, event_id=event_id)
    )

    compiled = left.union_all(right).compile()

    assert_eq(
        compiled.sql,
        'SELECT "__snekql_union"."event_id" AS "event_id" FROM (SELECT "event_id" AS "event_id" FROM "event" WHERE ("event_id" > ?) UNION ALL SELECT "event_id" AS "event_id" FROM "event" WHERE ("event_id" < ?)) AS "__snekql_union"',
    )
    assert_eq(compiled.params, (2, 8))


class NullableEvent[S = sqlite.Pending](sqlite.Model[S]):
    """A genuinely nullable SQL output, independent of the result model."""

    __row_type__: ClassVar[sqlite.ReadType[NullableEvent[sqlite.Row]]]

    event_id: sqlite.Col[int | None] = sqlite.Integer()


class OptionalRow(BaseModel):
    """A result annotation alone does not widen a source token."""

    event_id: int | None


@test(mark="fast")
def nullable_left_contract_accepts_nonnullable_right() -> None:
    """A compatible required source fits the left token's optional contract."""
    left = (
        sqlite.select(NullableEvent)
        .all()
        .project(OptionalRow, event_id=NullableEvent.event_id.label("event_id"))
    )
    right = (
        sqlite.select(Event)
        .all()
        .project(OptionalRow, event_id=Event.event_id.label("event_id"))
    )

    compiled = left.union_all(right).compile()

    assert_eq(compiled.params, ())


class MariaEvent[S = mariadb.Pending](mariadb.Model[S]):
    """A backend-distinct source with the same logical field."""

    __row_type__: ClassVar[mariadb.ReadType[MariaEvent[mariadb.Row]]]

    event_id: mariadb.Col[int] = mariadb.Integer(primary_key=True)


class OtherRow(Row):
    """A subclass is still a distinct result contract."""


@test(
    [
        Param("ordered", name="ordered"),
        Param("limited", name="limited"),
        Param("offset", name="offset"),
        Param("locking", name="locking"),
        Param("other_result", name="other_result"),
        Param("other_backend", name="other_backend"),
    ],
    mark="fast",
)
def unsupported_operand_is_rejected_before_compilation(kind: str) -> None:
    """Runtime guards protect dynamic callers as well as statically typed code."""
    token = Event.event_id.label("event_id")
    left = sqlite.select(Event).all().project(Row, event_id=token)
    candidates: dict[str, object] = {
        "ordered": left.order_by(Event.event_id.asc()),
        "limited": left.limit(1),
        "offset": left.offset(1),
        "locking": left.for_update(),
        "other_result": sqlite.select(Event).all().project(OtherRow, event_id=token),
        "other_backend": mariadb.select(MariaEvent)
        .all()
        .project(Row, event_id=MariaEvent.event_id.label("event_id")),
    }

    with assert_raises(sqlite.QueryConstructionError):
        left.union_all(candidates[kind])  # ty: ignore[invalid-argument-type]


@test(mark="fast")
def nullable_right_does_not_widen_a_required_left_token() -> None:
    """A nullable Pydantic annotation cannot hide unsafe token nullability."""
    left = (
        sqlite.select(Event)
        .all()
        .project(OptionalRow, event_id=Event.event_id.label("event_id"))
    )
    right = (
        sqlite.select(NullableEvent)
        .all()
        .project(OptionalRow, event_id=NullableEvent.event_id.label("event_id"))
    )

    with assert_raises(sqlite.QueryConstructionError) as caught:
        left.union_all(right)

    assert_eq(
        str(caught.exception),
        "UNION right output cannot widen the left output's nullability",
    )


class Pair(BaseModel):
    """Canonical output order follows the result model, not binding insertion."""

    first: int
    second: int


@test(mark="fast")
def operand_fields_are_aligned_by_name() -> None:
    """Different insertion orders cannot exchange named result values."""
    left = (
        sqlite.select(Event)
        .all()
        .project(
            Pair,
            second=Event.event_id.add(10).label("second"),
            first=Event.event_id.add(1).label("first"),
        )
    )
    right = (
        sqlite.select(Event)
        .all()
        .project(
            Pair,
            first=Event.event_id.add(2).label("first"),
            second=Event.event_id.add(20).label("second"),
        )
    )

    compiled = left.union_all(right).compile()

    assert_eq(compiled.params, (1, 10, 2, 20))


@test(mark="fast")
def combined_output_orders_the_final_page() -> None:
    """Ordering tokens read the combined relation, never either input scope."""
    token = Event.event_id.label("event_id")
    left = sqlite.select(Event).where(Event.event_id.gt(2)).project(Row, event_id=token)
    right = (
        sqlite.select(Event).where(Event.event_id.lt(8)).project(Row, event_id=token)
    )
    combined = left.union(right)

    compiled = (
        combined.order_by(combined.column(token).desc()).limit(3).offset(1).compile()
    )

    assert_eq(compiled.params, (2, 8, 3, 1))
    assert_eq(
        compiled.sql.endswith(
            'ORDER BY "__snekql_union"."event_id" DESC LIMIT ? OFFSET ?'
        ),
        True,
    )


class CombinedRole:
    """A CTE role exposing the completed compound result."""


@test(mark="fast")
def combined_result_becomes_a_filterable_cte() -> None:
    """The definition hides both operand scopes behind one output contract."""
    token = Event.event_id.label("event_id")
    operand = sqlite.select(Event).all().project(Row, event_id=token)

    combined = operand.union(operand).cte(CombinedRole, name="events")
    compiled = sqlite.select(combined).where(combined.column(token).gt(4)).compile()

    assert_eq(compiled.params, (4,))
    assert_eq(compiled.sql.startswith('WITH "events" AS ('), True)
    assert_eq(
        compiled.sql.endswith('FROM "events" WHERE ("events"."event_id" > ?)'), True
    )


@test(mark="fast")
def compound_ordering_rejects_aggregate_reinterpretation() -> None:
    """Final ordering must not turn a combined rowset into an aggregate SELECT."""
    token = Event.event_id.label("event_id")
    operand = sqlite.select(Event).all().project(Row, event_id=token)
    combined = operand.union_all(operand)

    with assert_raises(sqlite.QueryConstructionError):
        combined.order_by(combined.column(token).count().asc())

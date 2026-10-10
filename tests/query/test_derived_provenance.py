"""Derived references preserve independent source capability and codec facts."""

from datetime import UTC, datetime
from typing import ClassVar

from pydantic import BaseModel
from snektest import Param, assert_eq, assert_raises, test

from snekql import mariadb, sqlite
from tests.query.test_ctes import ActiveRole, FilteredRole, Identifier, Person
from tests.query.test_union_contracts import JsonNumber, TextNumber
from tests.query.test_unions import MariaEvent, OptionalRow
from tests.runtime.test_named_codecs import FirstValue, MariaDocument


@test(mark="fast")
def nested_extrema_union_rejects_json_decode_mismatch() -> None:
    """Scalar and alias references do not erase the source JSON marker."""
    left_token = JsonNumber.event_id.min().label("event_id")
    right_token = TextNumber.event_id.max().label("event_id")
    left = (
        sqlite.select(JsonNumber)
        .project(OptionalRow, event_id=left_token)
        .cte(ActiveRole, name="json_number")
    )
    right = (
        sqlite.select(TextNumber)
        .project(OptionalRow, event_id=right_token)
        .cte(ActiveRole, name="text_number")
    )
    peer = sqlite.alias(right, FilteredRole, name="peer")

    class ScalarRole:
        pass

    left_scalar = sqlite.alias(left, ScalarRole, name="left_scalar")
    right_scalar = sqlite.alias(right, ScalarRole, name="right_scalar")
    first = sqlite.select(left).project(
        OptionalRow,
        event_id=sqlite.scalar(sqlite.select(left_scalar.column(left_token))),
    )
    second = sqlite.select(peer).project(
        OptionalRow,
        event_id=sqlite.scalar(sqlite.select(right_scalar.column(right_token))),
    )

    with assert_raises(sqlite.QueryConstructionError):
        first.union_all(second)


@test(mark="fast")
def nested_scalar_count_retains_nullable_native_operations() -> None:
    """A scalar's NULL possibility survives a second definition and alias."""

    class OptionalIdentifier(BaseModel):
        id: int | None

    class ScalarRole:
        pass

    scalar_source = sqlite.alias(Person, ScalarRole, name="scalar_person")
    token = sqlite.scalar(
        sqlite.select(scalar_source.column(Person.id).count()).where(
            scalar_source.column(Person.id).gt(3)
        )
    ).label("id")
    counted = (
        sqlite.select(Person)
        .project(OptionalIdentifier, id=token)
        .cte(ActiveRole, name="counted")
    )
    rebound = counted.column(token).label("id")
    nested = (
        sqlite.select(counted)
        .project(OptionalIdentifier, id=rebound)
        .cte(FilteredRole, name="nested")
    )
    peer = sqlite.alias(nested, ActiveRole, name="peer")
    calculated = peer.column(rebound).add(2)
    assert_eq(sqlite.select(calculated).compile().params, (3, 2))

    with assert_raises(sqlite.QueryConstructionError):
        sqlite.select(peer).project(Identifier, id=calculated)


@test(mark="fast")
def nested_sum_keeps_numeric_capability_without_native_arithmetic() -> None:
    """A decoded integer SUM still does not prove native integer SQL storage."""
    total = MariaEvent.event_id.sum().label("event_id")
    totals = (
        mariadb.select(MariaEvent)
        .project(OptionalRow, event_id=total)
        .cte(ActiveRole, name="totals")
    )
    rebound = totals.column(total).label("event_id")
    nested = (
        mariadb.select(totals)
        .project(OptionalRow, event_id=rebound)
        .cte(FilteredRole, name="nested")
    )
    peer = mariadb.alias(nested, ActiveRole, name="peer")
    column = peer.column(rebound)
    mariadb.select(column.sum()).compile()

    with assert_raises(mariadb.QueryConstructionError):
        column.add(1)


@test(
    [
        Param("min", name="min"),
        Param("max", name="max"),
        Param("asc", name="asc"),
        Param("desc", name="desc"),
        Param("gt", name="gt"),
        Param("between", name="between"),
    ],
    mark="fast",
)
def nested_scalar_retains_zoned_ordering_restriction(operation: str) -> None:
    """A nullable scalar retains the leaf's non-order-preserving wire restriction."""

    class Event[S = sqlite.Pending](sqlite.Model[S]):
        __row_type__: ClassVar[sqlite.ReadType[Event[sqlite.Row]]]
        value: sqlite.Col[sqlite.ZonedDatetime] = sqlite.Text()

    class OptionalTime(BaseModel):
        value: sqlite.ZonedDatetime | None

    class ScalarRole:
        pass

    token = Event.value.label("value")
    first = (
        sqlite.select(Event)
        .project(OptionalTime, value=token)
        .cte(ActiveRole, name="times")
    )
    scalar_source = sqlite.alias(first, ScalarRole, name="scalar_times")
    rebound = sqlite.scalar(sqlite.select(scalar_source.column(token))).label("value")
    nested = (
        sqlite.select(first)
        .project(OptionalTime, value=rebound)
        .cte(FilteredRole, name="nested_times")
    )
    column = nested.column(rebound)
    instant = sqlite.ZonedDatetime(datetime(2026, 1, 1, tzinfo=UTC))
    sqlite.select(nested).compile()

    with assert_raises(sqlite.QueryConstructionError):
        if operation == "min":
            column.min()
        elif operation == "max":
            column.max()
        elif operation == "asc":
            column.asc()
        elif operation == "desc":
            column.desc()
        elif operation == "gt":
            column.gt(instant)
        else:
            column.between(instant, instant)


@test(mark="fast")
def nested_opaque_output_defers_unavailable_compatibility_proof() -> None:
    """An opaque leaf remains readable but cannot establish UNION compatibility."""
    token = MariaDocument.payload.json_extract_int("$[0]").label("value")
    first = (
        mariadb.select(MariaDocument)
        .project(FirstValue, value=token)
        .cte(ActiveRole, name="extracted")
    )
    rebound = first.column(token).label("value")
    nested = (
        mariadb.select(first)
        .project(FirstValue, value=rebound)
        .cte(FilteredRole, name="nested_extracted")
    )
    peer = mariadb.alias(nested, ActiveRole, name="peer")
    operand = mariadb.select(peer).project(FirstValue, value=peer.column(rebound))
    operand.compile()

    with assert_raises(mariadb.QueryConstructionError):
        operand.union_all(operand)


@test(
    [Param("length", name="length"), Param("collation", name="collation")], mark="fast"
)
def derived_extrema_union_retains_text_storage_policy(metadata: str) -> None:
    """MIN/MAX equivalence must not erase physical decoder metadata."""

    class FirstText[S = mariadb.Pending](mariadb.Model[S]):
        __row_type__: ClassVar[mariadb.ReadType[FirstText[mariadb.Row]]]
        value: mariadb.Col[str] = mariadb.Text(
            length=80, collation="utf8mb4_unicode_ci"
        )

    class SecondText[S = mariadb.Pending](mariadb.Model[S]):
        __row_type__: ClassVar[mariadb.ReadType[SecondText[mariadb.Row]]]
        value: mariadb.Col[str] = mariadb.Text(
            length=120 if metadata == "length" else 80,
            collation="utf8mb4_bin"
            if metadata == "collation"
            else "utf8mb4_unicode_ci",
        )

    class OptionalText(BaseModel):
        value: str | None

    first_token = FirstText.value.label("value")
    second_token = SecondText.value.label("value")
    first = (
        mariadb.select(FirstText)
        .project(OptionalText, value=first_token)
        .cte(ActiveRole, name="first_text")
    )
    second = (
        mariadb.select(SecondText)
        .project(OptionalText, value=second_token)
        .cte(FilteredRole, name="second_text")
    )
    left = mariadb.select(first).project(
        OptionalText, value=first.column(first_token).min()
    )
    right = mariadb.select(second).project(
        OptionalText, value=second.column(second_token).max()
    )

    with assert_raises(mariadb.QueryConstructionError):
        left.union_all(right)

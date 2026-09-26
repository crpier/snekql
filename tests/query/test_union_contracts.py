"""Decoder compatibility must be established before combining named rows."""

from typing import Annotated, Any, ClassVar
from uuid import UUID

from pydantic import AfterValidator, BaseModel, Json
from snektest import assert_eq, assert_raises, test

from snekql import mariadb, sqlite
from tests.query.test_unions import Event, OptionalRow, Row
from tests.runtime.test_named_codecs import FirstValue, MariaDocument


class TextUuid[S = sqlite.Pending](sqlite.Model[S]):
    """UUID values stored in textual wire form."""

    __row_type__: ClassVar[sqlite.ReadType[TextUuid[sqlite.Row]]]

    identifier: sqlite.Col[UUID] = sqlite.Text()


class BlobUuid[S = sqlite.Pending](sqlite.Model[S]):
    """Same logical UUID, incompatible binary wire form."""

    __row_type__: ClassVar[sqlite.ReadType[BlobUuid[sqlite.Row]]]

    identifier: sqlite.Col[UUID] = sqlite.Blob()


class UuidResult(BaseModel):
    identifier: UUID


@test(mark="fast")
def union_rejects_mixed_uuid_encodings() -> None:
    """A matching final UUID annotation does not establish a shared decoder."""
    left = sqlite.select(TextUuid).project(UuidResult, identifier=TextUuid.identifier)
    right = sqlite.select(BlobUuid).project(UuidResult, identifier=BlobUuid.identifier)

    with assert_raises(sqlite.QueryConstructionError):
        left.union_all(right)


def increment(value: int) -> int:
    """A source annotation's decode validator changes observed values."""
    return value + 1


def double(value: int) -> int:
    """A different decode validator is not interchangeable with increment."""
    return value * 2


class Adjusted[S = sqlite.Pending](sqlite.Model[S]):
    __row_type__: ClassVar[sqlite.ReadType[Adjusted[sqlite.Row]]]
    event_id: sqlite.Col[Annotated[int, AfterValidator(increment)]] = sqlite.Integer()


class Doubled[S = sqlite.Pending](sqlite.Model[S]):
    __row_type__: ClassVar[sqlite.ReadType[Doubled[sqlite.Row]]]
    event_id: sqlite.Col[Annotated[int, AfterValidator(double)]] = sqlite.Integer()


@test(mark="fast")
def union_rejects_different_source_validation_policies() -> None:
    """The library must not run the left validator against right-hand values."""
    left = sqlite.select(Adjusted).project(Row, event_id=Adjusted.event_id)
    right = sqlite.select(Doubled).project(Row, event_id=Doubled.event_id)

    with assert_raises(sqlite.QueryConstructionError):
        left.union_all(right)


class JsonNumber[S = sqlite.Pending](sqlite.Model[S]):
    __row_type__: ClassVar[sqlite.ReadType[JsonNumber[sqlite.Row]]]
    event_id: sqlite.Col[Json[int]] = sqlite.Text()


class TextNumber[S = sqlite.Pending](sqlite.Model[S]):
    __row_type__: ClassVar[sqlite.ReadType[TextNumber[sqlite.Row]]]
    event_id: sqlite.Col[int] = sqlite.Text()


@test(mark="fast")
def union_rejects_json_marker_decode_mismatch() -> None:
    """Logical int and TEXT storage alone do not establish the same codec."""
    left = sqlite.select(JsonNumber).project(Row, event_id=JsonNumber.event_id)
    right = sqlite.select(TextNumber).project(Row, event_id=TextNumber.event_id)

    with assert_raises(sqlite.QueryConstructionError):
        left.union(right)


@test(mark="fast")
def unknown_dialect_output_policy_is_rejected() -> None:
    """Identical opaque operands do not prove compatible SQL domains."""
    operand = mariadb.select(MariaDocument).project(
        FirstValue, value=MariaDocument.payload.json_extract_int("$[0]")
    )

    with assert_raises(mariadb.QueryConstructionError):
        operand.union_all(operand)


@test(mark="fast")
def right_token_cannot_address_left_contract() -> None:
    """Equal label text is not token identity."""
    left_token = Event.event_id.label("event_id")
    right_token = Event.event_id.label("event_id")
    left = sqlite.select(Event).project(Row, event_id=left_token)
    right = sqlite.select(Event).project(Row, event_id=right_token)
    combined = left.union_all(right)

    with assert_raises(sqlite.QueryConstructionError):
        combined.column(right_token)


@test(mark="fast")
def earlier_compound_token_cannot_order_a_new_combination() -> None:
    """Identical static roles still have distinct runtime query identities."""
    token = Event.event_id.label("event_id")
    operand = sqlite.select(Event).project(Row, event_id=token)
    first = operand.union_all(operand)
    second = first.union_all(operand)

    with assert_raises(sqlite.QueryConstructionError):
        second.order_by(first.column(token).asc())


@test(mark="fast")
def shared_cte_dependency_is_emitted_once_for_both_operands() -> None:
    """WITH bindings precede both branch-local bindings in textual order."""

    class SharedRole:
        pass

    token = Event.event_id.label("event_id")
    shared = (
        sqlite.select(Event)
        .where(Event.event_id.gt(1))
        .project(Row, event_id=token)
        .cte(SharedRole, name="shared")
    )
    left = (
        sqlite.select(shared)
        .where(shared.column(token).lt(4))
        .project(Row, event_id=shared.column(token))
    )
    right = (
        sqlite.select(shared)
        .where(shared.column(token).gt(2))
        .project(Row, event_id=shared.column(token))
    )

    compiled = left.union_all(right).compile()

    assert_eq(compiled.sql.count('"shared" AS ('), 1)
    assert_eq(compiled.params, (1, 4, 2))


type UnknownValue = Any


class UnknownEvent[S = sqlite.Pending](sqlite.Model[S]):
    __row_type__: ClassVar[sqlite.ReadType[UnknownEvent[sqlite.Row]]]
    event_id: sqlite.Col[UnknownValue] = sqlite.Integer()


@test(mark="fast")
def unknown_alias_domain_is_not_a_compatibility_proof() -> None:
    """An alias must not hide Any from the output-domain guard."""
    operand = sqlite.select(UnknownEvent).project(Row, event_id=UnknownEvent.event_id)

    with assert_raises(sqlite.QueryConstructionError):
        operand.union_all(operand)


@test(mark="fast")
def combined_column_cannot_become_an_independent_source() -> None:
    """A standalone reference must not silently read only the left operand."""
    token = Event.event_id.label("event_id")
    operand = sqlite.select(Event).project(Row, event_id=token)
    combined = operand.union_all(operand)

    with assert_raises(sqlite.QueryCompilationError):
        sqlite.select(combined.column(token)).compile()


@test(mark="fast")
def extrema_share_their_source_wire_codec() -> None:
    """Different SQL operations can still preserve the same output wire policy."""
    left = sqlite.select(Event).project(
        OptionalRow, event_id=Event.event_id.min().label("event_id")
    )
    right = sqlite.select(Event).project(
        OptionalRow, event_id=Event.event_id.max().label("event_id")
    )

    compiled = left.union_all(right).compile()

    assert_eq(compiled.params, ())

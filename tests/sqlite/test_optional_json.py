"""Optional field-level Json markers select decoded-payload JSON storage."""

from __future__ import annotations

from typing import Annotated, ClassVar

from annotated_types import MinLen
from pydantic import AfterValidator, BeforeValidator, Json, PlainSerializer
from snektest import assert_eq, assert_raises, test

from snekql import sqlite
from snekql.errors import ModelDeclarationError, ModelValidationError
from tests.helpers import initialized_database


class Document[S = sqlite.Pending](sqlite.Model[S]):
    """A JSON marker wrapped in a nullable field annotation."""

    __row_type__: ClassVar[sqlite.ReadType[Document[sqlite.Row]]]

    id: Document.Col[int] = sqlite.Integer(primary_key=True)
    payload: Document.Col[Json[list[int]] | None] = sqlite.Text()


@test(mark="medium")
async def optional_json_round_trips_decoded_payload() -> None:
    """Adding None to a Json annotation does not require encoded JSON input."""

    async with await initialized_database(
        database=":memory:", models=[Document]
    ) as database:
        async with database.transaction() as setup:
            await setup.execute(sqlite.insert(Document(id=1, payload=[1, 2])))

        async with database.transaction() as tx:
            payload = await tx.fetch_one(sqlite.select(Document.payload).all())

    assert_eq(payload, [1, 2])


class InnerOptional[S = sqlite.Pending](sqlite.Model[S]):
    """The optional union may also be inside the field's Json marker."""

    __row_type__: ClassVar[sqlite.ReadType[InnerOptional[sqlite.Row]]]

    id: InnerOptional.Col[int] = sqlite.Integer(primary_key=True)
    payload: InnerOptional.Col[Json[list[int] | None]] = sqlite.Text()


@test(mark="medium")
async def optional_json_construction_and_assignment_round_trip() -> None:
    """Both optional spellings support SQL NULL and decoded list assignments."""

    async with await initialized_database(
        database=":memory:", models=[Document, InnerOptional]
    ) as database:
        async with database.transaction() as setup:
            await setup.execute(sqlite.insert(Document(id=1, payload=None)))
            await setup.execute(sqlite.insert(InnerOptional(id=1, payload=None)))

        async with database.transaction() as tx:
            assert_eq(await tx.fetch_one(sqlite.select(Document.payload).all()), None)
            assert_eq(
                await tx.fetch_one(sqlite.select(InnerOptional.payload).all()), None
            )
            assert_eq(
                await tx.fetch_one(
                    sqlite.select(Document.id.count()).where(Document.payload.is_null())
                ),
                1,
            )
            assert_eq(
                await tx.fetch_one(
                    sqlite.select(InnerOptional.id.count()).where(
                        InnerOptional.payload.is_null()
                    )
                ),
                1,
            )

        async with database.transaction() as tx:
            await tx.execute(
                sqlite.update(Document).set(Document.payload.to([3, 4])).all()
            )
            await tx.execute(
                sqlite.update(InnerOptional).set(InnerOptional.payload.to([3, 4])).all()
            )

        async with database.transaction() as tx:
            assert_eq(await tx.fetch_one(sqlite.select(Document.payload).all()), [3, 4])
            assert_eq(
                await tx.fetch_one(sqlite.select(InnerOptional.payload).all()), [3, 4]
            )


@test(mark="fast")
def optional_json_retains_constraints_and_validator_order() -> None:
    """Removing a field marker preserves inner and outer Annotated metadata."""

    calls: list[str] = []

    def before(value: object) -> object:
        calls.append("before")
        return value

    def after(value: object) -> object:
        calls.append("after")
        return value

    class Constrained[S = sqlite.Pending](sqlite.Model[S]):
        """A constrained payload inside an optional JSON field wrapper."""

        __row_type__: ClassVar[sqlite.ReadType[Constrained[sqlite.Row]]]

        payload: Constrained.Col[
            Annotated[
                Json[Annotated[list[int], MinLen(1), BeforeValidator(before)]] | None,
                AfterValidator(after),
            ]
        ] = sqlite.Text()

    assert_eq(Constrained(payload=[1]).payload, [1])
    assert_eq(calls, ["before", "after"])
    with assert_raises(ModelValidationError):
        Constrained(payload=[])
    with assert_raises(ModelValidationError):
        Constrained.payload.to([])


@test(mark="medium")
async def optional_json_preserves_custom_serialization() -> None:
    """Field payload serializers keep their chosen JSON representation."""

    def ordered(value: list[int]) -> list[int]:
        return sorted(value)

    class Serialized[S = sqlite.Pending](sqlite.Model[S]):
        """A JSON list with a canonical order on the wire."""

        __row_type__: ClassVar[sqlite.ReadType[Serialized[sqlite.Row]]]

        payload: Serialized.Col[
            Json[Annotated[list[int], PlainSerializer(ordered)]] | None
        ] = sqlite.Text()

    async with await initialized_database(
        database=":memory:", models=[Serialized]
    ) as database:
        async with database.transaction() as setup:
            await setup.execute(sqlite.insert(Serialized(payload=[3, 1])))
        async with database.transaction() as tx:
            assert_eq(
                await tx.fetch_one(sqlite.select(Serialized.payload).all()), [1, 3]
            )


@test(mark="fast")
def nested_payload_json_markers_are_not_stripped() -> None:
    """Only the field wire marker changes; nested Json items still parse strings."""

    class Nested[S = sqlite.Pending](sqlite.Model[S]):
        """Nested JSON strings remain a payload-level Pydantic feature."""

        __row_type__: ClassVar[sqlite.ReadType[Nested[sqlite.Row]]]

        payload: Nested.Col[Json[list[Json[int]]] | None] = sqlite.Text()

    assert_eq(Nested(payload=["1"]).payload, [1])  # ty: ignore[invalid-argument-type]
    with assert_raises(ModelValidationError):
        Nested(payload=[1])


@test(mark="fast")
def mixed_field_marker_unions_are_rejected() -> None:
    """A field cannot select different wire codecs for different union arms."""

    with assert_raises(ModelDeclarationError):

        class Mixed[S = sqlite.Pending](sqlite.Model[S]):
            """An ambiguous JSON-or-plain field declaration."""

            __row_type__: ClassVar[sqlite.ReadType[Mixed[sqlite.Row]]]

            payload: Mixed.Col[Json[list[int]] | str] = sqlite.Text(nullable=False)

        Mixed(payload=[1])


@test(mark="fast")
def explicit_json_payload_unions_remain_supported() -> None:
    """One marker around the entire union unambiguously selects JSON storage."""

    class Explicit[S = sqlite.Pending](sqlite.Model[S]):
        """Every alternative belongs to one JSON payload domain."""

        __row_type__: ClassVar[sqlite.ReadType[Explicit[sqlite.Row]]]

        payload: Explicit.Col[Json[list[int] | str]] = sqlite.Text(nullable=False)

    assert_eq(Explicit(payload=[1]).payload, [1])
    assert_eq(Explicit(payload="text").payload, "text")


@test(mark="medium")
async def sql_null_and_json_null_remain_distinct_on_the_wire() -> None:
    """Both decode to None, but Python None writes SQL NULL, not JSON text null."""

    class WireDocument[S = sqlite.Pending](sqlite.Model[S]):
        """A text view seeds externally supplied JSON null without a JSON codec."""

        __row_type__: ClassVar[sqlite.ReadType[WireDocument[sqlite.Row]]]

        __tablename__ = "document"
        id: WireDocument.Col[int] = sqlite.Integer(primary_key=True)
        payload: WireDocument.Col[str | None] = sqlite.Text()

    async with await initialized_database(
        database=":memory:", models=[Document]
    ) as database:
        async with database.transaction() as setup:
            await setup.execute(sqlite.insert(Document(id=1, payload=None)))
            await setup.execute(sqlite.insert(WireDocument(id=2, payload="null")))

        async with database.transaction() as tx:
            values = await tx.fetch_all(
                sqlite.select(Document.payload).all().order_by(Document.id.asc())
            )
            sql_null_ids = await tx.fetch_all(
                sqlite.select(Document.id).where(Document.payload.is_null())
            )
            wire = await tx.fetch_all(
                sqlite.select(WireDocument.payload)
                .all()
                .order_by(WireDocument.id.asc())
            )

    assert_eq(values, [None, None])
    assert_eq(sql_null_ids, [1])
    assert_eq(wire, [None, "null"])


@test(mark="medium")
async def fetched_optional_json_keeps_payload_constraints() -> None:
    """Row validation honors retained metadata; unchecked decoding still works."""

    class Checked[S = sqlite.Pending](sqlite.Model[S]):
        """A constrained optional JSON payload."""

        __row_type__: ClassVar[sqlite.ReadType[Checked[sqlite.Row]]]

        payload: Checked.Col[Json[Annotated[list[int], MinLen(1)]] | None] = (
            sqlite.Text()
        )

    async with await initialized_database(
        database=":memory:", models=[Checked]
    ) as database:
        async with database.transaction() as setup:
            await setup.execute(
                sqlite.raw("INSERT INTO checked (payload) VALUES ('[]')")
            )

        async with database.transaction() as tx:
            with assert_raises(ModelValidationError):
                await tx.fetch_one(sqlite.select(Checked.payload).all())
            raw = await tx.fetch_one(
                sqlite.select(Checked.payload).all(), validate=False
            )

    assert_eq(raw, [])


@test(mark="fast")
def inner_optional_json_accepts_decoded_python_values() -> None:
    """An optional payload inside Json accepts non-null Python values directly."""

    assert_eq(InnerOptional(id=1, payload=[1, 2]).payload, [1, 2])

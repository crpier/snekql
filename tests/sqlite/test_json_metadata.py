"""JSON wire markers must not discard the logical field's Annotated metadata."""

from __future__ import annotations

from collections.abc import AsyncGenerator
from typing import Annotated

from annotated_types import MinLen
from pydantic import AfterValidator, BeforeValidator, Json, PlainSerializer
from snektest import assert_eq, assert_raises, fixture, load_fixture, test

from snekql import sqlite


class NonemptyBatch[S = sqlite.Pending](
    sqlite.Model[S, "NonemptyBatch[sqlite.Fetched]"]
):
    """The logical contract intentionally violated by a stored historical row."""

    __tablename__ = "metadata_batch"
    items: NonemptyBatch.Col[Annotated[Json[list[int]], MinLen(1)]] = sqlite.Text()


@fixture
async def stored_invalid_batch() -> AsyncGenerator[sqlite.Database]:
    """Create a row that predates enforcement of the field constraint."""

    async with await sqlite.Database.initialize(database=":memory:") as database:
        await database.migrate(
            {
                "create": "CREATE TABLE metadata_batch (items TEXT NOT NULL) STRICT",
                "legacy_row": "INSERT INTO metadata_batch VALUES ('[]')",
            }
        )
        yield database


@test(mark="fast")
def json_field_preserves_length_constraint() -> None:
    """Pending construction enforces constraints alongside the JSON marker."""

    class Batch[S = sqlite.Pending](sqlite.Model[S, "Batch[sqlite.Fetched]"]):
        """A nonempty JSON list."""

        items: Batch.Col[Annotated[Json[list[int]], MinLen(1)]] = sqlite.Text()

    with assert_raises(sqlite.ModelValidationError):
        Batch(items=[])


@test(mark="fast")
def json_field_preserves_validator_order() -> None:
    """Before validators run right-to-left and after validators left-to-right."""

    def append_one(values: list[int]) -> list[int]:
        return [*values, 1]

    def append_two(values: list[int]) -> list[int]:
        return [*values, 2]

    def append_three(values: list[int]) -> list[int]:
        return [*values, 3]

    def append_four(values: list[int]) -> list[int]:
        return [*values, 4]

    class Batch[S = sqlite.Pending](sqlite.Model[S, "Batch[sqlite.Fetched]"]):
        """JSON with ordered input/output validation."""

        items: Batch.Col[
            Annotated[
                Json[list[int]],
                BeforeValidator(append_two),
                BeforeValidator(append_one),
                AfterValidator(append_three),
                AfterValidator(append_four),
            ]
        ] = sqlite.Text()

    assert_eq(Batch(items=[]).items, [1, 2, 3, 4])


@test(mark="fast")
def json_field_preserves_custom_serializer() -> None:
    """A serializer remains responsible for the JSON wire representation."""

    def reverse_values(values: list[int]) -> list[int]:
        return list(reversed(values))

    class Batch[S = sqlite.Pending](sqlite.Model[S, "Batch[sqlite.Fetched]"]):
        """JSON with an explicit wire serializer."""

        items: Batch.Col[
            Annotated[
                Json[list[int]],
                PlainSerializer(
                    reverse_values, return_type=list[int], when_used="json"
                ),
            ]
        ] = sqlite.Text()

    assert_eq(Batch.items.encode([1, 2], backend="sqlite"), "[2,1]")


@test(mark="fast")
def json_field_keeps_nested_payload_markers() -> None:
    """Inner JSON strings still follow their own Pydantic payload annotations."""

    class Batch[S = sqlite.Pending](sqlite.Model[S, "Batch[sqlite.Fetched]"]):
        """An outer JSON array containing encoded JSON arrays."""

        items: Batch.Col[Json[list[Json[list[int]]]]] = sqlite.Text()

    assert_eq(Batch.items.decode('["[1,2]"]', backend="sqlite"), [[1, 2]])


@test(mark="medium")
async def fetched_json_enforces_field_constraints() -> None:
    """A legacy row violating metadata fails normal runtime materialization."""

    database = await load_fixture(stored_invalid_batch())
    async with database.transaction() as transaction:
        with assert_raises(sqlite.ModelValidationError):
            await transaction.fetch_one(sqlite.select(NonemptyBatch).all())


@test(mark="medium")
async def fetched_json_can_explicitly_skip_validation() -> None:
    """The existing validate=False escape hatch still permits legacy JSON values."""

    database = await load_fixture(stored_invalid_batch())
    async with database.transaction() as transaction:
        payload = await transaction.fetch_one(
            sqlite.select(NonemptyBatch.items).all(), validate=False
        )

    assert_eq(payload, [])

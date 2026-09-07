"""Validation metadata on JSON-backed model fields."""

from __future__ import annotations

from typing import Annotated

from annotated_types import MinLen
from pydantic import AfterValidator, Json, PlainSerializer
from snektest import assert_eq, assert_raises, test

from snekql.sqlite import Fetched, Model, ModelValidationError, Pending, Text


@test(mark="fast")
def json_field_preserves_length_constraint() -> None:
    """Selecting a JSON wire codec must not discard payload constraints."""

    class Batch[S = Pending](Model[S, "Batch[Fetched]"]):
        """A batch must contain at least one item."""

        items: Batch.Col[Annotated[Json[list[int]], MinLen(1)]] = Text()

    with assert_raises(ModelValidationError):
        Batch(items=[])


@test(mark="fast")
def json_fetch_preserves_length_constraint() -> None:
    """Database JSON decoding must enforce constraints on the payload too."""

    class Batch[S = Pending](Model[S, "Batch[Fetched]"]):
        """A batch must contain at least one item."""

        items: Batch.Col[Annotated[Json[list[int]], MinLen(1)]] = Text()

    with assert_raises(ModelValidationError):
        Batch.items.decode("[]", backend="sqlite")


@test(mark="fast")
def json_field_preserves_custom_validator() -> None:
    """An application validator still normalizes a JSON-backed logical value."""

    class Batch[S = Pending](Model[S, "Batch[Fetched]"]):
        """A batch whose item order is canonicalized on construction."""

        items: Batch.Col[Annotated[Json[list[int]], AfterValidator(sorted)]] = Text()

    assert_eq(Batch(items=[2, 1]).items, [1, 2])


@test(mark="fast")
def json_field_preserves_custom_serializer() -> None:
    """The JSON marker must not replace an application's payload serializer."""

    class Batch[S = Pending](Model[S, "Batch[Fetched]"]):
        """A batch whose wire order is canonicalized without changing its value."""

        items: Batch.Col[
            Annotated[Json[list[int]], PlainSerializer(sorted, return_type=list[int])]
        ] = Text()

    pending = Batch(items=[2, 1])
    assert_eq(Batch.items.encode(pending.items, backend="sqlite"), "[1,2]")

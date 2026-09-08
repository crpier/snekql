"""MariaDB JSON storage preserves metadata alongside Pydantic's wire marker."""

from __future__ import annotations

from typing import Annotated

from annotated_types import MinLen
from pydantic import Json, PlainSerializer
from snektest import Param, assert_eq, assert_raises, test

from snekql import mariadb


@test(
    [Param(value="native", name="native"), Param(value="text", name="text")],
    mark="fast",
)
def json_marker_preserves_mariadb_constraints(storage: str) -> None:
    """Both native and marker-selected JSON enforce the same field constraints."""

    class Batch[S = mariadb.Pending](mariadb.Model[S, "Batch[mariadb.Fetched]"]):
        """A nonempty JSON list."""

        items: Batch.Col[Annotated[Json[list[int]], MinLen(1)]] = (
            mariadb.Json() if storage == "native" else mariadb.Text()
        )

    with assert_raises(mariadb.ModelValidationError):
        Batch(items=[])


@test(
    [Param(value="native", name="native"), Param(value="text", name="text")],
    mark="fast",
)
def json_marker_preserves_mariadb_serializer(storage: str) -> None:
    """Metadata controls JSON output for both MariaDB storage choices."""

    def reverse_values(values: list[int]) -> list[int]:
        return list(reversed(values))

    class Batch[S = mariadb.Pending](mariadb.Model[S, "Batch[mariadb.Fetched]"]):
        """JSON with an explicit wire serializer."""

        items: Batch.Col[
            Annotated[
                Json[list[int]],
                PlainSerializer(
                    reverse_values, return_type=list[int], when_used="json"
                ),
            ]
        ] = mariadb.Json() if storage == "native" else mariadb.Text()

    assert_eq(Batch.items.encode([1, 2], backend="mariadb"), "[2,1]")

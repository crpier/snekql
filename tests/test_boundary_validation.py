"""Public boundary validation for constrained numeric arguments."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import cast

from snektest import assert_raises, test

from snekql import (
    Database,
    DatabaseRuntimeError,
    Model,
    Pending,
    QueryConstructionError,
    Text,
    select,
)
from tests.logging_helpers import NULL_LOGGER


class BoundaryUser[S = Pending](Model[S, "BoundaryUser[object]"]):
    """Table model used by select boundary validation tests."""

    email: BoundaryUser.Col[str] = Text(nullable=False)


@test(mark="fast")
def select_limit_and_offset_reject_invalid_values_at_boundary() -> None:
    """Constrained select integers are validated by public chain methods."""

    limit_fn = cast("Callable[[object], object]", select(BoundaryUser).all().limit)
    offset_fn = cast("Callable[[object], object]", select(BoundaryUser).all().offset)

    with assert_raises(QueryConstructionError):
        _ = limit_fn(-1)

    with assert_raises(QueryConstructionError):
        _ = limit_fn(True)

    with assert_raises(QueryConstructionError):
        _ = offset_fn("1")


@test(mark="medium")
async def database_numeric_configuration_rejects_invalid_values_at_boundary() -> None:
    """Runtime numeric configuration rejects invalid values as domain errors."""

    initialize_fn = cast("Callable[..., Awaitable[object]]", Database.initialize)

    with assert_raises(DatabaseRuntimeError):
        _ = await initialize_fn(NULL_LOGGER, database=":memory:", pool_size=True)

    database = await Database.initialize(NULL_LOGGER, database=":memory:")
    try:
        transaction_fn = cast("Callable[..., object]", database.transaction)
        with assert_raises(DatabaseRuntimeError):
            _ = transaction_fn(timeout="1")
    finally:
        await database.close()

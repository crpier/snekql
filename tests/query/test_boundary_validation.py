"""Public boundary validation for constrained numeric arguments."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import cast

from pydantic import ValidationError
from snektest import assert_in, assert_isinstance, assert_raises, test

from snekql import (
    Database,
    DatabaseRuntimeError,
    Fetched,
    Model,
    Pending,
    QueryConstructionError,
    Text,
    select,
)
from tests.helpers import NULL_LOGGER


class BoundaryUser[S = Pending](Model[S, "BoundaryUser[Fetched]"]):
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


@test(mark="fast")
def boundary_validation_uses_pydantic_message_with_domain_error() -> None:
    """Boundary validation preserves Pydantic detail on domain exceptions."""

    limit_fn = cast("Callable[[object], object]", select(BoundaryUser).all().limit)

    with assert_raises(QueryConstructionError) as error:
        _ = limit_fn(True)

    assert_isinstance(error.exception.__cause__, ValidationError)
    assert_in("Input should be a valid integer", str(error.exception))


@test(mark="medium")
async def database_numeric_configuration_rejects_invalid_values_at_boundary() -> None:
    """Runtime numeric configuration rejects invalid values as domain errors."""

    initialize_fn = cast("Callable[..., Awaitable[object]]", Database.initialize)

    with assert_raises(DatabaseRuntimeError):
        _ = await initialize_fn(logger=NULL_LOGGER, database=":memory:", pool_size=True)

    database = await Database.initialize(logger=NULL_LOGGER, database=":memory:")
    try:
        transaction_fn = cast("Callable[..., object]", database.transaction)
        with assert_raises(DatabaseRuntimeError):
            _ = transaction_fn(timeout="1")
    finally:
        await database.close()

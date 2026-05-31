"""Boundary validation helpers for constrained public API values."""

from __future__ import annotations

from collections.abc import Callable
from functools import wraps
from typing import Annotated, ParamSpec, TypeVar

from annotated_types import Ge, Gt
from pydantic import ConfigDict, ValidationError, validate_call

from snekql.errors import SnekqlError

P = ParamSpec("P")
R = TypeVar("R")
ErrorT = TypeVar("ErrorT", bound=SnekqlError)

# Constrained numeric aliases used after public boundary validation.
type NonNegativeFloat = Annotated[float, Ge(0)]
type NonNegativeInt = Annotated[int, Ge(0)]
type PositiveInt = Annotated[int, Gt(0)]


def validate_boundary(
    error_type: type[ErrorT],
    message: str,
) -> Callable[[Callable[P, R]], Callable[P, R]]:
    """Validate public API calls and wrap validation errors as domain errors."""

    def decorate(function: Callable[P, R]) -> Callable[P, R]:
        validated = validate_call(
            config=ConfigDict(arbitrary_types_allowed=True, strict=True),
        )(function)

        @wraps(function)
        def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
            try:
                return validated(*args, **kwargs)
            except ValidationError as error:
                raise error_type(message) from error

        return wrapper

    return decorate

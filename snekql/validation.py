"""Boundary validation helpers for constrained public API values."""

lazy from annotationlib import Format
lazy from collections.abc import Callable
lazy from functools import cache, wraps
lazy from importlib.metadata import entry_points
lazy from inspect import Parameter, iscoroutinefunction, signature
lazy from typing import Annotated, cast

lazy from annotated_types import Ge, Gt
lazy from pydantic import ConfigDict, ValidationError, validate_call

lazy from snekql.errors import SnekqlError

# Constrained numeric aliases used after public boundary validation.
type NonNegativeFloat = Annotated[float, Ge(0)]
type NonNegativeInt = Annotated[int, Ge(0)]
type PositiveInt = Annotated[int, Gt(0)]


_METHOD_ARGUMENT_COUNT = 2


@cache
def _has_pydantic_plugins() -> bool:
    """Installed plugins may enforce additional policy even for plain integers.

    Be conservative even when an installed plugin is disabled. Plugin discovery
    is setup work, not a per-call scan, just as it is in Pydantic itself.
    """
    return bool(entry_points(group="pydantic"))


def _is_plain_nonnegative_int_method(function: Callable[..., object]) -> bool:
    """Recognize only a required, untyped self and one plain integer argument.

    Check the alias definition as well as the method's annotation: adding a
    constraint or transformation must automatically restore general validation.
    """
    if iscoroutinefunction(function):
        return False
    if NonNegativeInt.__value__ != Annotated[int, Ge(0)]:
        return False
    parameters = tuple(
        signature(function, annotation_format=Format.FORWARDREF).parameters.values()
    )
    return (
        len(parameters) == _METHOD_ARGUMENT_COUNT
        and parameters[0].name == "self"
        and parameters[0].annotation is Parameter.empty
        and parameters[1].annotation is NonNegativeInt
        and all(
            p.kind is Parameter.POSITIONAL_OR_KEYWORD and p.default is Parameter.empty
            for p in parameters
        )
        and not _has_pydantic_plugins()
    )


def validate_boundary[ErrorT: SnekqlError, **P, R](
    *,
    error_type: type[ErrorT],
    _specialize_nonnegative_int: bool = False,
) -> Callable[[Callable[P, R]], Callable[P, R]]:
    """Validate public API calls and wrap validation errors as domain errors.

    The private specialization opt-in is only for pagination's known integer
    methods; ordinary callers retain the general validator unchanged.
    """

    def decorate(function: Callable[P, R]) -> Callable[P, R]:
        validated = validate_call(
            config=ConfigDict(
                arbitrary_types_allowed=True, hide_input_in_errors=True, strict=True
            ),
        )(function)

        if _specialize_nonnegative_int and _is_plain_nonnegative_int_method(function):
            # The signature guard permits this positional call; narrowing args
            # to two objects otherwise loses the ParamSpec relationship.
            direct = cast("Callable[..., R]", function)

            @wraps(function)
            def integer_method(*args: P.args, **kwargs: P.kwargs) -> R:
                try:
                    # Exact built-ins need no normalization. Subtypes,
                    # keywords, malformed calls and failures use Pydantic.
                    if len(args) == _METHOD_ARGUMENT_COUNT and not kwargs:
                        value = args[1]
                        if type(value) is int and value >= 0:
                            return direct(args[0], value)
                    return validated(*args, **kwargs)
                except ValidationError as error:
                    raise error_type(str(error)) from error

            return integer_method

        @wraps(function)
        def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
            try:
                return validated(*args, **kwargs)
            except ValidationError as error:
                raise error_type(str(error)) from error

        return wrapper

    return decorate

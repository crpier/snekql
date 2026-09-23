"""Backend-owned searched CASE expressions."""

from typing import Any, Literal, overload

from snekql._aliases import _AliasOwner
from snekql._case import build_case
from snekql._literal import _IntegerLiteral, build_integer_literal
from snekql._value_expression import ExpressionMethods, ValueExpression
from snekql.expressions import Predicate
from snekql.sqlite.model import Model


@overload
def case[OwnerT: Model[Any, Any] | _AliasOwner[Literal["sqlite"], Any, Any]](
    condition: Predicate[OwnerT],
    *,
    then: int | ExpressionMethods[OwnerT, int],
    otherwise: int | ExpressionMethods[OwnerT, int],
) -> ValueExpression[OwnerT, int]: ...


@overload
def case[OwnerT: Model[Any, Any] | _AliasOwner[Literal["sqlite"], Any, Any]](
    condition: Predicate[OwnerT],
    *,
    then: int
    | ExpressionMethods[OwnerT, int]
    | ExpressionMethods[OwnerT, int | None]
    | None,
    otherwise: int
    | ExpressionMethods[OwnerT, int]
    | ExpressionMethods[OwnerT, int | None]
    | None,
) -> ValueExpression[OwnerT, int | None]: ...


@overload
def case[OwnerT: Model[Any, Any] | _AliasOwner[Literal["sqlite"], Any, Any]](
    condition: Predicate[OwnerT],
    *,
    then: float | ExpressionMethods[OwnerT, float],
    otherwise: float | ExpressionMethods[OwnerT, float],
) -> ValueExpression[OwnerT, float]: ...


@overload
def case[OwnerT: Model[Any, Any] | _AliasOwner[Literal["sqlite"], Any, Any]](
    condition: Predicate[OwnerT],
    *,
    then: float
    | ExpressionMethods[OwnerT, float]
    | ExpressionMethods[OwnerT, float | None]
    | None,
    otherwise: float
    | ExpressionMethods[OwnerT, float]
    | ExpressionMethods[OwnerT, float | None]
    | None,
) -> ValueExpression[OwnerT, float | None]: ...


@overload
def case[OwnerT: Model[Any, Any] | _AliasOwner[Literal["sqlite"], Any, Any]](
    condition: Predicate[OwnerT],
    *,
    then: str | ExpressionMethods[OwnerT, str],
    otherwise: str | ExpressionMethods[OwnerT, str],
) -> ValueExpression[OwnerT, str]: ...


@overload
def case[OwnerT: Model[Any, Any] | _AliasOwner[Literal["sqlite"], Any, Any]](
    condition: Predicate[OwnerT],
    *,
    then: str
    | ExpressionMethods[OwnerT, str]
    | ExpressionMethods[OwnerT, str | None]
    | None,
    otherwise: str
    | ExpressionMethods[OwnerT, str]
    | ExpressionMethods[OwnerT, str | None]
    | None,
) -> ValueExpression[OwnerT, str | None]: ...


def case(
    condition: Predicate[Any], *, then: object, otherwise: object
) -> ValueExpression[Any, Any]:
    """Choose a compatible branch in SQL; UNKNOWN conditions use `otherwise`.

    Example: `case(User.score.gte(100), then="gold", otherwise="standard")`.
    """
    return build_case(condition, then=then, otherwise=otherwise, backend="sqlite")


def literal(value: int, /) -> _IntegerLiteral[Literal["sqlite"]]:
    """Bind a native integer in a named projection, for example `literal(0)`."""
    return build_integer_literal(value, backend="sqlite")

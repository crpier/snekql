"""Backend-owned searched CASE expressions."""

from typing import Any, Literal, overload

from snekql._aliases import _AliasOwner
from snekql._case import build_case
from snekql._literal import _IntegerLiteral, build_integer_literal
from snekql._value_expression import ExpressionMethods, ValueExpression
from snekql.expressions import Predicate
from snekql.sqlite.model import Model


@overload
def case[OwnerT: Model[Any] | _AliasOwner[Literal["sqlite"], Any, Any]](
    condition: Predicate[OwnerT, Literal["sqlite"]],
    *,
    then: int | ExpressionMethods[OwnerT, int, Literal["sqlite"]],
    otherwise: int | ExpressionMethods[OwnerT, int, Literal["sqlite"]],
) -> ValueExpression[OwnerT, int, int, Literal["sqlite"]]: ...


@overload
def case[OwnerT: Model[Any] | _AliasOwner[Literal["sqlite"], Any, Any]](
    condition: Predicate[OwnerT, Literal["sqlite"]],
    *,
    then: int
    | ExpressionMethods[OwnerT, int, Literal["sqlite"]]
    | ExpressionMethods[OwnerT, int | None, Literal["sqlite"]]
    | None,
    otherwise: int
    | ExpressionMethods[OwnerT, int, Literal["sqlite"]]
    | ExpressionMethods[OwnerT, int | None, Literal["sqlite"]]
    | None,
) -> ValueExpression[OwnerT, int | None, int, Literal["sqlite"]]: ...


@overload
def case[OwnerT: Model[Any] | _AliasOwner[Literal["sqlite"], Any, Any]](
    condition: Predicate[OwnerT, Literal["sqlite"]],
    *,
    then: float | ExpressionMethods[OwnerT, float, Literal["sqlite"]],
    otherwise: float | ExpressionMethods[OwnerT, float, Literal["sqlite"]],
) -> ValueExpression[OwnerT, float, float, Literal["sqlite"]]: ...


@overload
def case[OwnerT: Model[Any] | _AliasOwner[Literal["sqlite"], Any, Any]](
    condition: Predicate[OwnerT, Literal["sqlite"]],
    *,
    then: float
    | ExpressionMethods[OwnerT, float, Literal["sqlite"]]
    | ExpressionMethods[OwnerT, float | None, Literal["sqlite"]]
    | None,
    otherwise: float
    | ExpressionMethods[OwnerT, float, Literal["sqlite"]]
    | ExpressionMethods[OwnerT, float | None, Literal["sqlite"]]
    | None,
) -> ValueExpression[OwnerT, float | None, float, Literal["sqlite"]]: ...


@overload
def case[OwnerT: Model[Any] | _AliasOwner[Literal["sqlite"], Any, Any]](
    condition: Predicate[OwnerT, Literal["sqlite"]],
    *,
    then: str | ExpressionMethods[OwnerT, str, Literal["sqlite"]],
    otherwise: str | ExpressionMethods[OwnerT, str, Literal["sqlite"]],
) -> ValueExpression[OwnerT, str, str, Literal["sqlite"]]: ...


@overload
def case[OwnerT: Model[Any] | _AliasOwner[Literal["sqlite"], Any, Any]](
    condition: Predicate[OwnerT, Literal["sqlite"]],
    *,
    then: str
    | ExpressionMethods[OwnerT, str, Literal["sqlite"]]
    | ExpressionMethods[OwnerT, str | None, Literal["sqlite"]]
    | None,
    otherwise: str
    | ExpressionMethods[OwnerT, str, Literal["sqlite"]]
    | ExpressionMethods[OwnerT, str | None, Literal["sqlite"]]
    | None,
) -> ValueExpression[OwnerT, str | None, str, Literal["sqlite"]]: ...


def case(
    condition: Predicate[Any, Literal["sqlite"]], *, then: object, otherwise: object
) -> ValueExpression[Any, Any, Any, Literal["sqlite"]]:
    """Choose a compatible branch in SQL; UNKNOWN conditions use `otherwise`.

    Example: `case(User.score.gte(100), then="gold", otherwise="standard")`.
    """
    return build_case(condition, then=then, otherwise=otherwise, backend="sqlite")


def literal(value: int, /) -> _IntegerLiteral[Literal["sqlite"]]:
    """Bind a native integer in a named projection, for example `literal(0)`."""
    return build_integer_literal(value, backend="sqlite")

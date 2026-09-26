"""Backend-owned searched CASE expressions."""

from typing import Any, Literal, overload

from snekql._aliases import _AliasOwner
from snekql._case import build_case
from snekql._literal import _IntegerLiteral, build_integer_literal
from snekql._value_expression import ExpressionMethods, ValueExpression
from snekql.expressions import Predicate
from snekql.mariadb.model import Model


@overload
def case[OwnerT: Model[Any] | _AliasOwner[Literal["mariadb"], Any, Any]](
    condition: Predicate[OwnerT, Literal["mariadb"]],
    *,
    then: int | ExpressionMethods[OwnerT, int, Literal["mariadb"]],
    otherwise: int | ExpressionMethods[OwnerT, int, Literal["mariadb"]],
) -> ValueExpression[OwnerT, int, int, Literal["mariadb"]]: ...


@overload
def case[OwnerT: Model[Any] | _AliasOwner[Literal["mariadb"], Any, Any]](
    condition: Predicate[OwnerT, Literal["mariadb"]],
    *,
    then: int
    | ExpressionMethods[OwnerT, int, Literal["mariadb"]]
    | ExpressionMethods[OwnerT, int | None, Literal["mariadb"]]
    | None,
    otherwise: int
    | ExpressionMethods[OwnerT, int, Literal["mariadb"]]
    | ExpressionMethods[OwnerT, int | None, Literal["mariadb"]]
    | None,
) -> ValueExpression[OwnerT, int | None, int, Literal["mariadb"]]: ...


@overload
def case[OwnerT: Model[Any] | _AliasOwner[Literal["mariadb"], Any, Any]](
    condition: Predicate[OwnerT, Literal["mariadb"]],
    *,
    then: float | ExpressionMethods[OwnerT, float, Literal["mariadb"]],
    otherwise: float | ExpressionMethods[OwnerT, float, Literal["mariadb"]],
) -> ValueExpression[OwnerT, float, float, Literal["mariadb"]]: ...


@overload
def case[OwnerT: Model[Any] | _AliasOwner[Literal["mariadb"], Any, Any]](
    condition: Predicate[OwnerT, Literal["mariadb"]],
    *,
    then: float
    | ExpressionMethods[OwnerT, float, Literal["mariadb"]]
    | ExpressionMethods[OwnerT, float | None, Literal["mariadb"]]
    | None,
    otherwise: float
    | ExpressionMethods[OwnerT, float, Literal["mariadb"]]
    | ExpressionMethods[OwnerT, float | None, Literal["mariadb"]]
    | None,
) -> ValueExpression[OwnerT, float | None, float, Literal["mariadb"]]: ...


@overload
def case[OwnerT: Model[Any] | _AliasOwner[Literal["mariadb"], Any, Any]](
    condition: Predicate[OwnerT, Literal["mariadb"]],
    *,
    then: str | ExpressionMethods[OwnerT, str, Literal["mariadb"]],
    otherwise: str | ExpressionMethods[OwnerT, str, Literal["mariadb"]],
) -> ValueExpression[OwnerT, str, str, Literal["mariadb"]]: ...


@overload
def case[OwnerT: Model[Any] | _AliasOwner[Literal["mariadb"], Any, Any]](
    condition: Predicate[OwnerT, Literal["mariadb"]],
    *,
    then: str
    | ExpressionMethods[OwnerT, str, Literal["mariadb"]]
    | ExpressionMethods[OwnerT, str | None, Literal["mariadb"]]
    | None,
    otherwise: str
    | ExpressionMethods[OwnerT, str, Literal["mariadb"]]
    | ExpressionMethods[OwnerT, str | None, Literal["mariadb"]]
    | None,
) -> ValueExpression[OwnerT, str | None, str, Literal["mariadb"]]: ...


def case(
    condition: Predicate[Any, Literal["mariadb"]], *, then: object, otherwise: object
) -> ValueExpression[Any, Any, Any, Literal["mariadb"]]:
    """Choose a compatible branch in SQL; UNKNOWN conditions use `otherwise`.

    Example: `case(User.score.gte(100), then="gold", otherwise="standard")`.
    """
    return build_case(condition, then=then, otherwise=otherwise, backend="mariadb")


def literal(value: int, /) -> _IntegerLiteral[Literal["mariadb"]]:
    """Bind a signed-64 native integer, for example a recursive depth seed."""
    return build_integer_literal(value, backend="mariadb")

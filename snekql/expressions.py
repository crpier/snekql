"""Query Builder expression objects shared by fields and queries."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Generic, TypeVar

from snekql.errors import QueryConstructionError

OwnerT = TypeVar("OwnerT")


@dataclass(frozen=True)
class Predicate(Generic[OwnerT]):
    """Boolean SQL predicate for one table model.

    Predicates are produced by column descriptor methods such as `User.email.eq`.
    They compose with `&`, `|`, and `~` instead of Python comparison operators.
    """

    kind: str = ""
    column: object | None = None
    value: object = None
    values: tuple[object, ...] = field(default_factory=tuple)
    children: tuple[Predicate[OwnerT], ...] = field(default_factory=tuple)

    def __and__(self, other: Predicate[OwnerT]) -> Predicate[OwnerT]:
        return Predicate(kind="and", children=(self, other))

    def __or__(self, other: Predicate[OwnerT]) -> Predicate[OwnerT]:
        return Predicate(kind="or", children=(self, other))

    def __invert__(self) -> Predicate[OwnerT]:
        return Predicate(kind="not", children=(self,))

    def __bool__(self) -> bool:
        raise QueryConstructionError("predicates cannot be used as booleans")


@dataclass(frozen=True)
class OrderBy(Generic[OwnerT]):
    """SQL ordering expression for one table model.

    `OrderBy` values are produced by column descriptor methods like `.asc()` and
    `.desc()` and consumed by select query builders.
    """

    column: object | None = None
    direction: str = ""


@dataclass(frozen=True)
class Assignment(Generic[OwnerT]):
    """SQL update assignment for one table model.

    `Assignment` values are produced by update-assignable column descriptors via
    `.to(value)` and consumed by `update(Model).set(...)`.
    """

    column: object | None = None
    value: object = None

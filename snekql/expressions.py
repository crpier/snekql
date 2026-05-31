"""Query Builder expression objects shared by fields and queries."""

from __future__ import annotations

from typing import Generic, TypeVar

OwnerT = TypeVar("OwnerT")


class Predicate(Generic[OwnerT]):
    """Boolean SQL predicate for one table model.

    Predicates are produced by column descriptor methods such as `User.email.eq`.
    They compose with `&`, `|`, and `~` instead of Python comparison operators.
    """

    def __and__(self, other: Predicate[OwnerT]) -> Predicate[OwnerT]:
        return Predicate()

    def __or__(self, other: Predicate[OwnerT]) -> Predicate[OwnerT]:
        return Predicate()

    def __invert__(self) -> Predicate[OwnerT]:
        return Predicate()


class OrderBy(Generic[OwnerT]):
    """SQL ordering expression for one table model.

    `OrderBy` values are produced by column descriptor methods like `.asc()` and
    `.desc()` and consumed by select query builders.
    """

    pass


class Assignment(Generic[OwnerT]):
    """SQL update assignment for one table model.

    `Assignment` values are produced by update-assignable column descriptors via
    `.to(value)` and consumed by `update(Model).set(...)`.
    """

    pass

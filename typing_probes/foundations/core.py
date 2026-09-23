"""Throwaway query typing with executable projection materialization.

This is not a SQL compiler or database runtime. Legacy TypeVars deliberately
make owner and value coordinates invariant, including phantom parameters.
"""

# Invariance is intentional; PEP 695 would infer variance instead.
# ruff: noqa: UP046

from collections.abc import Callable
from dataclasses import dataclass
from typing import Generic, TypeVar, cast

Owner = TypeVar("Owner")
Value = TypeVar("Value")
Result = TypeVar("Result")


class PrototypeError(Exception):
    """The experiment received inconsistent runtime query input."""


class Item(Generic[Owner, Value]):
    """An SQL expression with an invariant source and decoded value type."""

    def __init__(self, owner: type[Owner], sql: str) -> None:
        self.owner: type[Owner] = owner
        self.sql: str = sql


@dataclass
class Predicate(Generic[Owner]):
    owner: type[Owner]
    sql: str
    value: object


@dataclass
class Having(Generic[Owner]):
    owner: type[Owner]
    sql: str
    value: object


@dataclass
class Assignment(Generic[Owner]):
    owner: type[Owner]
    sql: str
    value: object


class Aggregate(Item[Owner, Value]):
    """Aggregate comparisons cannot be passed to a row-level WHERE."""

    def gt(self, value: Value) -> Having[Owner]:
        return Having(self.owner, f"{self.sql} > ?", value)


class Column(Item[Owner, Value]):
    """A column supports predicates, assignments, and typed aggregates."""

    def eq(self, value: Value) -> Predicate[Owner]:
        return Predicate(self.owner, f"{self.sql} = ?", value)

    def to(self, value: Value) -> Assignment[Owner]:
        return Assignment(self.owner, self.sql, value)

    def count(self) -> Aggregate[Owner, int]:
        return Aggregate(self.owner, f"COUNT({self.sql})")

    def sum(self: Column[Owner, int]) -> Aggregate[Owner, int | None]:
        return Aggregate(self.owner, f"SUM({self.sql})")


class Write[Result]:
    """Static write result marker; no write execution is implemented."""


class Query(Generic[Owner, Result]):
    """Carry selected SQL fragments and a callable for already-decoded values."""

    def __init__(
        self,
        owner: type[Owner],
        selections: tuple[str, ...],
        factory: Callable[..., Result],
    ) -> None:
        self.owner: type[Owner] = owner
        self.selections: tuple[str, ...] = selections
        self.factory: Callable[..., Result] = factory
        self.predicates: list[Predicate[Owner]] = []
        self.groupings: list[str] = []
        self.having_predicates: list[Having[Owner]] = []

    def where(self, predicate: Predicate[Owner]) -> Query[Owner, Result]:
        self.predicates.append(predicate)
        return self

    def group_by[T](self, column: Column[Owner, T]) -> Query[Owner, Result]:
        self.groupings.append(column.sql)
        return self

    def having(self, predicate: Having[Owner]) -> Query[Owner, Result]:
        self.having_predicates.append(predicate)
        return self

    def materialize_raw(self, *values: object) -> Result:
        """Apply the checked constructor; SQL decoding/validation is not modeled."""
        return self.factory(*values)


class Updating(Generic[Owner]):
    """Setting at least one assignment creates the filterable write builder."""

    def set(
        self, first: Assignment[Owner], *rest: Assignment[Owner]
    ) -> Assigned[Owner]:
        return Assigned((first, *rest))


class Assigned(Generic[Owner]):
    def __init__(self, assignments: tuple[Assignment[Owner], ...]) -> None:
        self.assignments: tuple[Assignment[Owner], ...] = assignments

    def where(self, predicate: Predicate[Owner]) -> Write[int]:
        del predicate
        return Write[int]()


class Deleting(Generic[Owner]):
    def where(self, predicate: Predicate[Owner]) -> Write[int]:
        del predicate
        return Write[int]()


class Projection[Owner, *Values]:
    """Accumulate one result coordinate per add, without arity overloads."""

    def __init__(self, owner: type[Owner], selections: tuple[str, ...]) -> None:
        self.owner: type[Owner] = owner
        self.selections: tuple[str, ...] = selections

    def add[Value](
        self, column: Item[Owner, Value]
    ) -> Projection[Owner, *Values, Value]:
        if column.owner is not self.owner:
            message = "Projection columns must belong to the same source"
            raise PrototypeError(message)
        return Projection(self.owner, (*self.selections, column.sql))

    def query(self) -> Query[Owner, tuple[*Values]]:
        def materialize(*values: object) -> tuple[*Values]:
            # Projection construction records order and types. A real runtime
            # must decode each SQL slot before entering this raw-value boundary.
            return cast("tuple[*Values]", values)

        return Query(self.owner, self.selections, materialize)

    def map[Result](self, factory: Callable[[*Values], Result]) -> Query[Owner, Result]:
        return Query(self.owner, self.selections, factory)


def columns[Owner, Value](column: Item[Owner, Value]) -> Projection[Owner, Value]:
    """Begin a positional projection with one precisely typed expression."""
    return Projection(column.owner, (column.sql,))

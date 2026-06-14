"""Query Builder expression objects shared by fields and queries."""

from __future__ import annotations

from dataclasses import dataclass, field

from snekql.errors import QueryConstructionError


@dataclass(frozen=True)
class Predicate[OwnerT]:
    """Boolean SQL predicate for one table model.

    Predicates are produced by column descriptor methods such as `User.email.eq`.
    They compose with `&`, `|`, and `~` instead of Python comparison operators.
    """

    kind: str = ""
    column: object | None = None
    value: object = None
    values: tuple[object, ...] = field(default_factory=tuple)
    # Type-erased so the recursive field does not pin OwnerT to invariant; this
    # is what makes `Predicate` covariant in its owner type (see proto_c).
    children: tuple[Predicate[object], ...] = field(default_factory=tuple)

    def __and__[Other](self, other: Predicate[Other]) -> Predicate[OwnerT | Other]:
        return Predicate(kind="and", children=(self, other))

    def __or__[Other](self, other: Predicate[Other]) -> Predicate[OwnerT | Other]:
        return Predicate(kind="or", children=(self, other))

    def __invert__(self) -> Predicate[OwnerT]:
        return Predicate(kind="not", children=(self,))

    def __bool__(self) -> bool:
        msg = "predicates cannot be used as booleans"
        raise QueryConstructionError(msg)


class Comparable[OwnerT, ValueT]:
    """Predicate-building surface shared by columns and aggregates.

    Both column descriptors (``Attr``) and :class:`Aggregate` mix this in so a
    comparison builds the same :class:`Predicate` whether it targets a column in
    ``WHERE`` (``Order.amount.gt(5)``) or an aggregate in ``HAVING``
    (``Order.amount.sum().gt(5)``). ``ValueT`` is the comparison value type -- a
    column's read type or an aggregate's result type -- and ``OwnerT`` the owning
    table model the resulting predicate is scoped to. Predicates store the
    operand as ``column`` (an ``Attr`` or an :class:`Aggregate`); the compiler
    renders the operand and encodes the value according to which it is.

    Text-only helpers (``like``/``not_like``) stay on ``Attr`` since they are not
    meaningful over an aggregate.
    """

    def eq(self, value: ValueT) -> Predicate[OwnerT]:
        if value is None:
            msg = "eq(None) is invalid; use is_null()"
            raise QueryConstructionError(msg)
        return Predicate(kind="eq", column=self, value=value)

    def ne(self, value: ValueT) -> Predicate[OwnerT]:
        if value is None:
            msg = "ne(None) is invalid; use is_not_null()"
            raise QueryConstructionError(msg)
        return Predicate(kind="ne", column=self, value=value)

    def is_null(self) -> Predicate[OwnerT]:
        return Predicate(kind="is_null", column=self)

    def is_not_null(self) -> Predicate[OwnerT]:
        return Predicate(kind="is_not_null", column=self)

    def in_(self, *values: ValueT) -> Predicate[OwnerT]:
        if not values:
            msg = "in_() requires at least one value"
            raise QueryConstructionError(msg)
        if any(candidate is None for candidate in values):
            msg = "in_() values cannot be None"
            raise QueryConstructionError(msg)
        return Predicate(kind="in", column=self, values=values)

    def not_in(self, *values: ValueT) -> Predicate[OwnerT]:
        if not values:
            msg = "not_in() requires at least one value"
            raise QueryConstructionError(msg)
        if any(candidate is None for candidate in values):
            msg = "not_in() values cannot be None"
            raise QueryConstructionError(msg)
        return Predicate(kind="not_in", column=self, values=values)

    def gt(self, value: ValueT) -> Predicate[OwnerT]:
        if value is None:
            msg = "gt(None) is invalid; use is_not_null()"
            raise QueryConstructionError(msg)
        return Predicate(kind="gt", column=self, value=value)

    def gte(self, value: ValueT) -> Predicate[OwnerT]:
        if value is None:
            msg = "gte(None) is invalid; use is_not_null()"
            raise QueryConstructionError(msg)
        return Predicate(kind="gte", column=self, value=value)

    def lt(self, value: ValueT) -> Predicate[OwnerT]:
        if value is None:
            msg = "lt(None) is invalid; use is_not_null()"
            raise QueryConstructionError(msg)
        return Predicate(kind="lt", column=self, value=value)

    def lte(self, value: ValueT) -> Predicate[OwnerT]:
        if value is None:
            msg = "lte(None) is invalid; use is_not_null()"
            raise QueryConstructionError(msg)
        return Predicate(kind="lte", column=self, value=value)

    def between(self, low: ValueT, high: ValueT) -> Predicate[OwnerT]:
        if low is None or high is None:
            msg = "between() bounds cannot be None; use is_null()/is_not_null()"
            raise QueryConstructionError(msg)
        return Predicate(kind="between", column=self, values=(low, high))


@dataclass(frozen=True)
class Aggregate[OwnerT, T](Comparable[OwnerT, T]):
    """SQL aggregate over a column (or ``COUNT(*)``), as a selectable expression.

    Produced by column methods (``Order.amount.sum()``) and the model
    ``count_all()`` classmethod for the star form. Fields are type-erased like
    :class:`Predicate` so the generic params stay phantom: ``OwnerT`` carries the
    owning table for the scope check, ``T`` the decoded result type. ``column`` is
    the wrapped column descriptor, or ``None`` for ``COUNT(*)``; ``owner`` is the
    owning table model, always present so it can anchor the ``FROM`` clause and the
    scope check.
    """

    func: str = ""
    column: object | None = None
    owner: object | None = None

    def asc(self) -> OrderBy[OwnerT]:
        """Order rows by this aggregate ascending (e.g. ``ORDER BY COUNT(id)``)."""

        return OrderBy(column=self, direction="ASC")

    def desc(self) -> OrderBy[OwnerT]:
        """Order rows by this aggregate descending."""

        return OrderBy(column=self, direction="DESC")


@dataclass(frozen=True)
class JoinOn[LeftOwnerT, RightOwnerT]:
    """Join condition relating two table models on equal columns.

    Produced by `FKAttr.references` from a foreign-key column against the
    column it references. The two owner type parameters record which models the
    condition relates so `join()` can require the new table to be tied to an
    already-joined one (in either argument order).
    """

    left_column: object | None = None
    right_column: object | None = None


@dataclass(frozen=True)
class OrderBy[OwnerT]:
    """SQL ordering expression for one table model.

    `OrderBy` values are produced by column descriptor methods like `.asc()` and
    `.desc()` and consumed by select query builders.
    """

    column: object | None = None
    direction: str = ""


@dataclass(frozen=True)
class Assignment[OwnerT]:
    """SQL update assignment for one table model.

    `Assignment` values are produced by update-assignable column descriptors via
    `.to(value)` and consumed by `update(Model).set(...)`.
    """

    column: object | None = None
    value: object = None

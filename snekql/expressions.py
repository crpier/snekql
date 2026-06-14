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


@dataclass(frozen=True)
class Aggregate[OwnerT, T]:
    """SQL aggregate over a column (or ``COUNT(*)``), as a selectable expression.

    Produced by column methods (``Order.amount.sum()``) and the model ``_count()``
    classmethod for the star form. Fields are type-erased like :class:`Predicate`
    so the generic params stay phantom: ``OwnerT`` carries the owning table for the
    scope check, ``T`` the decoded result type. ``column`` is the wrapped column
    descriptor, or ``None`` for ``COUNT(*)``; ``owner`` is the owning table model,
    always present so it can anchor the ``FROM`` clause and the scope check.
    """

    func: str = ""
    column: object | None = None
    owner: object | None = None


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

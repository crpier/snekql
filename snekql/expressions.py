"""Query Builder expression objects shared by fields and queries."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, ClassVar, Literal, Protocol, cast, overload, runtime_checkable
from warnings import deprecated

from snekql.errors import QueryCompilationError, QueryConstructionError


class _ColumnRef[T_co](Protocol):
    """Structural view of a column descriptor's read value type.

    Implemented by ``Attr`` (via a typing-only witness). Declared here so the
    column-vs-column comparison surface can be typed without importing the
    storage layer, which would form an import cycle.
    """

    def __column_value_type__(self) -> T_co: ...


@runtime_checkable
class ColumnRef[OwnerT, T](Protocol):
    """Read-only public annotation for a model-owned column reference.

    Concrete descriptor classes remain private implementation details. Use this
    protocol when an application helper needs to accept any accessed column while
    preserving its model owner and decoded value type.
    """

    def __column_owner_type__(self) -> OwnerT:
        """Typing-only witness for the model that owns this column."""

        raise NotImplementedError

    def __column_value_type__(self) -> T:
        """Typing-only witness for this column's decoded value type."""

        raise NotImplementedError


class _ColumnSubquery[T_co](Protocol):
    """Structural view of a single-column subquery's projected value type.

    Implemented by ``SelectValueQuery`` (via a typing-only witness). Declared
    here so ``in_subquery``/``not_in_subquery`` can be typed without importing
    the query layer, which would form an import cycle.
    """

    def __subquery_value_type__(self) -> T_co: ...


# The comparison surface's operator vocabulary, shared by literal comparisons
# (`eq(5)`) and column comparisons (`eq_col(Other.id)`): the node stores the
# builder-method name (so error messages can point back at the call site) and
# compiles it to its SQL symbol through this one table.
type ComparisonOperator = Literal["eq", "ne", "gt", "gte", "lt", "lte"]

_COMPARISON_SQL_OPERATORS: dict[ComparisonOperator, str] = {
    "eq": "=",
    "ne": "!=",
    "gt": ">",
    "gte": ">=",
    "lt": "<",
    "lte": "<=",
}

type CompoundOperator = Literal["AND", "OR"]

# The projection shape a node's nested select must satisfy, declared as a
# ClassVar so scope validators stay node-name-blind: ``"single_column"`` for
# membership (`IN (subquery)`), ``"select"`` for existence (`EXISTS`).
type PredicateSubqueryArity = Literal["single_column", "select"]

_BINARY_PREDICATE_CHILD_COUNT = 2


class PredicateCompiler(Protocol):
    """The compile-time facts a predicate node renders itself against.

    Query Compilation implements this over its ``(dialect, scope)`` pair; each
    node owns its SQL shape and parameter order and pulls everything dialect-
    or scope-dependent (placeholders, operand rendering, value encoding,
    nested-select compilation) through this seam. The double dispatch mirrors
    ADR 0004's open-AST ``SqlCompilable`` contract, extended to the built-in
    predicate nodes.
    """

    @property
    def placeholder(self) -> str: ...

    def render_operand(self, operand: object) -> str: ...

    def value_encoder(self, operand: object) -> Callable[[object], object]: ...

    def render_comparison_operand(self, other: object) -> str: ...

    def compile_scalar(self, scalar: object) -> tuple[str, tuple[object, ...]]: ...

    def compile_subquery(
        self,
        subquery: object,
        *,
        single_column: bool,
    ) -> tuple[str, tuple[object, ...]]: ...

    def compile(self, predicate: Predicate[Any]) -> tuple[str, tuple[object, ...]]: ...


class Predicate[OwnerT](ABC):
    """Boolean SQL predicate for one table model.

    Predicates are produced by column descriptor methods such as `User.email.eq`.
    They compose with `&`, `|`, and `~` instead of Python comparison operators.

    Each concrete predicate is a small frozen node that compiles itself through
    :class:`PredicateCompiler` (``__compile_predicate_sql__``) and exposes a
    structural surface (``__predicate_operand__``/``__predicate_children__``/
    ``__predicate_subquery__``) so scope validators traverse the tree without
    naming node types. ``OwnerT`` stays phantom on the nodes -- their fields are
    type-erased -- which keeps `Predicate` covariant in its owner type.
    """

    # Which nested-select shape this node carries, if any; validators read it
    # instead of maintaining kind sets.
    __predicate_subquery_arity__: ClassVar[PredicateSubqueryArity | None] = None

    def __and__[Other](self, other: Predicate[Other]) -> Predicate[OwnerT | Other]:
        return CompoundPredicate[OwnerT | Other](operator="AND", children=(self, other))

    def __or__[Other](self, other: Predicate[Other]) -> Predicate[OwnerT | Other]:
        return CompoundPredicate[OwnerT | Other](operator="OR", children=(self, other))

    def __invert__(self) -> Predicate[OwnerT]:
        return NegatedPredicate(child=self)

    def __bool__(self) -> bool:
        msg = "predicates cannot be used as booleans"
        raise QueryConstructionError(msg)

    @abstractmethod
    def __compile_predicate_sql__(
        self,
        compiler: PredicateCompiler,
    ) -> tuple[str, tuple[object, ...]]:
        """Compile this node to its SQL fragment and ordered parameters."""

    def __predicate_operand__(self) -> object | None:
        """The column/aggregate operand scope validators check, if any."""

        return None

    def __predicate_children__(self) -> tuple[Predicate[object], ...]:
        """Nested predicates the validators recurse into."""

        return ()

    def __predicate_subquery__(self) -> object | None:
        """The nested select this node carries, if any (see the arity flag)."""

        return None


@dataclass(frozen=True)
class ComparisonPredicate[OwnerT](Predicate[OwnerT]):
    """``operand <op> value`` for ``eq``/``ne``/``gt``/``gte``/``lt``/``lte``."""

    operand: object
    operator: ComparisonOperator
    value: object

    def __predicate_operand__(self) -> object | None:
        return self.operand

    def __compile_predicate_sql__(
        self,
        compiler: PredicateCompiler,
    ) -> tuple[str, tuple[object, ...]]:
        if self.value is None:
            msg = f"{self.operator}(None) is invalid; use is_not_null()"
            if self.operator == "eq":
                msg = "eq(None) is invalid; use is_null()"
            raise QueryCompilationError(msg)
        rendered = compiler.render_operand(self.operand)
        encode = compiler.value_encoder(self.operand)
        operator = _COMPARISON_SQL_OPERATORS[self.operator]
        return (
            f"{rendered} {operator} {compiler.placeholder}",
            (encode(self.value),),
        )


@dataclass(frozen=True)
class NullPredicate[OwnerT](Predicate[OwnerT]):
    """``operand IS NULL`` / ``operand IS NOT NULL``."""

    operand: object
    negated: bool

    def __predicate_operand__(self) -> object | None:
        return self.operand

    def __compile_predicate_sql__(
        self,
        compiler: PredicateCompiler,
    ) -> tuple[str, tuple[object, ...]]:
        operator = "IS NOT NULL" if self.negated else "IS NULL"
        return f"{compiler.render_operand(self.operand)} {operator}", ()


@dataclass(frozen=True)
class MembershipPredicate[OwnerT](Predicate[OwnerT]):
    """``operand IN (...)`` / ``operand NOT IN (...)`` over literal values."""

    operand: object
    values: tuple[object, ...]
    negated: bool

    def __predicate_operand__(self) -> object | None:
        return self.operand

    def __compile_predicate_sql__(
        self,
        compiler: PredicateCompiler,
    ) -> tuple[str, tuple[object, ...]]:
        if not self.values:
            msg = "IN predicates require at least one value"
            raise QueryCompilationError(msg)
        if any(value is None for value in self.values):
            msg = "IN predicate values cannot be None"
            raise QueryCompilationError(msg)
        rendered = compiler.render_operand(self.operand)
        encode = compiler.value_encoder(self.operand)
        placeholders = ", ".join(compiler.placeholder for _ in self.values)
        operator = "NOT IN" if self.negated else "IN"
        params = tuple(encode(value) for value in self.values)
        return f"{rendered} {operator} ({placeholders})", params


@dataclass(frozen=True)
class BetweenPredicate[OwnerT](Predicate[OwnerT]):
    """``operand BETWEEN low AND high``.

    Naming the bounds as two fields makes the "exactly two bounds" malformation
    structurally impossible; only a ``None`` bound remains to reject at compile.
    """

    operand: object
    low: object
    high: object

    def __predicate_operand__(self) -> object | None:
        return self.operand

    def __compile_predicate_sql__(
        self,
        compiler: PredicateCompiler,
    ) -> tuple[str, tuple[object, ...]]:
        if self.low is None or self.high is None:
            msg = "between() bounds cannot be None; use is_null()/is_not_null()"
            raise QueryCompilationError(msg)
        rendered = compiler.render_operand(self.operand)
        encode = compiler.value_encoder(self.operand)
        return (
            f"{rendered} BETWEEN {compiler.placeholder} AND {compiler.placeholder}",
            (encode(self.low), encode(self.high)),
        )


@dataclass(frozen=True)
class LikePredicate[OwnerT](Predicate[OwnerT]):
    """``operand LIKE pattern`` / ``operand NOT LIKE pattern``."""

    operand: object
    pattern: str
    negated: bool

    def __predicate_operand__(self) -> object | None:
        return self.operand

    def __compile_predicate_sql__(
        self,
        compiler: PredicateCompiler,
    ) -> tuple[str, tuple[object, ...]]:
        # Structural read: only a TEXT-storage column supports SQL pattern
        # matching, and the storage-type name is the fact the operand exposes.
        if getattr(self.operand, "storage_type_name", None) != "Text":
            name = "not_like" if self.negated else "like"
            msg = f"{name}() is only valid for text columns"
            raise QueryCompilationError(msg)
        rendered = compiler.render_operand(self.operand)
        encode = compiler.value_encoder(self.operand)
        operator = "NOT LIKE" if self.negated else "LIKE"
        return f"{rendered} {operator} {compiler.placeholder}", (encode(self.pattern),)


@dataclass(frozen=True)
class ColumnComparisonPredicate[OwnerT](Predicate[OwnerT]):
    """``operand <op> other`` where ``other`` is a column or scalar subquery."""

    operand: object
    operator: ComparisonOperator
    other: object

    def __predicate_operand__(self) -> object | None:
        return self.operand

    def __compile_predicate_sql__(
        self,
        compiler: PredicateCompiler,
    ) -> tuple[str, tuple[object, ...]]:
        rendered = compiler.render_operand(self.operand)
        operator = _COMPARISON_SQL_OPERATORS[self.operator]
        other = self.other
        if isinstance(other, Scalar):
            scalar = cast("Scalar[Any, Any, Any]", other)
            operand_sql, operand_params = compiler.compile_scalar(scalar)
            return f"{rendered} {operator} {operand_sql}", operand_params
        other_ref = compiler.render_comparison_operand(other)
        return f"{rendered} {operator} {other_ref}", ()


@dataclass(frozen=True)
class SubqueryMembershipPredicate[OwnerT](Predicate[OwnerT]):
    """``operand IN (subquery)`` / ``operand NOT IN (subquery)``."""

    __predicate_subquery_arity__: ClassVar[PredicateSubqueryArity | None] = (
        "single_column"
    )

    operand: object
    subquery: object
    negated: bool

    def __predicate_operand__(self) -> object | None:
        return self.operand

    def __predicate_subquery__(self) -> object | None:
        return self.subquery

    def __compile_predicate_sql__(
        self,
        compiler: PredicateCompiler,
    ) -> tuple[str, tuple[object, ...]]:
        rendered = compiler.render_operand(self.operand)
        sub_sql, sub_params = compiler.compile_subquery(
            self.subquery,
            single_column=True,
        )
        operator = "NOT IN" if self.negated else "IN"
        return f"{rendered} {operator} ({sub_sql})", sub_params


@dataclass(frozen=True)
class ExistencePredicate[OwnerT](Predicate[OwnerT]):
    """``EXISTS (subquery)`` / ``NOT EXISTS (subquery)``; carries no operand."""

    __predicate_subquery_arity__: ClassVar[PredicateSubqueryArity | None] = "select"

    subquery: object
    negated: bool

    def __predicate_subquery__(self) -> object | None:
        return self.subquery

    def __compile_predicate_sql__(
        self,
        compiler: PredicateCompiler,
    ) -> tuple[str, tuple[object, ...]]:
        sub_sql, sub_params = compiler.compile_subquery(
            self.subquery,
            single_column=False,
        )
        keyword = "NOT EXISTS" if self.negated else "EXISTS"
        return f"{keyword} ({sub_sql})", sub_params


@dataclass(frozen=True)
class CompoundPredicate[OwnerT](Predicate[OwnerT]):
    """``(left) AND (right)`` / ``(left) OR (right)``.

    Children are type-erased so the recursive field does not pin ``OwnerT`` to
    invariant; this is what makes `Predicate` covariant in its owner type.
    """

    operator: CompoundOperator
    children: tuple[Predicate[object], ...]

    def __predicate_children__(self) -> tuple[Predicate[object], ...]:
        return self.children

    def __compile_predicate_sql__(
        self,
        compiler: PredicateCompiler,
    ) -> tuple[str, tuple[object, ...]]:
        if len(self.children) != _BINARY_PREDICATE_CHILD_COUNT:
            msg = "compound predicate is malformed"
            raise QueryCompilationError(msg)
        left_sql, left_params = compiler.compile(self.children[0])
        right_sql, right_params = compiler.compile(self.children[1])
        return (
            f"({left_sql}) {self.operator} ({right_sql})",
            (*left_params, *right_params),
        )


@dataclass(frozen=True)
class NegatedPredicate[OwnerT](Predicate[OwnerT]):
    """``NOT (child)``."""

    child: Predicate[object]

    def __predicate_children__(self) -> tuple[Predicate[object], ...]:
        return (self.child,)

    def __compile_predicate_sql__(
        self,
        compiler: PredicateCompiler,
    ) -> tuple[str, tuple[object, ...]]:
        child_sql, child_params = compiler.compile(self.child)
        return f"NOT ({child_sql})", child_params


@dataclass(frozen=True)
class Scalar[OwnerT, T, CompareT = T]:
    """A scalar subquery: a single-column, single-value SELECT used as a value.

    Produced by the top-level ``scalar(...)`` factory wrapping a one-column
    select. It is a selectable (usable in a projection, like :class:`Aggregate`)
    and a comparison operand (the right side of a ``*_col`` comparison). ``T`` is
    the decoded result type carried for the projection's result shape. The
    wrapped query is type-erased as ``subquery`` to avoid importing the query
    layer here; the compiler reads its ``.state`` and decodes through its single
    projected selectable.
    """

    subquery: object | None = None

    def __accepts_comparison__(self, _value: CompareT) -> None:
        """Typing-only contravariant witness for the comparison value domain."""

    def __column_owner_type__(self) -> OwnerT:
        """Typing-only witness for singleton-select owner inference."""

        raise NotImplementedError

    def __column_value_type__(self) -> T:
        """Typing-only witness for singleton-select result inference."""

        raise NotImplementedError


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

    def __accepts_comparison__(self, _value: ValueT) -> None:
        """Typing-only contravariant witness for comparison-domain inference."""

    @overload
    @deprecated("eq(None) is invalid; use is_null()")
    def eq(self, value: None) -> Predicate[OwnerT]: ...
    @overload
    def eq(self, value: ValueT) -> Predicate[OwnerT]: ...
    def eq(self, value: ValueT | None) -> Predicate[OwnerT]:
        if value is None:
            msg = "eq(None) is invalid; use is_null()"
            raise QueryConstructionError(msg)
        return ComparisonPredicate(operand=self, operator="eq", value=value)

    @overload
    @deprecated("ne(None) is invalid; use is_not_null()")
    def ne(self, value: None) -> Predicate[OwnerT]: ...
    @overload
    def ne(self, value: ValueT) -> Predicate[OwnerT]: ...
    def ne(self, value: ValueT | None) -> Predicate[OwnerT]:
        if value is None:
            msg = "ne(None) is invalid; use is_not_null()"
            raise QueryConstructionError(msg)
        return ComparisonPredicate(operand=self, operator="ne", value=value)

    def is_null(self) -> Predicate[OwnerT]:
        return NullPredicate(operand=self, negated=False)

    def is_not_null(self) -> Predicate[OwnerT]:
        return NullPredicate(operand=self, negated=True)

    @overload
    @deprecated("in_(None) is invalid; use is_null()")
    def in_(self, value: None, /) -> Predicate[OwnerT]: ...
    @overload
    def in_(self, *values: ValueT) -> Predicate[OwnerT]: ...
    def in_(self, *values: ValueT | None) -> Predicate[OwnerT]:
        if not values:
            msg = "in_() requires at least one value"
            raise QueryConstructionError(msg)
        if any(candidate is None for candidate in values):
            msg = "in_() values cannot be None"
            raise QueryConstructionError(msg)
        return MembershipPredicate(operand=self, values=values, negated=False)

    @overload
    @deprecated("not_in(None) is invalid; use is_not_null()")
    def not_in(self, value: None, /) -> Predicate[OwnerT]: ...
    @overload
    def not_in(self, *values: ValueT) -> Predicate[OwnerT]: ...
    def not_in(self, *values: ValueT | None) -> Predicate[OwnerT]:
        if not values:
            msg = "not_in() requires at least one value"
            raise QueryConstructionError(msg)
        if any(candidate is None for candidate in values):
            msg = "not_in() values cannot be None"
            raise QueryConstructionError(msg)
        return MembershipPredicate(operand=self, values=values, negated=True)

    @overload
    @deprecated("gt(None) is invalid; use is_not_null()")
    def gt(self, value: None) -> Predicate[OwnerT]: ...
    @overload
    def gt(self, value: ValueT) -> Predicate[OwnerT]: ...
    def gt(self, value: ValueT | None) -> Predicate[OwnerT]:
        if value is None:
            msg = "gt(None) is invalid; use is_not_null()"
            raise QueryConstructionError(msg)
        return ComparisonPredicate(operand=self, operator="gt", value=value)

    @overload
    @deprecated("gte(None) is invalid; use is_not_null()")
    def gte(self, value: None) -> Predicate[OwnerT]: ...
    @overload
    def gte(self, value: ValueT) -> Predicate[OwnerT]: ...
    def gte(self, value: ValueT | None) -> Predicate[OwnerT]:
        if value is None:
            msg = "gte(None) is invalid; use is_not_null()"
            raise QueryConstructionError(msg)
        return ComparisonPredicate(operand=self, operator="gte", value=value)

    @overload
    @deprecated("lt(None) is invalid; use is_not_null()")
    def lt(self, value: None) -> Predicate[OwnerT]: ...
    @overload
    def lt(self, value: ValueT) -> Predicate[OwnerT]: ...
    def lt(self, value: ValueT | None) -> Predicate[OwnerT]:
        if value is None:
            msg = "lt(None) is invalid; use is_not_null()"
            raise QueryConstructionError(msg)
        return ComparisonPredicate(operand=self, operator="lt", value=value)

    @overload
    @deprecated("lte(None) is invalid; use is_not_null()")
    def lte(self, value: None) -> Predicate[OwnerT]: ...
    @overload
    def lte(self, value: ValueT) -> Predicate[OwnerT]: ...
    def lte(self, value: ValueT | None) -> Predicate[OwnerT]:
        if value is None:
            msg = "lte(None) is invalid; use is_not_null()"
            raise QueryConstructionError(msg)
        return ComparisonPredicate(operand=self, operator="lte", value=value)

    @overload
    @deprecated("between() bounds cannot be None; use is_null()/is_not_null()")
    def between(self, low: None, high: ValueT) -> Predicate[OwnerT]: ...
    @overload
    @deprecated("between() bounds cannot be None; use is_null()/is_not_null()")
    def between(self, low: ValueT, high: None) -> Predicate[OwnerT]: ...
    @overload
    def between(self, low: ValueT, high: ValueT) -> Predicate[OwnerT]: ...
    def between(self, low: ValueT | None, high: ValueT | None) -> Predicate[OwnerT]:
        if low is None or high is None:
            msg = "between() bounds cannot be None; use is_null()/is_not_null()"
            raise QueryConstructionError(msg)
        return BetweenPredicate(operand=self, low=low, high=high)

    # Comparisons against another expression (a column or a scalar subquery)
    # rather than a literal value. A column operand on the other side is what a
    # correlated subquery uses to relate its inner row to the outer row; a
    # scalar-subquery operand compares against the subquery's single value. A
    # column operand's value type must match this column's; a scalar operand is
    # accepted regardless of value type, since aggregate scalars are commonly
    # nullable (``AVG`` -> ``float | None``). Whether the operand's table is in
    # scope is checked when the query compiles (an out-of-scope reference is a
    # compilation error unless it correlates to an enclosing query).

    def eq_col(
        self,
        other: _ColumnRef[ValueT] | Scalar[Any, Any, ValueT],
    ) -> Predicate[OwnerT]:
        return ColumnComparisonPredicate(operand=self, operator="eq", other=other)

    def ne_col(
        self,
        other: _ColumnRef[ValueT] | Scalar[Any, Any, ValueT],
    ) -> Predicate[OwnerT]:
        return ColumnComparisonPredicate(operand=self, operator="ne", other=other)

    def gt_col(
        self,
        other: _ColumnRef[ValueT] | Scalar[Any, Any, ValueT],
    ) -> Predicate[OwnerT]:
        return ColumnComparisonPredicate(operand=self, operator="gt", other=other)

    def gte_col(
        self,
        other: _ColumnRef[ValueT] | Scalar[Any, Any, ValueT],
    ) -> Predicate[OwnerT]:
        return ColumnComparisonPredicate(operand=self, operator="gte", other=other)

    def lt_col(
        self,
        other: _ColumnRef[ValueT] | Scalar[Any, Any, ValueT],
    ) -> Predicate[OwnerT]:
        return ColumnComparisonPredicate(operand=self, operator="lt", other=other)

    def lte_col(
        self,
        other: _ColumnRef[ValueT] | Scalar[Any, Any, ValueT],
    ) -> Predicate[OwnerT]:
        return ColumnComparisonPredicate(operand=self, operator="lte", other=other)

    def in_subquery(
        self,
        subquery: _ColumnSubquery[ValueT],
    ) -> Predicate[OwnerT]:
        """Test membership against a single-column subquery (``IN (SELECT ...)``)."""

        return SubqueryMembershipPredicate(
            operand=self,
            subquery=subquery,
            negated=False,
        )

    def not_in_subquery(
        self,
        subquery: _ColumnSubquery[ValueT],
    ) -> Predicate[OwnerT]:
        """Negated membership against a single-column subquery (``NOT IN``)."""

        return SubqueryMembershipPredicate(
            operand=self,
            subquery=subquery,
            negated=True,
        )


@dataclass(frozen=True)
class Aggregate[OwnerT, T, CompareT = T](Comparable[OwnerT, CompareT]):
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

    def __column_owner_type__(self) -> OwnerT:
        """Typing-only witness for singleton-select owner inference."""

        raise NotImplementedError

    def __column_value_type__(self) -> T:
        """Typing-only witness for singleton-select result inference."""

        raise NotImplementedError

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

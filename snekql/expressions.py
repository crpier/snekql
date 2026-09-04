"""Query Builder expression objects shared by fields and queries."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass
from typing import (
    Any,
    ClassVar,
    Literal,
    Never,
    Protocol,
    cast,
    overload,
    runtime_checkable,
)

from snekql._query_readiness import _ExecutableQuery
from snekql.errors import QueryCompilationError, QueryConstructionError

type AggregateFunction = Literal["AVG", "COUNT", "MAX", "MIN", "SUM"]


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

    def eq(self, value: T) -> Predicate[OwnerT]:
        """Build an equality predicate for this column."""

        raise NotImplementedError


class _ColumnSubquery[T_co, ReadinessT_co](Protocol):
    """Structural view of a single-column subquery's projected value type.

    Implemented by ``SelectValueQuery`` (via a typing-only witness). Declared
    here so ``in_subquery``/``not_in_subquery`` can be typed without importing
    the query layer, which would form an import cycle.
    """

    def __subquery_value_type__(self) -> T_co: ...

    def _readiness_type(self) -> ReadinessT_co: ...


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

    def render_operand(self, operand: object) -> tuple[str, tuple[object, ...]]: ...

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

    def __init__(self, _private: Never, /) -> None:
        raise NotImplementedError

    # Which nested-select shape this node carries, if any; validators read it
    # instead of maintaining kind sets.
    __predicate_subquery_arity__: ClassVar[PredicateSubqueryArity | None] = None

    def __and__[Other](self, other: Predicate[Other]) -> Predicate[OwnerT | Other]:
        return CompoundPredicate[OwnerT | Other](
            operator="AND",
            children=(
                _require_predicate_node(self),
                _require_predicate_node(other),
            ),
        )

    def __or__[Other](self, other: Predicate[Other]) -> Predicate[OwnerT | Other]:
        return CompoundPredicate[OwnerT | Other](
            operator="OR",
            children=(
                _require_predicate_node(self),
                _require_predicate_node(other),
            ),
        )

    def __invert__(self) -> Predicate[OwnerT]:
        return NegatedPredicate(child=_require_predicate_node(self))

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


class _PredicateNode[OwnerT](Predicate[OwnerT], ABC):
    """Private base proving a predicate came from a supported factory."""


def _require_predicate_node[OwnerT](
    predicate: Predicate[OwnerT],
) -> _PredicateNode[OwnerT]:
    """Keep caller-defined predicate implementations out of query state."""

    if not isinstance(predicate, _PredicateNode):
        msg = "predicates must be built from columns or query factories"
        raise QueryConstructionError(msg)
    return predicate


@dataclass(frozen=True)
class ComparisonPredicate[OwnerT](_PredicateNode[OwnerT]):
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
        rendered, operand_params = compiler.render_operand(self.operand)
        encode = compiler.value_encoder(self.operand)
        operator = _COMPARISON_SQL_OPERATORS[self.operator]
        return (
            f"{rendered} {operator} {compiler.placeholder}",
            (*operand_params, encode(self.value)),
        )


@dataclass(frozen=True)
class NullPredicate[OwnerT](_PredicateNode[OwnerT]):
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
        rendered, operand_params = compiler.render_operand(self.operand)
        return f"{rendered} {operator}", operand_params


@dataclass(frozen=True)
class MembershipPredicate[OwnerT](_PredicateNode[OwnerT]):
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
        rendered, operand_params = compiler.render_operand(self.operand)
        encode = compiler.value_encoder(self.operand)
        placeholders = ", ".join(compiler.placeholder for _ in self.values)
        operator = "NOT IN" if self.negated else "IN"
        params = (*operand_params, *(encode(value) for value in self.values))
        return f"{rendered} {operator} ({placeholders})", params


@dataclass(frozen=True)
class BetweenPredicate[OwnerT](_PredicateNode[OwnerT]):
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
        rendered, operand_params = compiler.render_operand(self.operand)
        encode = compiler.value_encoder(self.operand)
        return (
            f"{rendered} BETWEEN {compiler.placeholder} AND {compiler.placeholder}",
            (*operand_params, encode(self.low), encode(self.high)),
        )


@dataclass(frozen=True)
class LikePredicate[OwnerT](_PredicateNode[OwnerT]):
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
        rendered, operand_params = compiler.render_operand(self.operand)
        encode = compiler.value_encoder(self.operand)
        operator = "NOT LIKE" if self.negated else "LIKE"
        return (
            f"{rendered} {operator} {compiler.placeholder}",
            (*operand_params, encode(self.pattern)),
        )


@dataclass(frozen=True)
class ColumnComparisonPredicate[OwnerT](_PredicateNode[OwnerT]):
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
        rendered, rendered_params = compiler.render_operand(self.operand)
        operator = _COMPARISON_SQL_OPERATORS[self.operator]
        other = self.other
        if isinstance(other, _Scalar):
            scalar = cast("_Scalar[Any, Any, Any]", other)
            operand_sql, operand_params = compiler.compile_scalar(scalar)
            return (
                f"{rendered} {operator} {operand_sql}",
                (*rendered_params, *operand_params),
            )
        other_ref = compiler.render_comparison_operand(other)
        return f"{rendered} {operator} {other_ref}", rendered_params


@dataclass(frozen=True)
class SubqueryMembershipPredicate[OwnerT](_PredicateNode[OwnerT]):
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
        rendered, operand_params = compiler.render_operand(self.operand)
        sub_sql, sub_params = compiler.compile_subquery(
            self.subquery,
            single_column=True,
        )
        operator = "NOT IN" if self.negated else "IN"
        return (
            f"{rendered} {operator} ({sub_sql})",
            (*operand_params, *sub_params),
        )


@dataclass(frozen=True)
class ExistencePredicate[OwnerT](_PredicateNode[OwnerT]):
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
class CompoundPredicate[OwnerT](_PredicateNode[OwnerT]):
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
class NegatedPredicate[OwnerT](_PredicateNode[OwnerT]):
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


class Scalar[OwnerT, T, CompareT = T](ABC):
    """Non-constructible annotation for a scalar subquery.

    Obtain scalar expressions from the public `scalar(...)` query factory.
    """

    def __init__(self, _private: Never, /) -> None:
        raise NotImplementedError

    def __accepts_comparison__(self, _value: CompareT) -> None:
        """Typing-only contravariant witness for the comparison value domain."""

        del _value

    @abstractmethod
    def __column_owner_type__(self) -> OwnerT:
        """Typing-only witness for singleton-select owner inference."""

    @abstractmethod
    def __column_value_type__(self) -> T:
        """Typing-only witness for singleton-select result inference."""


@dataclass(frozen=True)
class _Scalar[OwnerT, T, CompareT = T](Scalar[OwnerT, T, CompareT]):
    """Private scalar-subquery node produced only by the Query Builder."""

    subquery: object

    def __column_owner_type__(self) -> OwnerT:
        raise NotImplementedError

    def __column_value_type__(self) -> T:
        raise NotImplementedError


class Comparable[OwnerT, ValueT, ColumnValueT = ValueT]:
    """Predicate-building surface shared by columns and aggregates.

    Both column descriptors (``Attr``) and :class:`Aggregate` mix this in so a
    comparison builds the same :class:`Predicate` whether it targets a column in
    ``WHERE`` (``Order.amount.gt(5)``) or an aggregate in ``HAVING``
    (``Order.amount.sum().gt(5)``). ``ValueT`` is the non-null literal comparison
    domain, while ``ColumnValueT`` preserves the full read type for comparisons
    against columns and subqueries. ``OwnerT`` is the owning table model the
    resulting predicate is scoped to. Predicates store the operand as ``column``
    (an ``Attr`` or an :class:`Aggregate`); the compiler renders the operand and
    encodes the value according to which it is.

    Text-only helpers (``like``/``not_like``) stay on ``Attr`` since they are not
    meaningful over an aggregate.
    """

    def __accepts_comparison__(self, _value: ValueT) -> None:
        """Typing-only contravariant witness for comparison-domain inference."""

    def eq(self, value: ValueT) -> Predicate[OwnerT]:
        if value is None:
            msg = "eq(None) is invalid; use is_null()"
            raise QueryConstructionError(msg)
        return ComparisonPredicate(operand=self, operator="eq", value=value)

    def ne(self, value: ValueT) -> Predicate[OwnerT]:
        if value is None:
            msg = "ne(None) is invalid; use is_not_null()"
            raise QueryConstructionError(msg)
        return ComparisonPredicate(operand=self, operator="ne", value=value)

    def is_null(self) -> Predicate[OwnerT]:
        return NullPredicate(operand=self, negated=False)

    def is_not_null(self) -> Predicate[OwnerT]:
        return NullPredicate(operand=self, negated=True)

    @overload
    def in_(self, value: ValueT, /) -> Predicate[OwnerT]: ...
    @overload
    def in_(
        self,
        value: ValueT,
        second: ValueT,
        /,
        *values: ValueT,
    ) -> Predicate[OwnerT]: ...
    def in_(self, *values: ValueT | None) -> Predicate[OwnerT]:
        if not values:
            msg = "in_() requires at least one value"
            raise QueryConstructionError(msg)
        if any(candidate is None for candidate in values):
            msg = "in_() values cannot be None"
            raise QueryConstructionError(msg)
        return MembershipPredicate(operand=self, values=values, negated=False)

    @overload
    def not_in(self, value: ValueT, /) -> Predicate[OwnerT]: ...
    @overload
    def not_in(
        self,
        value: ValueT,
        second: ValueT,
        /,
        *values: ValueT,
    ) -> Predicate[OwnerT]: ...
    def not_in(self, *values: ValueT | None) -> Predicate[OwnerT]:
        if not values:
            msg = "not_in() requires at least one value"
            raise QueryConstructionError(msg)
        if any(candidate is None for candidate in values):
            msg = "not_in() values cannot be None"
            raise QueryConstructionError(msg)
        return MembershipPredicate(operand=self, values=values, negated=True)

    def gt(self, value: ValueT) -> Predicate[OwnerT]:
        if value is None:
            msg = "gt(None) is invalid; use is_not_null()"
            raise QueryConstructionError(msg)
        self._require_ordering()
        return ComparisonPredicate(operand=self, operator="gt", value=value)

    def gte(self, value: ValueT) -> Predicate[OwnerT]:
        if value is None:
            msg = "gte(None) is invalid; use is_not_null()"
            raise QueryConstructionError(msg)
        self._require_ordering()
        return ComparisonPredicate(operand=self, operator="gte", value=value)

    def lt(self, value: ValueT) -> Predicate[OwnerT]:
        if value is None:
            msg = "lt(None) is invalid; use is_not_null()"
            raise QueryConstructionError(msg)
        self._require_ordering()
        return ComparisonPredicate(operand=self, operator="lt", value=value)

    def lte(self, value: ValueT) -> Predicate[OwnerT]:
        if value is None:
            msg = "lte(None) is invalid; use is_not_null()"
            raise QueryConstructionError(msg)
        self._require_ordering()
        return ComparisonPredicate(operand=self, operator="lte", value=value)

    def between(self, low: ValueT, high: ValueT) -> Predicate[OwnerT]:
        if low is None or high is None:
            msg = "between() bounds cannot be None; use is_null()/is_not_null()"
            raise QueryConstructionError(msg)
        self._require_ordering()
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
        other: _ColumnRef[ColumnValueT] | Scalar[Any, Any, ValueT],
    ) -> Predicate[OwnerT]:
        self._require_factory_scalar(other)
        return ColumnComparisonPredicate(operand=self, operator="eq", other=other)

    def ne_col(
        self,
        other: _ColumnRef[ColumnValueT] | Scalar[Any, Any, ValueT],
    ) -> Predicate[OwnerT]:
        self._require_factory_scalar(other)
        return ColumnComparisonPredicate(operand=self, operator="ne", other=other)

    def gt_col(
        self,
        other: _ColumnRef[ColumnValueT] | Scalar[Any, Any, ValueT],
    ) -> Predicate[OwnerT]:
        self._require_factory_scalar(other)
        self._require_ordering()
        return ColumnComparisonPredicate(operand=self, operator="gt", other=other)

    def gte_col(
        self,
        other: _ColumnRef[ColumnValueT] | Scalar[Any, Any, ValueT],
    ) -> Predicate[OwnerT]:
        self._require_factory_scalar(other)
        self._require_ordering()
        return ColumnComparisonPredicate(operand=self, operator="gte", other=other)

    def lt_col(
        self,
        other: _ColumnRef[ColumnValueT] | Scalar[Any, Any, ValueT],
    ) -> Predicate[OwnerT]:
        self._require_factory_scalar(other)
        self._require_ordering()
        return ColumnComparisonPredicate(operand=self, operator="lt", other=other)

    def lte_col(
        self,
        other: _ColumnRef[ColumnValueT] | Scalar[Any, Any, ValueT],
    ) -> Predicate[OwnerT]:
        self._require_factory_scalar(other)
        self._require_ordering()
        return ColumnComparisonPredicate(operand=self, operator="lte", other=other)

    @staticmethod
    def _require_factory_scalar(other: object) -> None:
        """Reject scalar annotations not produced by the Query Builder factory."""

        if isinstance(other, Scalar) and not isinstance(other, _Scalar):
            msg = "scalar operands must be built with scalar()"
            raise QueryConstructionError(msg)

    def _require_ordering(self) -> None:
        """Reject ordered operations when an operand has no logical order."""

    def in_subquery(
        self,
        subquery: _ColumnSubquery[ColumnValueT, _ExecutableQuery],
    ) -> Predicate[OwnerT]:
        """Test membership against an executable single-column subquery."""

        return SubqueryMembershipPredicate(
            operand=self,
            subquery=subquery,
            negated=False,
        )

    def not_in_subquery(
        self,
        subquery: _ColumnSubquery[ColumnValueT, _ExecutableQuery],
    ) -> Predicate[OwnerT]:
        """Negated membership against an executable single-column subquery."""

        return SubqueryMembershipPredicate(
            operand=self,
            subquery=subquery,
            negated=True,
        )


class Aggregate[OwnerT, T, CompareT = T](
    Comparable[OwnerT, CompareT, CompareT],
    ABC,
):
    """Non-constructible annotation for a SQL aggregate expression.

    Obtain aggregates from column methods such as `Order.amount.sum()` or the
    model `count_all()` classmethod.
    """

    def __init__(self, _private: Never, /) -> None:
        raise NotImplementedError

    @abstractmethod
    def __column_owner_type__(self) -> OwnerT:
        """Typing-only witness for singleton-select owner inference."""

    @abstractmethod
    def __column_value_type__(self) -> T:
        """Typing-only witness for singleton-select result inference."""

    def asc(self) -> OrderBy[OwnerT]:
        """Order rows by this aggregate ascending (e.g. `COUNT(id)`)."""

        return _OrderBy(column=self, direction="ASC")

    def desc(self) -> OrderBy[OwnerT]:
        """Order rows by this aggregate descending."""

        return _OrderBy(column=self, direction="DESC")


@dataclass(frozen=True)
class _Aggregate[OwnerT, T, CompareT = T](Aggregate[OwnerT, T, CompareT]):
    """Private aggregate node produced only by model and column methods."""

    column: object | None
    func: AggregateFunction
    owner: object

    def __post_init__(self) -> None:
        if type(self.func) is not str or self.func not in {
            "AVG",
            "COUNT",
            "MAX",
            "MIN",
            "SUM",
        }:
            msg = f"unsupported aggregate function: {self.func!r}"
            raise QueryConstructionError(msg)

    def __column_owner_type__(self) -> OwnerT:
        raise NotImplementedError

    def __column_value_type__(self) -> T:
        raise NotImplementedError


class JoinOn[LeftOwnerT, RightOwnerT](ABC):
    """Non-constructible annotation for a model join condition.

    Obtain join conditions from foreign-key column `.references(...)` methods.
    """

    def __init__(self, _private: Never, /) -> None:
        raise NotImplementedError

    @abstractmethod
    def __join_on_types__(self) -> tuple[LeftOwnerT, RightOwnerT]:
        """Typing-only witness for the models related by this condition."""


@dataclass(frozen=True)
class _JoinOn[LeftOwnerT, RightOwnerT](JoinOn[LeftOwnerT, RightOwnerT]):
    """Private join-condition node produced only by foreign-key columns."""

    left_column: object
    right_column: object

    def __join_on_types__(self) -> tuple[LeftOwnerT, RightOwnerT]:
        raise NotImplementedError


class OrderBy[OwnerT](ABC):
    """Non-constructible annotation for an SQL ordering expression.

    Obtain orderings from column or aggregate `.asc()` and `.desc()` methods.
    """

    def __init__(self, _private: Never, /) -> None:
        raise NotImplementedError

    @abstractmethod
    def __order_by_owner_type__(self) -> OwnerT:
        """Typing-only witness for the model owning this ordering."""


@dataclass(frozen=True)
class _OrderBy[OwnerT](OrderBy[OwnerT]):
    """Private ordering node produced only by columns and aggregates."""

    column: object
    direction: Literal["ASC", "DESC"]

    def __order_by_owner_type__(self) -> OwnerT:
        raise NotImplementedError


class DoNothing:
    """Conflict action that discards an insert instead of raising.

    Pass the bare marker as an `on_conflict` action:

    ```python
    insert(User(email=email)).on_conflict(User.email, action=DoNothing)
    ```
    """


class InsertedValue:
    """Internal marker for the attempted insert value of an assigned column."""


class Assignment[OwnerT](ABC):
    """Non-constructible annotation for a model-column assignment.

    Obtain assignments from update-assignable column `.to(...)` and
    `.to_inserted()` methods.
    """

    def __init__(self, _private: Never, /) -> None:
        raise NotImplementedError

    @abstractmethod
    def __assignment_owner_type__(self) -> OwnerT:
        """Typing-only witness for the model targeted by this assignment."""


@dataclass(frozen=True)
class _Assignment[OwnerT](Assignment[OwnerT]):
    """Private assignment node produced only by update-assignable columns."""

    column: object
    value: object

    def __assignment_owner_type__(self) -> OwnerT:
        raise NotImplementedError


@dataclass(frozen=True, init=False)
class DoUpdate[OwnerT]:
    """Conflict action that updates one or more columns.

    Pass assignments built from columns on the inserted model:

    ```python
    DoUpdate(User.name.to_inserted(), User.status.to("active"))
    ```
    """

    assignments: tuple[_Assignment[OwnerT], ...]

    @overload
    def __init__(self, assignment: Assignment[OwnerT], /) -> None: ...

    @overload
    def __init__(
        self,
        assignment: Assignment[OwnerT],
        second: Assignment[OwnerT],
        /,
        *assignments: Assignment[OwnerT],
    ) -> None: ...

    def __init__(self, *assignments: Assignment[OwnerT]) -> None:
        if not assignments:
            msg = "DoUpdate requires at least one assignment"
            raise QueryConstructionError(msg)
        checked: list[_Assignment[OwnerT]] = []
        for assignment in assignments:
            if not isinstance(assignment, _Assignment):
                msg = "assignments must be built from columns"
                raise QueryConstructionError(msg)
            checked.append(assignment)
        object.__setattr__(self, "assignments", tuple(checked))

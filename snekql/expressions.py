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

from snekql._output_label import _OutputLabel
from snekql._query_readiness import _ExecutableQuery
from snekql.errors import QueryCompilationError, QueryConstructionError

type AggregateFunction = Literal["AVG", "COUNT", "MAX", "MIN", "SUM"]


class _ExpressionFamily[FamilyT](Protocol):
    """Named inputs preserve backend identity; compilation checks operand shape."""

    def __expression_family_type__(self) -> FamilyT: ...


class _OwnedColumnRef[Owner, Value, Family = Any](_ExpressionFamily[Family], Protocol):
    """Read-only witnesses preserve both owners without requiring literal methods.

    A nullable right operand must remain compatible with a nonnullable left
    operand. Requiring the full ColumnRef protocol would make its value invariant
    through eq(value), rejecting that comparison.
    """

    def __column_owner_type__(self) -> Owner: ...

    def __column_value_type__(self) -> Value: ...


@runtime_checkable
class ColumnRef[OwnerT, T, FamilyT = Any](Protocol):
    """Read-only public annotation for a model-owned column reference.

    Concrete descriptor classes remain private implementation details. Use this
    protocol when an application helper needs to accept any accessed column while
    preserving its model owner and decoded value type.
    """

    def __expression_family_type__(self) -> FamilyT:
        """Typing-only family evidence preserved through read-only helpers."""
        raise NotImplementedError

    def __column_owner_type__(self) -> OwnerT:
        """Typing-only witness for the model that owns this column."""

        raise NotImplementedError

    def __column_value_type__(self) -> T:
        """Typing-only witness for this column's decoded value type."""

        raise NotImplementedError

    def eq(self, value: T) -> Predicate[OwnerT, FamilyT]:
        """Build an equality predicate for this column."""

        raise NotImplementedError


class _ColumnSubquery[T_co, ReadinessT_co, FamilyT_co](
    _ExpressionFamily[FamilyT_co], Protocol
):
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

    def render_comparison_operand(
        self, other: object
    ) -> tuple[str, tuple[object, ...]]: ...

    def compile_scalar(self, scalar: object) -> tuple[str, tuple[object, ...]]: ...

    def compile_subquery(
        self,
        subquery: object,
        *,
        single_column: bool,
    ) -> tuple[str, tuple[object, ...]]: ...

    def compile(self, predicate: Predicate[Any]) -> tuple[str, tuple[object, ...]]: ...


class Predicate[OwnerT, FamilyT = Any](ABC):
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

    def __expression_family_type__(self) -> FamilyT:
        """Typing-only family evidence retained independently of table scope."""
        raise NotImplementedError

    # Which nested-select shape this node carries, if any; validators read it
    # instead of maintaining kind sets.
    __predicate_subquery_arity__: ClassVar[PredicateSubqueryArity | None] = None

    def __and__[Other](
        self, other: Predicate[Other, FamilyT]
    ) -> Predicate[OwnerT | Other, FamilyT]:
        return CompoundPredicate[OwnerT | Other, FamilyT](
            operator="AND",
            children=(
                _require_predicate_node(self),
                _require_predicate_node(other),
            ),
        )

    def __or__[Other](
        self, other: Predicate[Other, FamilyT]
    ) -> Predicate[OwnerT | Other, FamilyT]:
        return CompoundPredicate[OwnerT | Other, FamilyT](
            operator="OR",
            children=(
                _require_predicate_node(self),
                _require_predicate_node(other),
            ),
        )

    def __invert__(self) -> Predicate[OwnerT, FamilyT]:
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

    def __predicate_children__(self) -> tuple[Predicate[object, Any], ...]:
        """Nested predicates the validators recurse into."""

        return ()

    def __predicate_subquery__(self) -> object | None:
        """The nested select this node carries, if any (see the arity flag)."""

        return None

    def __predicate_nested_selects__(self) -> tuple[object, ...]:
        """Expose nested SELECTs for definition dependency discovery."""
        subquery = self.__predicate_subquery__()
        return () if subquery is None else (subquery,)


class _PredicateNode[OwnerT, FamilyT = Any](Predicate[OwnerT, FamilyT], ABC):
    """Private base proving a predicate came from a supported factory."""

    def __predicate_grouping_operands__(self) -> tuple[object, ...]:
        """Direct HAVING operands, excluding columns inside nested SELECTs.

        WHERE keeps its separate traversal because right-hand columns can
        correlate to an outer query whose scope is only known at compilation.
        """

        operand = self.__predicate_operand__()
        return () if operand is None else (operand,)


def _require_predicate_node[OwnerT, FamilyT](
    predicate: Predicate[OwnerT, FamilyT],
) -> _PredicateNode[OwnerT, FamilyT]:
    """Keep caller-defined predicate implementations out of query state."""

    if not isinstance(predicate, _PredicateNode):
        msg = "predicates must be built from columns or query factories"
        raise QueryConstructionError(msg)
    return predicate


@dataclass(frozen=True)
class ComparisonPredicate[OwnerT, FamilyT = Any](_PredicateNode[OwnerT, FamilyT]):
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
class NullPredicate[OwnerT, FamilyT = Any](_PredicateNode[OwnerT, FamilyT]):
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
class MembershipPredicate[OwnerT, FamilyT = Any](_PredicateNode[OwnerT, FamilyT]):
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
class BetweenPredicate[OwnerT, FamilyT = Any](_PredicateNode[OwnerT, FamilyT]):
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
class LikePredicate[OwnerT, FamilyT = Any](_PredicateNode[OwnerT, FamilyT]):
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
        if getattr(self.operand, "storage_type_name", None) not in {"Text", "LongText"}:
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
class ColumnComparisonPredicate[OwnerT, FamilyT = Any](_PredicateNode[OwnerT, FamilyT]):
    """``operand <op> other`` where ``other`` is a column or scalar subquery."""

    operand: object
    operator: ComparisonOperator
    other: object

    def __predicate_operand__(self) -> object | None:
        return self.operand

    def __predicate_nested_selects__(self) -> tuple[object, ...]:
        """Scalar comparison inputs retain their own SELECT dependency scope."""
        return (self.other.subquery,) if isinstance(self.other, _Scalar) else ()

    def __predicate_grouping_operands__(self) -> tuple[object, ...]:
        """Check both columns without treating a nested SELECT as an outer key."""

        if isinstance(self.other, _Scalar):
            return (self.operand,)
        return (self.operand, self.other)

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
        other_ref, other_params = compiler.render_comparison_operand(other)
        return f"{rendered} {operator} {other_ref}", (*rendered_params, *other_params)


@dataclass(frozen=True)
class SubqueryMembershipPredicate[OwnerT, FamilyT = Any](
    _PredicateNode[OwnerT, FamilyT]
):
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
class ExistencePredicate[OwnerT, FamilyT = Any](_PredicateNode[OwnerT, FamilyT]):
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
class CompoundPredicate[OwnerT, FamilyT = Any](_PredicateNode[OwnerT, FamilyT]):
    """``(left) AND (right)`` / ``(left) OR (right)``.

    Children are type-erased so the recursive field does not pin ``OwnerT`` to
    invariant; this is what makes `Predicate` covariant in its owner type.
    """

    operator: CompoundOperator
    children: tuple[Predicate[object, Any], ...]

    def __predicate_children__(self) -> tuple[Predicate[object, Any], ...]:
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
class NegatedPredicate[OwnerT, FamilyT = Any](_PredicateNode[OwnerT, FamilyT]):
    """``NOT (child)``."""

    child: Predicate[object, Any]

    def __predicate_children__(self) -> tuple[Predicate[object, Any], ...]:
        return (self.child,)

    def __compile_predicate_sql__(
        self,
        compiler: PredicateCompiler,
    ) -> tuple[str, tuple[object, ...]]:
        child_sql, child_params = compiler.compile(self.child)
        return f"NOT ({child_sql})", child_params


class Scalar[OwnerT, T, CompareT = T, FamilyT = Any](ABC):
    """Non-constructible annotation for a scalar subquery.

    Obtain scalar expressions from the public `scalar(...)` query factory.
    """

    def __init__(self, _private: Never, /) -> None:
        raise NotImplementedError

    def __expression_family_type__(self) -> FamilyT:
        """Typing-only family evidence independent of the scalar's outer owner."""
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

    def label(self, name: str) -> _OutputLabel[OwnerT, T, CompareT, FamilyT]:
        """Name the scalar SQL output without changing its nullable result type."""
        return _OutputLabel(name=name, operand=self)


@dataclass(frozen=True)
class _Scalar[OwnerT, T, CompareT = T, FamilyT = Any](
    Scalar[OwnerT, T, CompareT, FamilyT]
):
    """Private scalar-subquery node produced only by the Query Builder."""

    subquery: object

    def __column_owner_type__(self) -> OwnerT:
        raise NotImplementedError

    def __column_value_type__(self) -> T:
        raise NotImplementedError


class Comparable[OwnerT, ValueT, ColumnValueT = ValueT, FamilyT = Any]:
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

    def __expression_family_type__(self) -> FamilyT:
        """Typing-only family evidence for composed operands and predicates."""
        raise NotImplementedError

    def __accepts_comparison__(self, _value: ValueT) -> None:
        """Typing-only contravariant witness for comparison-domain inference."""

    def eq(self, value: ValueT) -> Predicate[OwnerT, FamilyT]:
        if value is None:
            msg = "eq(None) is invalid; use is_null()"
            raise QueryConstructionError(msg)
        return ComparisonPredicate(operand=self, operator="eq", value=value)

    def ne(self, value: ValueT) -> Predicate[OwnerT, FamilyT]:
        if value is None:
            msg = "ne(None) is invalid; use is_not_null()"
            raise QueryConstructionError(msg)
        return ComparisonPredicate(operand=self, operator="ne", value=value)

    def is_null(self) -> Predicate[OwnerT, FamilyT]:
        return NullPredicate(operand=self, negated=False)

    def is_not_null(self) -> Predicate[OwnerT, FamilyT]:
        return NullPredicate(operand=self, negated=True)

    @overload
    def in_(self, value: ValueT, /) -> Predicate[OwnerT, FamilyT]: ...
    @overload
    def in_(
        self,
        value: ValueT,
        second: ValueT,
        /,
        *values: ValueT,
    ) -> Predicate[OwnerT, FamilyT]: ...
    def in_(self, *values: ValueT | None) -> Predicate[OwnerT, FamilyT]:
        if not values:
            msg = "in_() requires at least one value"
            raise QueryConstructionError(msg)
        if any(candidate is None for candidate in values):
            msg = "in_() values cannot be None"
            raise QueryConstructionError(msg)
        return MembershipPredicate(operand=self, values=values, negated=False)

    @overload
    def not_in(self, value: ValueT, /) -> Predicate[OwnerT, FamilyT]: ...
    @overload
    def not_in(
        self,
        value: ValueT,
        second: ValueT,
        /,
        *values: ValueT,
    ) -> Predicate[OwnerT, FamilyT]: ...
    def not_in(self, *values: ValueT | None) -> Predicate[OwnerT, FamilyT]:
        if not values:
            msg = "not_in() requires at least one value"
            raise QueryConstructionError(msg)
        if any(candidate is None for candidate in values):
            msg = "not_in() values cannot be None"
            raise QueryConstructionError(msg)
        return MembershipPredicate(operand=self, values=values, negated=True)

    def gt(self, value: ValueT) -> Predicate[OwnerT, FamilyT]:
        if value is None:
            msg = "gt(None) is invalid; use is_not_null()"
            raise QueryConstructionError(msg)
        self._require_ordering()
        return ComparisonPredicate(operand=self, operator="gt", value=value)

    def gte(self, value: ValueT) -> Predicate[OwnerT, FamilyT]:
        if value is None:
            msg = "gte(None) is invalid; use is_not_null()"
            raise QueryConstructionError(msg)
        self._require_ordering()
        return ComparisonPredicate(operand=self, operator="gte", value=value)

    def lt(self, value: ValueT) -> Predicate[OwnerT, FamilyT]:
        if value is None:
            msg = "lt(None) is invalid; use is_not_null()"
            raise QueryConstructionError(msg)
        self._require_ordering()
        return ComparisonPredicate(operand=self, operator="lt", value=value)

    def lte(self, value: ValueT) -> Predicate[OwnerT, FamilyT]:
        if value is None:
            msg = "lte(None) is invalid; use is_not_null()"
            raise QueryConstructionError(msg)
        self._require_ordering()
        return ComparisonPredicate(operand=self, operator="lte", value=value)

    def between(self, low: ValueT, high: ValueT) -> Predicate[OwnerT, FamilyT]:
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
    # checked against its comparison domain, allowing nullable aggregate results.
    # Column comparisons retain both owners. Nested scalar scope is checked by
    # compilation. Keep the scalar overload first: scalars also implement column
    # witnesses, but their inner tables must not become outer predicate owners.

    @overload
    def eq_col(
        self, other: Scalar[Any, Any, ValueT, FamilyT]
    ) -> Predicate[OwnerT, FamilyT]: ...

    @overload
    def eq_col[OtherOwner](
        self, other: _OwnedColumnRef[OtherOwner, ColumnValueT | None, FamilyT]
    ) -> Predicate[OwnerT | OtherOwner, FamilyT]: ...

    def eq_col(
        self,
        other: _OwnedColumnRef[Any, ColumnValueT | None, FamilyT]
        | Scalar[Any, Any, ValueT, FamilyT],
    ) -> Predicate[Any, FamilyT]:
        self._require_factory_scalar(other)
        return ColumnComparisonPredicate(operand=self, operator="eq", other=other)

    @overload
    def ne_col(
        self, other: Scalar[Any, Any, ValueT, FamilyT]
    ) -> Predicate[OwnerT, FamilyT]: ...

    @overload
    def ne_col[OtherOwner](
        self, other: _OwnedColumnRef[OtherOwner, ColumnValueT | None, FamilyT]
    ) -> Predicate[OwnerT | OtherOwner, FamilyT]: ...

    def ne_col(
        self,
        other: _OwnedColumnRef[Any, ColumnValueT | None, FamilyT]
        | Scalar[Any, Any, ValueT, FamilyT],
    ) -> Predicate[Any, FamilyT]:
        self._require_factory_scalar(other)
        return ColumnComparisonPredicate(operand=self, operator="ne", other=other)

    @overload
    def gt_col(
        self, other: Scalar[Any, Any, ValueT, FamilyT]
    ) -> Predicate[OwnerT, FamilyT]: ...

    @overload
    def gt_col[OtherOwner](
        self, other: _OwnedColumnRef[OtherOwner, ColumnValueT | None, FamilyT]
    ) -> Predicate[OwnerT | OtherOwner, FamilyT]: ...

    def gt_col(
        self,
        other: _OwnedColumnRef[Any, ColumnValueT | None, FamilyT]
        | Scalar[Any, Any, ValueT, FamilyT],
    ) -> Predicate[Any, FamilyT]:
        self._require_factory_scalar(other)
        self._require_ordering()
        return ColumnComparisonPredicate(operand=self, operator="gt", other=other)

    @overload
    def gte_col(
        self, other: Scalar[Any, Any, ValueT, FamilyT]
    ) -> Predicate[OwnerT, FamilyT]: ...

    @overload
    def gte_col[OtherOwner](
        self, other: _OwnedColumnRef[OtherOwner, ColumnValueT | None, FamilyT]
    ) -> Predicate[OwnerT | OtherOwner, FamilyT]: ...

    def gte_col(
        self,
        other: _OwnedColumnRef[Any, ColumnValueT | None, FamilyT]
        | Scalar[Any, Any, ValueT, FamilyT],
    ) -> Predicate[Any, FamilyT]:
        self._require_factory_scalar(other)
        self._require_ordering()
        return ColumnComparisonPredicate(operand=self, operator="gte", other=other)

    @overload
    def lt_col(
        self, other: Scalar[Any, Any, ValueT, FamilyT]
    ) -> Predicate[OwnerT, FamilyT]: ...

    @overload
    def lt_col[OtherOwner](
        self, other: _OwnedColumnRef[OtherOwner, ColumnValueT | None, FamilyT]
    ) -> Predicate[OwnerT | OtherOwner, FamilyT]: ...

    def lt_col(
        self,
        other: _OwnedColumnRef[Any, ColumnValueT | None, FamilyT]
        | Scalar[Any, Any, ValueT, FamilyT],
    ) -> Predicate[Any, FamilyT]:
        self._require_factory_scalar(other)
        self._require_ordering()
        return ColumnComparisonPredicate(operand=self, operator="lt", other=other)

    @overload
    def lte_col(
        self, other: Scalar[Any, Any, ValueT, FamilyT]
    ) -> Predicate[OwnerT, FamilyT]: ...

    @overload
    def lte_col[OtherOwner](
        self, other: _OwnedColumnRef[OtherOwner, ColumnValueT | None, FamilyT]
    ) -> Predicate[OwnerT | OtherOwner, FamilyT]: ...

    def lte_col(
        self,
        other: _OwnedColumnRef[Any, ColumnValueT | None, FamilyT]
        | Scalar[Any, Any, ValueT, FamilyT],
    ) -> Predicate[Any, FamilyT]:
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
        subquery: _ColumnSubquery[ColumnValueT, _ExecutableQuery, FamilyT],
    ) -> Predicate[OwnerT, FamilyT]:
        """Test membership against an executable single-column subquery."""

        return SubqueryMembershipPredicate(
            operand=self,
            subquery=subquery,
            negated=False,
        )

    def not_in_subquery(
        self,
        subquery: _ColumnSubquery[ColumnValueT, _ExecutableQuery, FamilyT],
    ) -> Predicate[OwnerT, FamilyT]:
        """Negated membership against an executable single-column subquery."""

        return SubqueryMembershipPredicate(
            operand=self,
            subquery=subquery,
            negated=True,
        )


class Aggregate[OwnerT, T, CompareT = T, FamilyT = Any](
    Comparable[OwnerT, CompareT, CompareT, FamilyT],
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

    def label(self, name: str) -> _OutputLabel[OwnerT, T, CompareT, FamilyT]:
        """Name the aggregate result, retaining its value and comparison domains."""
        return _OutputLabel(name=name, operand=self)

    def asc(self) -> OrderBy[OwnerT]:
        """Order rows by this aggregate ascending (e.g. `COUNT(id)`)."""

        return _OrderBy(column=self, direction="ASC")

    def desc(self) -> OrderBy[OwnerT]:
        """Order rows by this aggregate descending."""

        return _OrderBy(column=self, direction="DESC")


@dataclass(frozen=True)
class _Aggregate[OwnerT, T, CompareT = T, FamilyT = Any](
    Aggregate[OwnerT, T, CompareT, FamilyT]
):
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

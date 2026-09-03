"""Typed predicate node construction and self-compilation tests (#227).

Every predicate builder returns a dedicated frozen node subclassing
``Predicate``, and each node owns its SQL shape by compiling itself through the
``PredicateCompiler`` seam. The stub compiler below renders fixed tokens so the
tests pin each node's shape and parameter order without involving a dialect.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, cast

from snektest import assert_eq, assert_isinstance, assert_raises, test

from snekql.expressions import (
    BetweenPredicate,
    ColumnComparisonPredicate,
    ComparisonPredicate,
    CompoundPredicate,
    ExistencePredicate,
    LikePredicate,
    MembershipPredicate,
    NegatedPredicate,
    NullPredicate,
    Predicate,
    SubqueryMembershipPredicate,
)
from snekql.sqlite import (
    PENDING_GENERATION,
    Fetched,
    ForeignKey,
    Integer,
    Model,
    Pending,
    QueryCompilationError,
    Text,
    exists,
    not_exists,
    select,
)


class User[S = Pending](Model[S, "User[Fetched]"]):
    """Base table used by the node-construction checks."""

    id: User.GenCol[int] = Integer(primary_key=True, default=PENDING_GENERATION)
    email: User.Col[str] = Text(nullable=False)


class Order[S = Pending](Model[S, "Order[Fetched]"]):
    """Second table for column comparisons and subquery predicates."""

    id: Order.GenCol[int] = Integer(primary_key=True, default=PENDING_GENERATION)
    user_id: Order.FKCol[User, int] = ForeignKey(User.id)


class _StubCompiler:
    """A minimal ``PredicateCompiler`` rendering fixed tokens.

    Nodes own their SQL shape; everything dialect- or scope-dependent comes
    from the compiler, so replacing it with fixed tokens isolates exactly what
    each node contributes: operator text, placeholder positions, and parameter
    order. Received operands are recorded so tests can assert what flowed
    through the seam.
    """

    def __init__(self) -> None:
        self.operands: list[object] = []
        self.subquery_arities: list[bool] = []

    @property
    def placeholder(self) -> str:
        return "?"

    def render_operand(self, operand: object) -> tuple[str, tuple[object, ...]]:
        self.operands.append(operand)
        return "operand", ()

    def value_encoder(self, operand: object) -> Callable[[object], object]:
        self.operands.append(operand)
        return lambda value: ("encoded", value)

    def render_comparison_operand(self, other: object) -> str:
        self.operands.append(other)
        return "other_column"

    def compile_scalar(self, scalar: object) -> tuple[str, tuple[object, ...]]:
        self.operands.append(scalar)
        return "(SELECT scalar)", ("scalar-param",)

    def compile_subquery(
        self,
        subquery: object,
        *,
        single_column: bool,
    ) -> tuple[str, tuple[object, ...]]:
        self.operands.append(subquery)
        self.subquery_arities.append(single_column)
        return "SELECT sub", ("sub-param",)

    def compile(self, predicate: Predicate[Any]) -> tuple[str, tuple[object, ...]]:
        return predicate.__compile_predicate_sql__(self)


@test(mark="fast")
def builders_return_dedicated_node_families() -> None:
    """Each predicate builder returns its typed node, still a ``Predicate``."""

    subquery = select(Order.user_id).all()
    cases: tuple[tuple[Predicate[Any], type[Predicate[Any]]], ...] = (
        (User.id.eq(1), ComparisonPredicate),
        (User.id.ne(1), ComparisonPredicate),
        (User.id.gt(1), ComparisonPredicate),
        (User.id.gte(1), ComparisonPredicate),
        (User.id.lt(1), ComparisonPredicate),
        (User.id.lte(1), ComparisonPredicate),
        (User.email.is_null(), NullPredicate),
        (User.email.is_not_null(), NullPredicate),
        (User.id.in_(1, 2), MembershipPredicate),
        (User.id.not_in(1, 2), MembershipPredicate),
        (User.id.between(1, 10), BetweenPredicate),
        (User.email.like("%a%"), LikePredicate),
        (User.email.not_like("%a%"), LikePredicate),
        (Order.user_id.eq_col(User.id), ColumnComparisonPredicate),
        (Order.user_id.ne_col(User.id), ColumnComparisonPredicate),
        (Order.user_id.gt_col(User.id), ColumnComparisonPredicate),
        (Order.user_id.gte_col(User.id), ColumnComparisonPredicate),
        (Order.user_id.lt_col(User.id), ColumnComparisonPredicate),
        (Order.user_id.lte_col(User.id), ColumnComparisonPredicate),
        (User.id.in_subquery(subquery), SubqueryMembershipPredicate),
        (User.id.not_in_subquery(subquery), SubqueryMembershipPredicate),
        (exists(subquery), ExistencePredicate),
        (not_exists(subquery), ExistencePredicate),
        (User.id.eq(1) & User.id.eq(2), CompoundPredicate),
        (User.id.eq(1) | User.id.eq(2), CompoundPredicate),
        (~User.id.eq(1), NegatedPredicate),
    )

    for predicate, node_family in cases:
        assert_isinstance(predicate, node_family)
        assert_isinstance(predicate, Predicate)


@test(mark="fast")
def bare_predicate_base_cannot_be_instantiated() -> None:
    """The abstract ``Predicate`` base rejects direct construction."""

    predicate_factory = cast("Callable[[], object]", Predicate)

    with assert_raises(TypeError):
        _ = predicate_factory()


@test(mark="fast")
def comparison_nodes_compile_their_operator_and_encoded_value() -> None:
    """Each comparison operator renders its symbol against one placeholder."""

    compiler = _StubCompiler()
    cases = {
        User.id.eq(5): "=",
        User.id.ne(5): "!=",
        User.id.gt(5): ">",
        User.id.gte(5): ">=",
        User.id.lt(5): "<",
        User.id.lte(5): "<=",
    }

    for predicate, operator in cases.items():
        sql, params = predicate.__compile_predicate_sql__(compiler)
        assert_eq(sql, f"operand {operator} ?")
        assert_eq(params, (("encoded", 5),))


@test(mark="fast")
def comparison_node_rejects_none_with_null_predicate_hint() -> None:
    """A None comparison value is rejected at compile with the null-method hint."""

    compiler = _StubCompiler()
    raw_eq: Predicate[User] = ComparisonPredicate[User](
        operand=User.id,
        operator="eq",
        value=None,
    )
    raw_gt: Predicate[User] = ComparisonPredicate[User](
        operand=User.id,
        operator="gt",
        value=None,
    )

    with assert_raises(QueryCompilationError) as raised_eq:
        _ = raw_eq.__compile_predicate_sql__(compiler)
    assert_eq(str(raised_eq.exception), "eq(None) is invalid; use is_null()")

    with assert_raises(QueryCompilationError) as raised_gt:
        _ = raw_gt.__compile_predicate_sql__(compiler)
    assert_eq(str(raised_gt.exception), "gt(None) is invalid; use is_not_null()")


@test(mark="fast")
def null_nodes_compile_without_parameters() -> None:
    """IS NULL / IS NOT NULL render the operand alone, with no parameters."""

    compiler = _StubCompiler()

    assert_eq(
        User.email.is_null().__compile_predicate_sql__(compiler),
        ("operand IS NULL", ()),
    )
    assert_eq(
        User.email.is_not_null().__compile_predicate_sql__(compiler),
        ("operand IS NOT NULL", ()),
    )


@test(mark="fast")
def membership_nodes_compile_one_placeholder_per_value() -> None:
    """IN / NOT IN render one placeholder per value, encoding each in order."""

    compiler = _StubCompiler()

    sql, params = User.id.in_(1, 2, 3).__compile_predicate_sql__(compiler)
    assert_eq(sql, "operand IN (?, ?, ?)")
    assert_eq(params, (("encoded", 1), ("encoded", 2), ("encoded", 3)))

    sql, params = User.id.not_in(1).__compile_predicate_sql__(compiler)
    assert_eq(sql, "operand NOT IN (?)")
    assert_eq(params, (("encoded", 1),))


@test(mark="fast")
def between_node_compiles_bounds_in_order_and_rejects_none() -> None:
    """BETWEEN renders two placeholders in bound order; None bounds raise."""

    compiler = _StubCompiler()

    sql, params = User.id.between(1, 10).__compile_predicate_sql__(compiler)
    assert_eq(sql, "operand BETWEEN ? AND ?")
    assert_eq(params, (("encoded", 1), ("encoded", 10)))

    raw_between: Predicate[User] = BetweenPredicate[User](
        operand=User.id, low=1, high=None
    )
    with assert_raises(QueryCompilationError) as raised:
        _ = raw_between.__compile_predicate_sql__(compiler)
    assert_eq(
        str(raised.exception),
        "between() bounds cannot be None; use is_null()/is_not_null()",
    )


@test(mark="fast")
def like_nodes_compile_pattern_and_gate_on_text_storage() -> None:
    """LIKE / NOT LIKE encode the pattern; non-text operands are rejected."""

    compiler = _StubCompiler()

    sql, params = User.email.like("%a%").__compile_predicate_sql__(compiler)
    assert_eq(sql, "operand LIKE ?")
    assert_eq(params, (("encoded", "%a%"),))

    sql, params = User.email.not_like("%a%").__compile_predicate_sql__(compiler)
    assert_eq(sql, "operand NOT LIKE ?")
    assert_eq(params, (("encoded", "%a%"),))

    raw_like: Predicate[User] = LikePredicate[User](
        operand=User.id,
        pattern="%a%",
        negated=False,
    )
    with assert_raises(QueryCompilationError) as raised:
        _ = raw_like.__compile_predicate_sql__(compiler)
    assert_eq(str(raised.exception), "like() is only valid for text columns")


@test(mark="fast")
def column_comparison_nodes_compile_against_the_rendered_operand() -> None:
    """Column comparisons render the other side through the compiler seam."""

    compiler = _StubCompiler()

    sql, params = Order.user_id.eq_col(User.id).__compile_predicate_sql__(compiler)
    assert_eq(sql, "operand = other_column")
    assert_eq(params, ())

    sql, params = Order.user_id.lte_col(User.id).__compile_predicate_sql__(compiler)
    assert_eq(sql, "operand <= other_column")
    assert_eq(params, ())


@test(mark="fast")
def subquery_nodes_compile_through_the_subquery_seam() -> None:
    """Membership and existence nodes wrap the compiled subquery SQL."""

    compiler = _StubCompiler()
    subquery = select(Order.user_id).all()

    sql, params = User.id.in_subquery(subquery).__compile_predicate_sql__(compiler)
    assert_eq(sql, "operand IN (SELECT sub)")
    assert_eq(params, ("sub-param",))

    sql, params = User.id.not_in_subquery(subquery).__compile_predicate_sql__(compiler)
    assert_eq(sql, "operand NOT IN (SELECT sub)")
    assert_eq(params, ("sub-param",))

    sql, params = exists(subquery).__compile_predicate_sql__(compiler)
    assert_eq(sql, "EXISTS (SELECT sub)")
    assert_eq(params, ("sub-param",))

    sql, params = not_exists(subquery).__compile_predicate_sql__(compiler)
    assert_eq(sql, "NOT EXISTS (SELECT sub)")
    assert_eq(params, ("sub-param",))

    # Membership demands a single-column subquery; existence takes any select.
    assert_eq(compiler.subquery_arities, [True, True, False, False])


@test(mark="fast")
def compound_and_negated_nodes_compile_their_children_in_order() -> None:
    """AND/OR parenthesize both children in order; NOT wraps its child."""

    compiler = _StubCompiler()

    sql, params = (User.id.eq(1) & User.id.eq(2)).__compile_predicate_sql__(compiler)
    assert_eq(sql, "(operand = ?) AND (operand = ?)")
    assert_eq(params, (("encoded", 1), ("encoded", 2)))

    sql, params = (User.id.eq(1) | User.id.eq(2)).__compile_predicate_sql__(compiler)
    assert_eq(sql, "(operand = ?) OR (operand = ?)")
    assert_eq(params, (("encoded", 1), ("encoded", 2)))

    sql, params = (~User.id.eq(1)).__compile_predicate_sql__(compiler)
    assert_eq(sql, "NOT (operand = ?)")
    assert_eq(params, (("encoded", 1),))

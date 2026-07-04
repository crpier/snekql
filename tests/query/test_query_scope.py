"""ScopeResolver unit tests: one scope mechanism for every operand kind.

Issue #226: "is this operand's table in scope" was answered by parallel
validators in ``_query_state`` and hand-threaded ``scope_models`` tuples in the
compiler. ``ScopeResolver`` owns that question: it derives the visible models
(own plus any enclosing query's), decides column qualification, layers scopes
for subqueries, and checks any operand kind (column, aggregate, dialect leaf)
at one call site with the caller's clause name and error class.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from snektest import assert_eq, assert_raises, test

from snekql import sqlite
from snekql._query_scope import ScopeResolver
from snekql.sqlite import (
    PENDING_GENERATION,
    Fetched,
    Pending,
    QueryCompilationError,
    QueryConstructionError,
)

if TYPE_CHECKING:
    from snekql._dialect_expr import CompileCtx
    from snekql.model import Table


class User[S = Pending](sqlite.Model[S, "User[Fetched]"]):
    """Anchor table providing in-scope columns and aggregates."""

    id: User.GenCol[int] = sqlite.Integer(
        primary_key=True,
        auto_increment=True,
        default=PENDING_GENERATION,
    )
    country: User.Col[str] = sqlite.Text(nullable=False)


class Order[S = Pending](sqlite.Model[S, "Order[Fetched]"]):
    """Joinable table so a scope can hold more than one own model."""

    id: Order.GenCol[int] = sqlite.Integer(
        primary_key=True,
        auto_increment=True,
        default=PENDING_GENERATION,
    )
    user_id: Order.FKCol[User, int] = sqlite.ForeignKey(User.id)
    amount: Order.Col[int] = sqlite.Integer(nullable=False)


class Unrelated[S = Pending](sqlite.Model[S, "Unrelated[Fetched]"]):
    """Table never brought into scope; its columns must be rejected."""

    id: Unrelated.GenCol[int] = sqlite.Integer(
        primary_key=True,
        auto_increment=True,
        default=PENDING_GENERATION,
    )


class _FakeDialectLeaf:
    """Minimal ``SqlCompilable`` operand naming its owning table."""

    def __init__(self, owner: type[Table[Any]]) -> None:
        self._owner = owner

    def __owner_model__(self) -> type[Table[Any]]:
        return self._owner

    def __compile_sql__(self, ctx: CompileCtx) -> str:
        return "1"


@test(mark="fast")
def models_lists_own_then_outer() -> None:
    """The visible models are the query's own tables then the enclosing ones."""

    scope = ScopeResolver(own_models=(Order,), outer_models=(User,))

    assert_eq(scope.models, (Order, User))


@test(mark="fast")
def single_table_scope_is_unqualified() -> None:
    """A one-table statement renders bare column names."""

    scope = ScopeResolver(own_models=(User,))

    assert_eq(scope.qualified, False)


@test(mark="fast")
def joined_scope_is_qualified() -> None:
    """More than one own table forces table-qualified column references."""

    scope = ScopeResolver(own_models=(User, Order))

    assert_eq(scope.qualified, True)


@test(mark="fast")
def subquery_scope_is_qualified() -> None:
    """Any enclosing scope forces qualification, even for a one-table inner."""

    scope = ScopeResolver(own_models=(Order,), outer_models=(User,))

    assert_eq(scope.qualified, True)


@test(mark="fast")
def enter_subquery_layers_the_current_scope_as_outer() -> None:
    """A subquery's own tables come first; everything visible before is outer."""

    outer = ScopeResolver(own_models=(User,))

    inner = outer.enter_subquery((Order,))

    assert_eq(inner.own_models, (Order,))
    assert_eq(inner.outer_models, (User,))
    assert_eq(inner.models, (Order, User))


@test(mark="fast")
def enter_subquery_nests_transitively() -> None:
    """A doubly nested subquery still sees every enclosing scope's tables."""

    outermost = ScopeResolver(own_models=(User,))

    innermost = outermost.enter_subquery((Order,)).enter_subquery((Unrelated,))

    assert_eq(innermost.own_models, (Unrelated,))
    assert_eq(innermost.outer_models, (Order, User))


@test(mark="fast")
def own_and_outer_columns_are_in_scope() -> None:
    """A column of an own or enclosing table passes the scope check."""

    scope = ScopeResolver(own_models=(Order,), outer_models=(User,))

    scope.ensure_operand_in_scope(
        Order.amount,
        clause="predicate",
        error=QueryConstructionError,
    )
    scope.ensure_operand_in_scope(
        User.id,
        clause="predicate",
        error=QueryConstructionError,
    )


@test(mark="fast")
def foreign_column_is_rejected_with_the_clause_message() -> None:
    """An out-of-scope column raises the caller's error naming its clause."""

    scope = ScopeResolver(own_models=(User,))

    with assert_raises(QueryConstructionError) as caught:
        scope.ensure_operand_in_scope(
            Unrelated.id,
            clause="predicate",
            error=QueryConstructionError,
        )

    assert_eq(
        str(caught.exception),
        "predicate references a table that is not in the query",
    )


@test(mark="fast")
def error_class_is_caller_chosen() -> None:
    """Compile-time callers get compilation errors from the same mechanism."""

    scope = ScopeResolver(own_models=(User,))

    with assert_raises(QueryCompilationError) as caught:
        scope.ensure_operand_in_scope(
            Unrelated.id,
            clause="comparison",
            error=QueryCompilationError,
        )

    assert_eq(
        str(caught.exception),
        "comparison references a table that is not in the query",
    )


@test(mark="fast")
def own_only_rejects_an_outer_column() -> None:
    """A projection may not reach into the enclosing query's tables."""

    scope = ScopeResolver(own_models=(Order,), outer_models=(User,))

    scope.ensure_operand_in_scope(
        Order.amount,
        clause="select",
        error=QueryCompilationError,
        own_only=True,
    )
    with assert_raises(QueryCompilationError) as caught:
        scope.ensure_operand_in_scope(
            User.id,
            clause="select",
            error=QueryCompilationError,
            own_only=True,
        )

    assert_eq(
        str(caught.exception),
        "select references a table that is not in the query",
    )


@test(mark="fast")
def aggregate_operands_scope_check_through_their_owner() -> None:
    """An aggregate is checked against the table it aggregates over."""

    scope = ScopeResolver(own_models=(User,))

    scope.ensure_operand_in_scope(
        User.id.count(),
        clause="having",
        error=QueryConstructionError,
    )
    with assert_raises(QueryConstructionError):
        scope.ensure_operand_in_scope(
            Order.amount.sum(),
            clause="having",
            error=QueryConstructionError,
        )


@test(mark="fast")
def dialect_leaf_operands_scope_check_through_owner_model() -> None:
    """A dialect expression names its own table via ``__owner_model__``."""

    scope = ScopeResolver(own_models=(User,))

    scope.ensure_operand_in_scope(
        _FakeDialectLeaf(User),
        clause="predicate",
        error=QueryConstructionError,
    )
    with assert_raises(QueryConstructionError):
        scope.ensure_operand_in_scope(
            _FakeDialectLeaf(Order),
            clause="predicate",
            error=QueryConstructionError,
        )


@test(mark="fast")
def non_column_operand_is_rejected() -> None:
    """A value that is no operand kind at all fails as a construction error."""

    scope = ScopeResolver(own_models=(User,))

    with assert_raises(QueryConstructionError):
        scope.ensure_operand_in_scope(
            "not a column",
            clause="predicate",
            error=QueryConstructionError,
        )

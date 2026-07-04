"""Query scope resolution: which tables an operand may reference (#226).

One :class:`ScopeResolver` answers "is this operand's table in scope" for every
operand kind -- a bound column, an aggregate, or an open-AST dialect leaf --
so the answer no longer depends on which validator happened to run. The
resolver is built from query state (the statement's own tables plus any
enclosing query's, for correlated subqueries) and also owns the qualification
decision that follows from the same facts.

The clause-level validators (where/having/order_by/group_by/set) live here too:
they are scope *policy* -- which operand kinds a clause admits -- expressed over
the resolver's single membership check. ``_query_state`` keeps the state
dataclasses and ownership accessors and never imports this module; the Query
Builder and Query Compilation import downward into it.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, cast

from snekql._dialect_expr import SqlCompilable
from snekql._query_state import (
    SelectState,
    require_column_model,
    require_column_name,
    require_field,
    require_selectable,
    require_single_column_subquery,
    require_subquery_state,
    selectable_owner_model,
)
from snekql.errors import (
    QueryCompilationError,
    QueryConstructionError,
    QueryError,
)
from snekql.expressions import Aggregate, Assignment, OrderBy, Predicate
from snekql.model import Table
from snekql.storage import Attr


@dataclass(frozen=True)
class ScopeResolver:
    """The tables a statement's operands may reference, and how they render.

    ``own_models`` are the statement's own tables (base model plus joins, in
    join order); ``outer_models`` are every enclosing query's tables when the
    statement compiles as a correlated subquery. Both scope membership and
    column qualification derive from these two facts, so they can never
    disagree.
    """

    own_models: tuple[type[Table[Any]], ...]
    outer_models: tuple[type[Table[Any]], ...] = ()

    @property
    def models(self) -> tuple[type[Table[Any]], ...]:
        """Every table an operand may reference: own first, then enclosing."""

        return (*self.own_models, *self.outer_models)

    @property
    def qualified(self) -> bool:
        """Whether column references must be table-qualified.

        A joined statement qualifies so identically named columns from
        different tables never collide; a subquery qualifies so an inner
        reference never captures an identically named outer column.
        """

        return len(self.own_models) > 1 or bool(self.outer_models)

    def enter_subquery(
        self,
        inner_own: tuple[type[Table[Any]], ...],
    ) -> ScopeResolver:
        """Build the scope a nested subquery compiles under.

        The subquery's own tables shadow nothing: everything visible here --
        own and outer alike -- stays reachable as its outer scope, which is
        what lets a doubly nested subquery correlate all the way out.
        """

        return ScopeResolver(own_models=inner_own, outer_models=self.models)

    def ensure_operand_in_scope(
        self,
        operand: object,
        *,
        clause: str,
        error: type[QueryError],
        own_only: bool = False,
    ) -> None:
        """Check an operand's owning table is reachable in this scope.

        ``clause`` names the SQL clause for the error message; ``error`` is the
        error class the calling phase raises (construction vs compilation);
        ``own_only`` restricts to the statement's own tables (a projection may
        not reach into the enclosing query).

        A plain column is by far the common operand, so the concrete ``Attr``
        is tested before the structural ``SqlCompilable`` protocol check (an
        attribute-walking runtime-checkable ``isinstance``). ``Attr`` is
        disjoint from the ``Aggregate`` and dialect-leaf branches, so the order
        never changes which branch a value takes.
        """

        models = self.own_models if own_only else self.models
        out_of_scope = f"{clause} references a table that is not in the query"
        if isinstance(operand, Attr):
            bound = cast("Attr[Any, Any, Any, Any, Any]", operand)
            if require_column_model(bound) not in models:
                raise error(out_of_scope)
            return
        if isinstance(operand, Aggregate):
            aggregate = cast("Aggregate[Any, Any]", operand)
            if selectable_owner_model(aggregate) not in models:
                raise error(out_of_scope)
            return
        if isinstance(operand, SqlCompilable):
            if operand.__owner_model__() not in models:
                raise error(out_of_scope)
            return
        bare_column = require_field(operand)
        if require_column_model(bare_column) not in models:
            raise error(out_of_scope)


def ensure_predicate_targets_models(
    predicate: Predicate[Any],
    scope: ScopeResolver,
) -> None:
    """Validate a where() predicate tree's operands against the scope.

    The traversal is node-name-blind: it walks the structural surface every
    predicate node exposes (operand, children, and nested select plus its
    arity), so adding a predicate kind never touches this validator.
    """

    arity = predicate.__predicate_subquery_arity__
    if arity == "select":
        # EXISTS carries no outer column; correlation to the outer scope is
        # resolved when the subquery compiles, not at construction.
        _ = require_subquery_state(predicate.__predicate_subquery__())
        return
    if arity == "single_column":
        _ = require_single_column_subquery(predicate.__predicate_subquery__())
    operand = predicate.__predicate_operand__()
    if operand is not None:
        if isinstance(operand, Aggregate):
            msg = "aggregates cannot appear in where(); use having()"
            raise QueryConstructionError(msg)
        scope.ensure_operand_in_scope(
            operand,
            clause="predicate",
            error=QueryConstructionError,
        )
    for child in predicate.__predicate_children__():
        ensure_predicate_targets_models(child, scope)


def ensure_having_targets(
    predicate: Predicate[Any],
    state: SelectState,
    scope: ScopeResolver,
) -> None:
    """Validate that a HAVING predicate targets only aggregates or grouped columns.

    SQL allows ``HAVING`` to reference the per-group aggregates and the grouping
    keys, never an ungrouped bare column. Aggregates carry their owner directly;
    a plain column must appear in ``group_by`` (and, like ``where``, name a table
    already in scope).
    """

    operand = predicate.__predicate_operand__()
    if operand is not None:
        ensure_having_selectable(operand, state, scope)
    for child in predicate.__predicate_children__():
        ensure_having_targets(child, state, scope)


def ensure_having_selectable(
    column: object,
    state: SelectState,
    scope: ScopeResolver,
) -> None:
    """Validate one HAVING operand: in scope, and grouped unless aggregated."""

    selectable = require_selectable(column)
    scope.ensure_operand_in_scope(
        selectable,
        clause="having",
        error=QueryConstructionError,
    )
    if isinstance(selectable, Aggregate):
        return
    bare_column = require_field(column)
    grouped_keys = {
        (require_column_model(grouped), require_column_name(grouped))
        for grouped in state.groupings
    }
    key = (require_column_model(bare_column), require_column_name(bare_column))
    if key not in grouped_keys:
        msg = "having references a column that is not grouped or aggregated"
        raise QueryConstructionError(msg)


def ensure_ordering_targets_models(
    ordering: OrderBy[Any],
    scope: ScopeResolver,
) -> None:
    """Validate an order_by() entry against the statement's own tables.

    An ordering may only target the statement's own tables -- never an
    enclosing query's -- so the check is ``own_only`` and holds unchanged when
    the compiler re-runs it for a correlated subquery.
    """

    if ordering.column is None or ordering.direction not in {"ASC", "DESC"}:
        msg = "orderings must be built from columns"
        raise QueryConstructionError(msg)
    selectable = require_selectable(ordering.column)
    scope.ensure_operand_in_scope(
        selectable,
        clause="ordering",
        error=QueryConstructionError,
        own_only=True,
    )


def ensure_grouping_targets_models(
    columns: tuple[Attr[Any, Any, Any, Any, Any], ...],
    scope: ScopeResolver,
) -> None:
    """Validate that every group_by() column names a table in scope."""

    for column in columns:
        scope.ensure_operand_in_scope(
            column,
            clause="group_by",
            error=QueryConstructionError,
        )


def ensure_grouping_covers_projection(state: SelectState) -> None:
    """Reject an aggregated projection that selects an ungrouped bare column.

    A query is aggregated when it projects an aggregate or carries a
    ``group_by``; in either case SQL requires every non-aggregate projected
    column to appear in the ``GROUP BY`` list. ``COUNT(*)``-style aggregates have
    no column, so they never need grouping.
    """

    has_aggregate = any(isinstance(field, Aggregate) for field in state.fields)
    if not (has_aggregate or state.groupings):
        return
    grouped_keys = {
        (require_column_model(column), require_column_name(column))
        for column in state.groupings
    }
    for field in state.fields:
        # Only a bare column must appear in GROUP BY; aggregates, scalar
        # subqueries, and open-AST dialect expressions are not plain columns.
        if not isinstance(field, Attr):
            continue
        key = (require_column_model(field), require_column_name(field))
        if key not in grouped_keys:
            msg = "non-aggregated column in an aggregated select must appear in group_by()"
            raise QueryCompilationError(msg)


def ensure_assignment_targets_model(
    assignment: Assignment[Any],
    scope: ScopeResolver,
) -> None:
    """Validate that a set() assignment targets the updated table."""

    if assignment.column is None:
        msg = "assignments must be built from columns"
        raise QueryConstructionError(msg)
    column = require_field(assignment.column)
    scope.ensure_operand_in_scope(
        column,
        clause="assignment",
        error=QueryConstructionError,
    )

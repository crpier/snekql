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

from snekql._aliases import _AliasRelation
from snekql._cte import _CteOutput, _CteRelation
from snekql._dialect_expr import ReferencedColumns, SqlCompilable
from snekql._literal import _IntegerLiteral
from snekql._query_sources import grouping_key
from snekql._query_state import (
    SelectState,
    require_column_model,
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
from snekql.expressions import (
    _Aggregate,
    _Assignment,
    _OrderBy,
    _PredicateNode,
    _require_predicate_node,
    _Scalar,
)
from snekql.model import Table, require_model_backend, require_model_table_name
from snekql.storage import Attr


def _query_owner_identity(
    model: type[Table[Any]], identities: dict[type[Table[Any]], object]
) -> object:
    """Resolve each source once per scope, preserving shared owner coordinates."""
    if model in identities:
        return identities[model]
    if issubclass(model, _AliasRelation):
        identity = (_AliasRelation, model.source_model, model.role)
    elif issubclass(model, _CteRelation):
        sources = frozenset(
            _query_owner_identity(source, identities)
            for source in model.definition.state.result_models()
        )
        identity = (_CteRelation, sources, model.role)
    else:
        identities[model] = model
        return model
    identities[model] = identity
    return identity


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

    def ensure_unambiguous_aliases(self) -> None:
        """Reject SQL shadowing and indistinguishable role types in visible scopes."""
        names: dict[str, type[Table[Any]]] = {}
        roles: set[tuple[type[Table[Any]], type[object]]] = set()
        cte_roles: set[object] = set()
        identities: dict[type[Table[Any]], object] = {}
        for model in self.models:
            name = require_model_table_name(model).casefold()
            previous = names.get(name)
            if previous is not None and (
                previous is not model
                or issubclass(model, (_AliasRelation, _CteRelation))
                or issubclass(previous, (_AliasRelation, _CteRelation))
            ):
                msg = "query source name collides with a visible query source"
                raise QueryCompilationError(msg)
            names[name] = model
            if issubclass(model, _AliasRelation):
                role = (model.source_model, model.role)
                if role in roles:
                    msg = "alias role is already visible in this query scope"
                    raise QueryCompilationError(msg)
                roles.add(role)
            if issubclass(model, _CteRelation):
                cte_role = _query_owner_identity(model, identities)
                if cte_role in cte_roles:
                    msg = "CTE role is already visible in this query scope"
                    raise QueryCompilationError(msg)
                cte_roles.add(cte_role)

    def enter_subquery(
        self,
        inner_own: tuple[type[Table[Any]], ...],
    ) -> ScopeResolver:
        """Build the scope a nested subquery compiles under.

        The subquery's own tables shadow nothing: everything visible here --
        own and outer alike -- stays reachable as its outer scope, which is
        what lets a doubly nested subquery correlate all the way out.
        """

        families = {
            require_model_backend(model) for model in (*inner_own, *self.models)
        }
        if len(families) > 1:
            msg = "subquery backend differs from the enclosing query"
            raise QueryCompilationError(msg)
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
        if isinstance(operand, _IntegerLiteral):
            if not models or any(
                require_model_backend(model) != operand.backend for model in models
            ):
                msg = "literal backend differs from the query"
                raise error(msg)
            return
        out_of_scope = f"{clause} references a table that is not in the query"
        if isinstance(operand, Attr):
            bound = cast("Attr[Any, Any, Any, Any, Any]", operand)
            if require_column_model(bound) not in models:
                raise error(out_of_scope)
            return
        if isinstance(operand, _Aggregate):
            aggregate = cast("_Aggregate[Any, Any]", operand)
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
    predicate: _PredicateNode[Any],
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
        if isinstance(operand, _Aggregate):
            msg = "aggregates cannot appear in where(); use having()"
            raise QueryConstructionError(msg)
        scope.ensure_operand_in_scope(
            operand,
            clause="predicate",
            error=QueryConstructionError,
        )
    for child in predicate.__predicate_children__():
        ensure_predicate_targets_models(_require_predicate_node(child), scope)


def ensure_having_targets(
    predicate: _PredicateNode[Any],
    state: SelectState,
    scope: ScopeResolver,
) -> None:
    """Validate that a HAVING predicate targets only aggregates or grouped columns.

    SQL allows ``HAVING`` to reference the per-group aggregates and the grouping
    keys, never an ungrouped bare column. Aggregates carry their owner directly;
    a plain column must appear in ``group_by`` (and, like ``where``, name a table
    already in scope).
    """

    for operand in predicate.__predicate_grouping_operands__():
        ensure_having_selectable(operand, state, scope)
    for child in predicate.__predicate_children__():
        ensure_having_targets(_require_predicate_node(child), state, scope)


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
    if isinstance(selectable, _Aggregate):
        return
    grouped_keys = {grouping_key(grouped) for grouped in state.groupings}
    key = grouping_key(column)
    if key not in grouped_keys:
        msg = "having references a column that is not grouped or aggregated"
        raise QueryConstructionError(msg)


def ensure_ordering_targets_models(
    ordering: _OrderBy[Any],
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
    columns: tuple[Attr[Any, Any, Any, Any, Any] | SqlCompilable, ...],
    scope: ScopeResolver,
) -> None:
    """Validate that every group_by() column names a table in scope."""

    for column in columns:
        scope.ensure_operand_in_scope(
            column,
            clause="group_by",
            error=QueryConstructionError,
        )


def _correlated_columns(  # noqa: C901 - traverse operands and predicates across nested SQL scopes
    state: SelectState,
    bound_models: frozenset[type[Table[Any]]] = frozenset(),
) -> tuple[object, ...]:
    """Find free column reads without confusing inner rows with outer group keys."""
    bound_models = bound_models.union(state.result_models())
    columns: list[object] = []

    def read_operand(operand: object) -> None:
        if isinstance(operand, (Attr, _CteOutput)):
            if selectable_owner_model(operand) not in bound_models:
                columns.append(operand)
        elif isinstance(operand, ReferencedColumns):
            for referenced in operand.__referenced_columns__():
                read_operand(referenced)
        elif isinstance(operand, _Scalar):
            columns.extend(
                _correlated_columns(
                    require_subquery_state(operand.subquery), bound_models
                )
            )

    def read_predicate(predicate: _PredicateNode[Any]) -> None:
        for operand in predicate.__predicate_grouping_operands__():
            read_operand(operand)
        for nested in predicate.__predicate_nested_selects__():
            columns.extend(
                _correlated_columns(require_subquery_state(nested), bound_models)
            )
        for child in predicate.__predicate_children__():
            read_predicate(_require_predicate_node(child))

    for operand in (
        *state.fields,
        *state.groupings,
        *(entry.column for entry in state.orderings),
    ):
        read_operand(operand)
    for predicate in (
        *state.predicates,
        *state.having,
        *(join.predicate for join in state.joins),
    ):
        read_predicate(predicate)
    if state.compound is not None:
        columns.extend(_correlated_columns(state.compound.left, bound_models))
        columns.extend(_correlated_columns(state.compound.right, bound_models))
    return tuple(columns)


def ensure_grouping_covers_projection(state: SelectState) -> None:
    """Reject an aggregated projection that selects an ungrouped bare column.

    Grouping, HAVING, and aggregates in SELECT or ORDER BY require every
    non-aggregate projected column to appear in GROUP BY. Aggregate context
    cannot be hidden in a different clause to expose an arbitrary input row.
    """

    has_aggregate = any(isinstance(field, _Aggregate) for field in state.fields) or any(
        isinstance(ordering.column, _Aggregate) for ordering in state.orderings
    )
    if not (has_aggregate or state.groupings or state.having):
        return
    grouped_keys = {grouping_key(column) for column in state.groupings}
    inputs: list[object] = []
    for field in (*state.fields, *(ordering.column for ordering in state.orderings)):
        if isinstance(field, ReferencedColumns):
            inputs.extend(field.__referenced_columns__())
        elif isinstance(field, (Attr, _CteOutput)):
            inputs.append(field)
        elif isinstance(field, _Scalar):
            inputs.extend(_correlated_columns(require_subquery_state(field.subquery)))
    predicates = list(state.having)
    while predicates:
        predicate = predicates.pop()
        for nested in predicate.__predicate_nested_selects__():
            inputs.extend(_correlated_columns(require_subquery_state(nested)))
        predicates.extend(
            _require_predicate_node(child)
            for child in predicate.__predicate_children__()
        )
    for operand in inputs:
        # A free reference to an enclosing query is constant within this local
        # group. Its own enclosing grouping boundary checks it instead.
        key = grouping_key(operand)
        if key[0] in state.result_models() and key not in grouped_keys:
            msg = "non-aggregated column in SELECT, HAVING or ORDER BY must appear in group_by()"
            raise QueryCompilationError(msg)


def ensure_assignment_targets_model(
    assignment: _Assignment[Any],
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

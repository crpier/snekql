"""Query Compilation: lower built query state into backend Dialect SQL.

The write/emit counterpart to materialization. Every function here operates on
query state plus a :class:`QueryDialect`; nothing in this module knows about the
Query Builder classes, so the dependency points one way (builder -> state <-
compilation).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, cast

from snekql._aliases import _AliasRelation
from snekql._compiled import CompiledQuery
from snekql._cte import _CteOutput, _CteRelation
from snekql._cte_graph import collect_cte_definitions
from snekql._dialect_expr import CompileCtx, DialectSelectable, SqlCompilable
from snekql._named_projection import NamedProjection
from snekql._query_dialect import QueryDialect, query_dialect_for_backend
from snekql._query_scope import (
    ScopeResolver,
    ensure_assignment_targets_model,
    ensure_grouping_covers_projection,
    ensure_having_targets,
    ensure_ordering_targets_models,
)
from snekql._query_state import (
    DeleteState,
    InsertState,
    Selectable,
    SelectState,
    UpdateState,
    require_column_model,
    require_column_name,
    require_field,
    require_insert_model,
    require_selectable,
    require_single_column_subquery,
    require_subquery_state,
)
from snekql._value_encode import _predicate_value_encoder
from snekql._value_expression import ValueExpression
from snekql.errors import QueryCompilationError
from snekql.expressions import (
    DoNothing,
    DoUpdate,
    InsertedValue,
    Predicate,
    _Aggregate,
    _OrderBy,
    _Scalar,
)
from snekql.model import (
    Table,
    require_model_backend,
    require_model_columns,
    require_model_table_name,
)
from snekql.storage import PENDING_GENERATION, Attr, CurrentTimestamp


def _render_column_ref(
    column: Attr[Any, Any, Any, Any, Any],
    dialect: QueryDialect,
    *,
    qualified: bool = False,
) -> str:
    """Render a column as the SQL reference used in compiled statements.

    Every column-name emission (predicates, orderings, assignments, and the
    select list) routes through this single seam so the qualification strategy
    lives in one place. Single-table statements render a bare dialect-quoted
    column name; joined statements qualify it with the owning table so columns
    from different tables never collide.
    """

    quoted_name = dialect.quote_identifier(require_column_name(column))
    if not qualified:
        return quoted_name
    table_name = require_model_table_name(require_column_model(column))
    return f"{dialect.quote_identifier(table_name)}.{quoted_name}"


def _render_aggregate(
    aggregate: _Aggregate[Any, Any],
    dialect: QueryDialect,
    *,
    qualified: bool,
) -> str:
    """Render an aggregate as ``FUNC(col)`` or ``COUNT(*)`` for the select list."""

    column = aggregate.column
    if column is None:
        return f"{aggregate.func}(*)"
    column_ref = _render_grouping_column(column, dialect, qualified=qualified)
    return f"{aggregate.func}({column_ref})"


def _render_grouping_column(
    column: object, dialect: QueryDialect, *, qualified: bool
) -> str:
    """Column references carry no bindings, whether physical or derived."""
    if isinstance(column, _CteOutput):
        sql, _ = column.__compile_sql__(_make_compile_ctx(dialect, qualified=qualified))
        return sql
    return _render_column_ref(require_field(column), dialect, qualified=qualified)


def _make_compile_ctx(
    dialect: QueryDialect, *, qualified: bool, scope: ScopeResolver | None = None
) -> CompileCtx:
    """Build the facts a dialect expression renders itself against.

    ``render_column`` closes over the enclosing statement's qualification so an
    expression's owned columns quote and qualify exactly like every other column
    reference, without the leaf reimplementing that strategy.
    """

    return CompileCtx(
        compile_predicate=_PredicateCompileContext(dialect=dialect, scope=scope).compile
        if scope is not None
        else None,
        char_length_function=dialect.char_length_function,
        placeholder=dialect.placeholder,
        quote_identifier=dialect.quote_identifier,
        render_column=lambda column: _render_grouping_column(
            column,
            dialect,
            qualified=qualified,
        ),
    )


def _render_selectable(
    field: Selectable,
    dialect: QueryDialect,
    *,
    qualified: bool,
    projection: bool = False,
    scope: ScopeResolver | None = None,
) -> tuple[str, tuple[object, ...]]:
    if isinstance(field, _Scalar):
        # Scalar subqueries carry nested parameters, so the select-list compiler
        # renders them through `_compile_scalar_sql`; they never reach here.
        msg = "scalar subqueries cannot be rendered without their parameters"
        raise QueryCompilationError(msg)
    if isinstance(field, _Aggregate):
        return _render_aggregate(field, dialect, qualified=qualified), ()
    if isinstance(field, SqlCompilable):
        # Open-AST dialect expression: the core renders it structurally through
        # the protocol, never naming the leaf. A projection uses the select seam
        # (`__compile_select_sql__`); an operand uses the operand seam.
        ctx = _make_compile_ctx(dialect, qualified=qualified, scope=scope)
        if projection and isinstance(field, DialectSelectable):
            return field.__compile_select_sql__(ctx)
        return field.__compile_sql__(ctx)
    return _render_column_ref(field, dialect, qualified=qualified), ()


def _compile_scalar_sql(
    scalar_subquery: _Scalar[Any, Any, Any],
    dialect: QueryDialect,
    *,
    scope: ScopeResolver,
) -> tuple[str, tuple[object, ...]]:
    """Compile a scalar subquery as a parenthesized correlated select."""

    state = require_single_column_subquery(scalar_subquery.subquery)
    sub_sql, sub_params = _compile_select_state(state, dialect, outer=scope)
    return f"({sub_sql})", sub_params


@dataclass(frozen=True)
class _PredicateCompileContext:
    """The concrete ``PredicateCompiler`` Query Compilation hands each node.

    Wraps the statement's ``(dialect, scope)`` pair behind the structural seam
    predicate nodes compile themselves against, reusing the module's existing
    rendering/encoding helpers so a node never learns about dialects or scope
    resolution directly (the built-in counterpart to ADR 0004's ``CompileCtx``).
    """

    dialect: QueryDialect
    scope: ScopeResolver

    @property
    def placeholder(self) -> str:
        return self.dialect.placeholder

    def render_operand(self, operand: object) -> tuple[str, tuple[object, ...]]:
        """Render a predicate operand and its ordered bound values."""

        return _render_selectable(
            require_selectable(operand),
            self.dialect,
            qualified=self.scope.qualified,
            scope=self.scope,
        )

    def value_encoder(self, operand: object) -> Callable[[object], object]:
        """Build the comparison-value encoder for a predicate operand."""

        return _predicate_value_encoder(require_selectable(operand), self.dialect)

    def render_comparison_operand(
        self, other: object
    ) -> tuple[str, tuple[object, ...]]:
        """Render the column or expression on the right of a `*_col` comparison.

        The column's table must be reachable in the current scope (the
        statement's own tables plus any enclosing query the subquery
        correlates to), else the reference is rejected at compile time.
        """

        operand = (
            require_selectable(other)
            if isinstance(other, SqlCompilable)
            else require_field(other)
        )
        self.scope.ensure_operand_in_scope(
            operand,
            clause="comparison",
            error=QueryCompilationError,
        )
        return _render_selectable(
            operand, self.dialect, qualified=self.scope.qualified, scope=self.scope
        )

    def compile_scalar(self, scalar: object) -> tuple[str, tuple[object, ...]]:
        """Compile a scalar-subquery operand as a parenthesized select."""

        return _compile_scalar_sql(
            cast("_Scalar[Any, Any, Any]", scalar),
            self.dialect,
            scope=self.scope,
        )

    def compile_subquery(
        self,
        subquery: object,
        *,
        single_column: bool,
    ) -> tuple[str, tuple[object, ...]]:
        """Compile a nested select, layering this statement's scope as outer."""

        state = (
            require_single_column_subquery(subquery)
            if single_column
            else require_subquery_state(subquery)
        )
        return _compile_select_state(state, self.dialect, outer=self.scope)

    def compile(self, predicate: Predicate[Any]) -> tuple[str, tuple[object, ...]]:
        """Compile a nested predicate (a compound/negated node's child)."""

        return predicate.__compile_predicate_sql__(self)


def _compile_predicate_sql(
    predicate: Predicate[Any],
    dialect: QueryDialect,
    *,
    scope: ScopeResolver,
) -> tuple[str, tuple[object, ...]]:
    context = _PredicateCompileContext(dialect=dialect, scope=scope)
    return predicate.__compile_predicate_sql__(context)


def _compile_group_by_sql(
    state: SelectState,
    dialect: QueryDialect,
    *,
    qualified: bool,
) -> str:
    group_by = ", ".join(
        _render_grouping_column(column, dialect, qualified=qualified)
        for column in state.groupings
    )
    return f"GROUP BY {group_by}"


def _compile_ordering_sql(
    ordering: _OrderBy[Any],
    scope: ScopeResolver,
    dialect: QueryDialect,
) -> str:
    ensure_ordering_targets_models(ordering, scope)
    selectable = require_selectable(ordering.column)
    column_name, params = _render_selectable(
        selectable, dialect, qualified=scope.qualified, scope=scope
    )
    if params:
        msg = "dialect expressions with bound values cannot be used for ordering"
        raise QueryCompilationError(msg)
    return f"{column_name} {ordering.direction}"


def _compile_predicates_sql(
    predicates: tuple[Predicate[Any], ...],
    dialect: QueryDialect,
    *,
    scope: ScopeResolver,
) -> tuple[str, tuple[object, ...]]:
    predicate_sql_parts: list[str] = []
    predicate_params: list[object] = []
    for predicate in predicates:
        predicate_sql, compiled_params = _compile_predicate_sql(
            predicate,
            dialect,
            scope=scope,
        )
        predicate_sql_parts.append(f"({predicate_sql})")
        predicate_params.extend(compiled_params)
    return " AND ".join(predicate_sql_parts), tuple(predicate_params)


def _encode_insert_row(
    row: object,
    model_class: type[Table[Any]],
    dialect: QueryDialect,
) -> dict[str, object]:
    row_model = require_insert_model(row)
    if row_model is not model_class:
        msg = "bulk insert rows must be instances of the same model"
        raise QueryCompilationError(msg)
    row_values: dict[str, object] = {}
    for name, column in require_model_columns(model_class).items():
        value = getattr(row, name)
        if value is PENDING_GENERATION:
            continue
        row_values[name] = dialect.encode_column_value(column, value)
    return row_values


def _returning_clause(
    model_class: type[Table[Any]],
    fields: tuple[Selectable, ...],
    dialect: QueryDialect,
    projection: NamedProjection | None = None,
) -> str:
    # An explicit projection lists only the named columns; otherwise RETURNING
    # spans every column so the row decodes back into a full Row model.
    if fields:
        names: tuple[str, ...] = tuple(
            require_column_name(require_field(field)) for field in fields
        )
    else:
        names = tuple(require_model_columns(model_class))
    parts = [dialect.quote_identifier(name) for name in names]
    if projection is not None:
        if len(parts) != len(projection.labels):
            msg = "named returning width does not match its labels"
            raise QueryCompilationError(msg)
        parts = [
            f"{sql} AS {dialect.quote_identifier(label)}"
            for sql, label in zip(parts, projection.labels, strict=True)
        ]
    rendered = ", ".join(parts)
    return f" RETURNING {rendered}"


def _compile_insert_conflict_sql(
    state: InsertState,
    model_class: type[Table[Any]],
    dialect: QueryDialect,
) -> tuple[str, tuple[object, ...]]:
    """Compile an insert's optional conflict action and assignment parameters."""

    action = state.conflict_action
    if action is None:
        return "", ()
    quoted_targets = tuple(
        _render_column_ref(target, dialect) for target in state.conflict_targets
    )
    if action is DoNothing:
        if state.returning:
            msg = "DoNothing cannot be combined with returning()"
            raise QueryCompilationError(msg)
        return dialect.conflict_do_nothing_sql(quoted_targets), ()
    if not isinstance(action, DoUpdate):
        msg = "unsupported insert conflict action"
        raise QueryCompilationError(msg)
    scope = ScopeResolver(own_models=(model_class,))
    set_sql_parts: list[str] = []
    params: tuple[object, ...] = ()
    for assignment in action.assignments:
        if isinstance(assignment.value, ValueExpression):
            msg = "expression assignments are only supported in UPDATE"
            raise QueryCompilationError(msg)
        ensure_assignment_targets_model(assignment, scope)
        column = require_field(assignment.column)
        column_name = _render_column_ref(column, dialect)
        if assignment.value is InsertedValue:
            assigned_value = dialect.inserted_value_sql(column_name)
        elif assignment.value is CurrentTimestamp:
            assigned_value = dialect.current_timestamp_sql
        else:
            assigned_value = dialect.placeholder
            params = (*params, dialect.encode_column_value(column, assignment.value))
        set_sql_parts.append(f"{column_name} = {assigned_value}")
    return (
        dialect.conflict_update_sql(quoted_targets, ", ".join(set_sql_parts)),
        params,
    )


def _compile_insert_sql(
    state: InsertState,
    dialect: QueryDialect,
) -> tuple[str, tuple[object, ...]]:
    model_class = state.model()
    if model_class is None or not state.rows:
        msg = "insert requires at least one row"
        raise QueryCompilationError(msg)
    encoded_rows = [_encode_insert_row(row, model_class, dialect) for row in state.rows]
    # Every row in a bulk insert shares one VALUES list, so the present-column
    # set must be identical across rows; otherwise the flattened parameters
    # would not line up with a single column list.
    names = tuple(encoded_rows[0])
    for row_values in encoded_rows[1:]:
        if tuple(row_values) != names:
            msg = "bulk insert rows must set the same columns"
            raise QueryCompilationError(msg)
    table_name = require_model_table_name(model_class)
    quoted_table = dialect.quote_identifier(table_name)
    returning = (
        _returning_clause(
            model_class, state.returning_fields, dialect, state.named_projection
        )
        if state.returning
        else ""
    )
    if not names:
        if len(encoded_rows) > 1:
            msg = "bulk insert requires at least one explicit column"
            raise QueryCompilationError(msg)
        if state.conflict_action is not None:
            msg = "on_conflict requires at least one explicit insert column"
            raise QueryCompilationError(msg)
        return dialect.empty_insert_sql(quoted_table) + returning, ()
    quoted_columns = ", ".join(dialect.quote_identifier(name) for name in names)
    row_placeholder = "(" + ", ".join(dialect.placeholder for _ in names) + ")"
    values_clause = ", ".join(row_placeholder for _ in encoded_rows)
    params = tuple(row_values[name] for row_values in encoded_rows for name in names)
    conflict, conflict_params = _compile_insert_conflict_sql(
        state,
        model_class,
        dialect,
    )
    params = (*params, *conflict_params)
    sql = (
        "INSERT INTO "  # noqa: S608
        + quoted_table
        + f" ({quoted_columns}) VALUES {values_clause}{conflict}{returning}"
    )
    return sql, params


def _ensure_expression_assignment_dependencies(state: UpdateState) -> None:
    """Reject SET dependencies whose evaluation order differs between backends."""
    for assignment in state.assignments:
        if isinstance(assignment.value, ValueExpression) and any(
            other.column is referenced and other is not assignment
            for referenced in assignment.value.__referenced_columns__()
            for other in state.assignments
        ):
            msg = "expression cannot read another column assigned by this statement"
            raise QueryCompilationError(msg)


def _compile_update_sql(
    state: UpdateState,
    dialect: QueryDialect,
) -> tuple[str, tuple[object, ...]]:
    if not state.assignments:
        msg = "update requires set() before execution"
        raise QueryCompilationError(msg)
    if not state.explicit_all and not state.predicates:
        msg = "update requires all() or where() before execution"
        raise QueryCompilationError(msg)
    _ensure_expression_assignment_dependencies(state)
    table_name = require_model_table_name(state.model)
    scope = ScopeResolver(own_models=(state.model,))
    set_sql_parts: list[str] = []
    params: tuple[object, ...] = ()
    for assignment in state.assignments:
        ensure_assignment_targets_model(assignment, scope)
        column = require_field(assignment.column)
        column_name = _render_column_ref(column, dialect)
        if assignment.value is InsertedValue:
            msg = "to_inserted() is only valid in a conflict update"
            raise QueryCompilationError(msg)
        if isinstance(assignment.value, ValueExpression):
            expression_sql, expression_params = assignment.value.__compile_sql__(
                _make_compile_ctx(dialect, qualified=False, scope=scope)
            )
            set_sql_parts.append(f"{column_name} = {expression_sql}")
            params = (*params, *expression_params)
            continue
        if assignment.value is CurrentTimestamp:
            set_sql_parts.append(f"{column_name} = {dialect.current_timestamp_sql}")
            continue
        set_sql_parts.append(f"{column_name} = {dialect.placeholder}")
        params = (*params, dialect.encode_column_value(column, assignment.value))
    sql_parts = [
        "UPDATE " + dialect.quote_identifier(table_name) + " SET ",  # noqa: S608
        ", ".join(set_sql_parts),
    ]
    if state.predicates:
        predicate_sql, predicate_params = _compile_predicates_sql(
            state.predicates,
            dialect,
            scope=scope,
        )
        sql_parts.append(f" WHERE {predicate_sql}")
        params = (*params, *predicate_params)
    if state.returning:
        if not dialect.supports_update_returning:
            msg = "backend does not support UPDATE RETURNING"
            raise QueryCompilationError(msg)
        sql_parts.append(
            _returning_clause(
                state.model, state.returning_fields, dialect, state.named_projection
            )
        )
    return "".join(sql_parts), params


def _compile_delete_sql(
    state: DeleteState,
    dialect: QueryDialect,
) -> tuple[str, tuple[object, ...]]:
    if not state.explicit_all and not state.predicates:
        msg = "delete requires all() or where() before execution"
        raise QueryCompilationError(msg)
    table_name = require_model_table_name(state.model)
    sql = "DELETE FROM " + dialect.quote_identifier(table_name)  # noqa: S608
    params: tuple[object, ...] = ()
    if state.predicates:
        predicate_sql, params = _compile_predicates_sql(
            state.predicates,
            dialect,
            scope=ScopeResolver(own_models=(state.model,)),
        )
        sql = f"{sql} WHERE {predicate_sql}"
    if state.returning:
        if not dialect.supports_delete_returning:
            msg = "backend does not support DELETE RETURNING"
            raise QueryCompilationError(msg)
        sql = f"{sql}{_returning_clause(state.model, state.returning_fields, dialect, state.named_projection)}"
    return sql, params


def _compile_select_list(
    state: SelectState,
    dialect: QueryDialect,
    *,
    scope: ScopeResolver,
    presence_name: str | None = None,
) -> tuple[str, tuple[object, ...]]:
    """Render the projected columns, collecting any scalar-subquery parameters.

    A scalar subquery in the select list carries its own placeholders, so the
    list -- not just the ``WHERE`` clause -- can contribute parameters; they come
    first in textual order, which is exactly the order returned here.
    """

    parts: list[str] = []
    params: tuple[object, ...] = ()
    for field in state.fields:
        if isinstance(field, _Scalar):
            scalar_sql, scalar_params = _compile_scalar_sql(
                field,
                dialect,
                scope=scope,
            )
            parts.append(scalar_sql)
            params = (*params, *scalar_params)
            continue
        field_sql, field_params = _render_selectable(
            field,
            dialect,
            qualified=scope.qualified,
            projection=True,
            scope=scope,
        )
        parts.append(field_sql)
        params = (*params, *field_params)
    if state.named_projection is not None:
        labels = state.named_projection.labels
        if len(parts) != len(labels):
            msg = "named projection width does not match its labels"
            raise QueryCompilationError(msg)
        parts = [
            f"{sql} AS {dialect.quote_identifier(label)}"
            for sql, label in zip(parts, labels, strict=True)
        ]
    if presence_name is not None:
        parts.append(f"1 AS {dialect.quote_identifier(presence_name)}")
    return ", ".join(parts), params


def _compile_source_sql(model: type[Table[Any]], dialect: QueryDialect) -> str:
    """Render a physical table with its independent query-role name, if any."""
    name = dialect.quote_identifier(require_model_table_name(model))
    if issubclass(model, _CteRelation):
        definition = dialect.quote_identifier(model.definition.name)
        return definition if definition == name else f"{definition} AS {name}"
    if issubclass(model, _AliasRelation):
        physical = dialect.quote_identifier(
            require_model_table_name(model.source_model)
        )
        return f"{physical} AS {name}"
    return name


def _compile_locking_clause(
    state: SelectState,
    dialect: QueryDialect,
    *,
    nested: bool,
) -> tuple[str, ...]:
    """Limit locking to supported, top-level, single-source row selections."""
    if state.lock_wait is None:
        return ()
    if dialect.for_update_sql is None:
        msg = "FOR UPDATE is not supported by this dialect"
        raise QueryCompilationError(msg)
    if issubclass(state.model, _CteRelation):
        msg = "FOR UPDATE requires a physical table source, not a CTE"
        raise QueryCompilationError(msg)
    if nested:
        msg = "locking subqueries are not supported"
        raise QueryCompilationError(msg)
    if (
        state.distinct
        or state.joins
        or state.groupings
        or state.having
        or any(isinstance(field, _Aggregate) for field in state.fields)
        or any(isinstance(ordering.column, _Aggregate) for ordering in state.orderings)
    ):
        msg = "FOR UPDATE requires a non-distinct, ungrouped, single-source SELECT"
        raise QueryCompilationError(msg)
    return (dialect.for_update_sql(state.lock_wait),)


def _compile_select_source(
    state: SelectState, dialect: QueryDialect
) -> tuple[str, tuple[object, ...]]:
    """Derived operands preserve binary grouping on both supported dialects."""
    if state.compound is None:
        return _compile_source_sql(state.model, dialect), ()
    left_sql, left_params = _compile_select_state(state.compound.left, dialect)
    right_sql, right_params = _compile_select_state(state.compound.right, dialect)
    alias = dialect.quote_identifier(require_model_table_name(state.model))
    return (
        f"({left_sql} {state.compound.operator} {right_sql}) AS {alias}",
        (*left_params, *right_params),
    )


def _compile_select_state(
    state: SelectState,
    dialect: QueryDialect,
    *,
    outer: ScopeResolver | None = None,
    presence_name: str | None = None,
) -> tuple[str, tuple[object, ...]]:
    if not state.explicit_all and not state.predicates:
        msg = "select requires all() or where() before execution"
        raise QueryCompilationError(msg)
    own_models = state.result_models()
    # A subquery layers the enclosing query's scope as outer, so correlated
    # references resolve against it; the resolver's qualification then makes
    # an inner reference never collide with an identically named outer column.
    scope = (
        outer.enter_subquery(own_models)
        if outer is not None
        else ScopeResolver(own_models=own_models)
    )
    scope.ensure_unambiguous_aliases()
    for column in state.fields:
        if isinstance(column, _Scalar):
            continue
        scope.ensure_operand_in_scope(
            column,
            clause="select",
            error=QueryCompilationError,
            own_only=True,
        )
    ensure_grouping_covers_projection(state)
    quoted_columns, params = _compile_select_list(
        state, dialect, scope=scope, presence_name=presence_name
    )
    select_keyword = "SELECT DISTINCT" if state.distinct else "SELECT"
    quoted_table, source_params = _compile_select_source(state, dialect)
    params = (*params, *source_params)
    sql_parts = [
        f"{select_keyword} {quoted_columns} FROM {quoted_table}",
    ]
    for index, join in enumerate(state.joins):
        join_table = _compile_source_sql(join.model, dialect)
        # ON can see the FROM anchor and preceding joins, never a later join.
        join_scope = ScopeResolver(
            own_models=own_models[: index + 2], outer_models=scope.outer_models
        )
        on_sql, on_params = _compile_predicate_sql(
            join.predicate, dialect, scope=join_scope
        )
        sql_parts.append(f"{join.join_type} JOIN {join_table} ON {on_sql}")
        params = (*params, *on_params)
    if state.predicates:
        predicate_sql, predicate_params = _compile_predicates_sql(
            state.predicates,
            dialect,
            scope=scope,
        )
        sql_parts.append(f"WHERE {predicate_sql}")
        params = (*params, *predicate_params)
    if state.groupings:
        sql_parts.append(
            _compile_group_by_sql(state, dialect, qualified=scope.qualified)
        )
    if state.having:
        for predicate in state.having:
            ensure_having_targets(predicate, state, scope)
        having_sql, having_params = _compile_predicates_sql(
            state.having,
            dialect,
            scope=scope,
        )
        sql_parts.append(f"HAVING {having_sql}")
        params = (*params, *having_params)
    if state.orderings:
        order_by = ", ".join(
            _compile_ordering_sql(ordering, scope, dialect)
            for ordering in state.orderings
        )
        sql_parts.append(f"ORDER BY {order_by}")
    limit_parts, limit_params = _compile_limit_offset_sql(state, dialect)
    sql_parts.extend(limit_parts)
    params = (*params, *limit_params)
    sql_parts.extend(_compile_locking_clause(state, dialect, nested=outer is not None))
    return " ".join(sql_parts), params


def _compile_limit_offset_sql(
    state: SelectState,
    dialect: QueryDialect,
) -> tuple[list[str], tuple[object, ...]]:
    """Bind explicit bounds and use dialect syntax when offset has no limit."""

    parts: list[str] = []
    params: tuple[object, ...] = ()
    if state.limit_value is not None:
        parts.append(f"LIMIT {dialect.placeholder}")
        params = (*params, state.limit_value)
    if state.offset_value is not None:
        if state.limit_value is None:
            parts.append(dialect.offset_only_limit_sql)
        parts.append(f"OFFSET {dialect.placeholder}")
        params = (*params, state.offset_value)
    return parts, params


def compile_select_sql_for_dialect(
    state: SelectState,
    dialect: QueryDialect,
) -> tuple[str, tuple[object, ...]]:
    """Compile a select query's state into backend Dialect SQL."""

    definitions = collect_cte_definitions(state)
    sql, params = _compile_select_state(state, dialect)
    if not definitions:
        return sql, params
    parts: list[str] = []
    definition_params: tuple[object, ...] = ()
    for definition in definitions:
        body, bindings = _compile_select_state(
            definition.state, dialect, presence_name=definition.presence_name
        )
        if definition.recursive_step is not None:
            member, member_bindings = _compile_select_state(
                definition.recursive_step,
                dialect,
                presence_name=definition.presence_name,
            )
            body = f"{body} UNION ALL {member}"
            bindings = (*bindings, *member_bindings)
        parts.append(f"{dialect.quote_identifier(definition.name)} AS ({body})")
        definition_params = (*definition_params, *bindings)
    prefix = (
        "WITH RECURSIVE"
        if any(definition.recursive_step is not None for definition in definitions)
        else "WITH"
    )
    return f"{prefix} {', '.join(parts)} {sql}", (*definition_params, *params)


def compile_write_sql_for_dialect(
    query: object,
    dialect: QueryDialect,
) -> tuple[str, tuple[object, ...]]:
    """Compile a write query into backend Dialect SQL.

    Writes are typed as ``object`` throughout the Query Runtime, so this seam
    narrows from the query object to its state and dispatches on the state type
    -- it never needs to import the Query Builder classes.
    """

    state = getattr(query, "state", None)
    if isinstance(state, InsertState):
        return _compile_insert_sql(state, dialect)
    if isinstance(state, UpdateState):
        return _compile_update_sql(state, dialect)
    if isinstance(state, DeleteState):
        return _compile_delete_sql(state, dialect)
    msg = "execute requires a write query"
    raise QueryCompilationError(msg)


@dataclass(frozen=True)
class InspectedQuery:
    """A built query lowered to SQL for human inspection.

    ``sql``/``params`` are the parameterized form that actually executes;
    ``inlined_sql`` is a best-effort rendering with the (already dialect-encoded)
    parameters substituted as SQL literals, for pasting into a database console.
    The inlined form is approximate and must never be executed.
    """

    sql: str
    params: tuple[object, ...]
    inlined_sql: str


def _render_sql_literal(value: object) -> str:
    """Render an already-encoded parameter as an approximate SQL literal."""

    if value is None:
        return "NULL"
    if isinstance(value, bool):
        return "1" if value else "0"
    if isinstance(value, (int, float)):
        return repr(value)
    if isinstance(value, bytes):
        return "x'" + value.hex() + "'"
    return "'" + str(value).replace("'", "''") + "'"


def _inline_sql_params(
    sql: str,
    params: tuple[object, ...],
    placeholder: str,
) -> str:
    """Substitute encoded params for placeholders in compiled SQL.

    Compiled SQL contains no string literals -- every value is a placeholder and
    every identifier is dialect-quoted -- so splitting on the placeholder token
    is unambiguous. A count mismatch (which should not happen) falls back to the
    parameterized SQL unchanged.
    """

    parts = sql.split(placeholder)
    if len(parts) - 1 != len(params):
        return sql
    rendered: list[str] = []
    for part, value in zip(parts, params, strict=False):
        rendered.append(part)
        rendered.append(_render_sql_literal(value))
    rendered.append(parts[-1])
    return "".join(rendered)


def compile_query_sql(query: object) -> CompiledQuery:
    """Compile a built query using its model's Backend Family, without IO."""

    state = getattr(query, "state", None)
    if isinstance(state, (SelectState, UpdateState, DeleteState)):
        model = state.model
    elif isinstance(state, InsertState):
        model = state.model()
        if model is None:
            msg = "an empty bulk insert has no SQL to compile"
            raise QueryCompilationError(msg)
    else:
        msg = "SQL compilation requires a snekql query"
        raise QueryCompilationError(msg)

    backend = require_model_backend(model)
    dialect = query_dialect_for_backend(backend)
    if isinstance(state, SelectState):
        sql, params = compile_select_sql_for_dialect(state, dialect)
    else:
        sql, params = compile_write_sql_for_dialect(query, dialect)
    return CompiledQuery(backend=backend, params=params, sql=sql)


def inspect_query_sql(query: object) -> InspectedQuery:
    """Produce value-bearing diagnostics only for explicit local inspection.

    Default repr/str must not invoke this helper, because literal rendering
    touches bound values. Compilation and formatting errors propagate here.
    """

    compiled = compile_query_sql(query)
    dialect = query_dialect_for_backend(compiled.backend)
    inlined = _inline_sql_params(compiled.sql, compiled.params, dialect.placeholder)
    return InspectedQuery(sql=compiled.sql, params=compiled.params, inlined_sql=inlined)

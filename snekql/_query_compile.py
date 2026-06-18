"""Query Compilation: lower built query state into backend Dialect SQL.

The write/emit counterpart to materialization. Every function here operates on
query state plus a :class:`QueryDialect`; nothing in this module knows about the
Query Builder classes, so the dependency points one way (builder -> state <-
compilation).
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, cast

from snekql._dialect_expr import CompileCtx, DialectSelectable, SqlCompilable
from snekql._query_dialect import QueryDialect
from snekql._query_state import (
    EXISTENCE_PREDICATE_KINDS,
    SUBQUERY_PREDICATE_KINDS,
    DeleteState,
    InsertState,
    Selectable,
    SelectState,
    UpdateState,
    ensure_assignment_targets_model,
    ensure_grouping_covers_projection,
    ensure_ordering_targets_models,
    require_column_model,
    require_column_name,
    require_field,
    require_insert_model,
    require_selectable,
    require_single_column_subquery,
    require_subquery_state,
    selectable_owner_model,
)
from snekql.errors import QueryCompilationError
from snekql.expressions import Aggregate, OrderBy, Predicate, Scalar
from snekql.model import Table, require_model_columns, require_model_table_name
from snekql.storage import MISSING, Attr

_BINARY_PREDICATE_CHILD_COUNT = 2
_UNARY_PREDICATE_CHILD_COUNT = 1


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
    aggregate: Aggregate[Any, Any],
    dialect: QueryDialect,
    *,
    qualified: bool,
) -> str:
    """Render an aggregate as ``FUNC(col)`` or ``COUNT(*)`` for the select list."""

    column = aggregate.column
    if column is None:
        return f"{aggregate.func}(*)"
    column_ref = _render_column_ref(
        require_field(column),
        dialect,
        qualified=qualified,
    )
    return f"{aggregate.func}({column_ref})"


def _make_compile_ctx(dialect: QueryDialect, *, qualified: bool) -> CompileCtx:
    """Build the facts a dialect expression renders itself against.

    ``render_column`` closes over the enclosing statement's qualification so an
    expression's owned columns quote and qualify exactly like every other column
    reference, without the leaf reimplementing that strategy.
    """

    return CompileCtx(
        placeholder=dialect.placeholder,
        quote_identifier=dialect.quote_identifier,
        render_column=lambda column: _render_column_ref(
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
) -> str:
    if isinstance(field, Scalar):
        # Scalar subqueries carry nested parameters, so the select-list compiler
        # renders them through `_compile_scalar_sql`; they never reach here.
        msg = "scalar subqueries cannot be rendered without their parameters"
        raise QueryCompilationError(msg)
    if isinstance(field, Aggregate):
        return _render_aggregate(field, dialect, qualified=qualified)
    if isinstance(field, SqlCompilable):
        # Open-AST dialect expression: the core renders it structurally through
        # the protocol, never naming the leaf. A projection uses the select seam
        # (`__compile_select_sql__`); an operand uses the operand seam.
        ctx = _make_compile_ctx(dialect, qualified=qualified)
        if projection and isinstance(field, DialectSelectable):
            return field.__compile_select_sql__(ctx)
        return field.__compile_sql__(ctx)
    return _render_column_ref(field, dialect, qualified=qualified)


def _compile_scalar_sql(
    scalar_subquery: Scalar[Any, Any],
    dialect: QueryDialect,
    *,
    scope_models: tuple[type[Table[Any]], ...],
) -> tuple[str, tuple[object, ...]]:
    """Compile a scalar subquery as a parenthesized correlated select."""

    state = require_single_column_subquery(scalar_subquery.subquery)
    sub_sql, sub_params = _compile_select_state(
        state,
        dialect,
        outer_models=scope_models,
    )
    return f"({sub_sql})", sub_params


_COMPARISON_OPERATORS = {"gt": ">", "gte": ">=", "lt": "<", "lte": "<="}


def _compile_compound_predicate_sql(
    predicate: Predicate[Any],
    dialect: QueryDialect,
    *,
    qualified: bool,
    scope_models: tuple[type[Table[Any]], ...],
) -> tuple[str, tuple[object, ...]]:
    if len(predicate.children) != _BINARY_PREDICATE_CHILD_COUNT:
        msg = "compound predicate is malformed"
        raise QueryCompilationError(msg)
    left_sql, left_params = _compile_predicate_sql(
        predicate.children[0],
        dialect,
        qualified=qualified,
        scope_models=scope_models,
    )
    right_sql, right_params = _compile_predicate_sql(
        predicate.children[1],
        dialect,
        qualified=qualified,
        scope_models=scope_models,
    )
    operator = "AND" if predicate.kind == "and" else "OR"
    return f"({left_sql}) {operator} ({right_sql})", (*left_params, *right_params)


def _compile_negated_predicate_sql(
    predicate: Predicate[Any],
    dialect: QueryDialect,
    *,
    qualified: bool,
    scope_models: tuple[type[Table[Any]], ...],
) -> tuple[str, tuple[object, ...]]:
    if len(predicate.children) != _UNARY_PREDICATE_CHILD_COUNT:
        msg = "negated predicate is malformed"
        raise QueryCompilationError(msg)
    child_sql, child_params = _compile_predicate_sql(
        predicate.children[0],
        dialect,
        qualified=qualified,
        scope_models=scope_models,
    )
    return f"NOT ({child_sql})", child_params


def _compile_equality_predicate_sql(
    predicate: Predicate[Any],
    encode: Callable[[object], object],
    column_name: str,
    dialect: QueryDialect,
) -> tuple[str, tuple[object, ...]]:
    if predicate.value is None:
        msg = f"{predicate.kind}(None) is invalid; use is_not_null()"
        if predicate.kind == "eq":
            msg = "eq(None) is invalid; use is_null()"
        raise QueryCompilationError(msg)
    operator = "=" if predicate.kind == "eq" else "!="
    return (
        f"{column_name} {operator} {dialect.placeholder}",
        (encode(predicate.value),),
    )


def _compile_comparison_predicate_sql(
    predicate: Predicate[Any],
    encode: Callable[[object], object],
    column_name: str,
    dialect: QueryDialect,
) -> tuple[str, tuple[object, ...]]:
    if predicate.value is None:
        msg = f"{predicate.kind}(None) is invalid; use is_not_null()"
        raise QueryCompilationError(msg)
    operator = _COMPARISON_OPERATORS[predicate.kind]
    return (
        f"{column_name} {operator} {dialect.placeholder}",
        (encode(predicate.value),),
    )


def _compile_between_predicate_sql(
    predicate: Predicate[Any],
    encode: Callable[[object], object],
    column_name: str,
    dialect: QueryDialect,
) -> tuple[str, tuple[object, ...]]:
    if len(predicate.values) != 2:  # noqa: PLR2004
        msg = "between() requires exactly two bounds"
        raise QueryCompilationError(msg)
    if any(bound is None for bound in predicate.values):
        msg = "between() bounds cannot be None; use is_null()/is_not_null()"
        raise QueryCompilationError(msg)
    params = tuple(encode(bound) for bound in predicate.values)
    return (
        f"{column_name} BETWEEN {dialect.placeholder} AND {dialect.placeholder}",
        params,
    )


def _compile_membership_predicate_sql(
    predicate: Predicate[Any],
    encode: Callable[[object], object],
    column_name: str,
    dialect: QueryDialect,
) -> tuple[str, tuple[object, ...]]:
    if not predicate.values:
        msg = "IN predicates require at least one value"
        raise QueryCompilationError(msg)
    if any(value is None for value in predicate.values):
        msg = "IN predicate values cannot be None"
        raise QueryCompilationError(msg)
    placeholders = ", ".join(dialect.placeholder for _ in predicate.values)
    operator = "IN" if predicate.kind == "in" else "NOT IN"
    params = tuple(encode(value) for value in predicate.values)
    return f"{column_name} {operator} ({placeholders})", params


def _compile_like_predicate_sql(
    predicate: Predicate[Any],
    column: Attr[Any, Any, Any, Any, Any],
    column_name: str,
    dialect: QueryDialect,
) -> tuple[str, tuple[object, ...]]:
    if column.storage_type_name != "Text":
        msg = f"{predicate.kind}() is only valid for text columns"
        raise QueryCompilationError(msg)
    operator = "LIKE" if predicate.kind == "like" else "NOT LIKE"
    return (
        f"{column_name} {operator} {dialect.placeholder}",
        (dialect.encode_column_value(column, predicate.value),),
    )


def _predicate_value_encoder(
    selectable: Selectable,
    dialect: QueryDialect,
) -> Callable[[object], object]:
    """Build the value encoder for a predicate operand.

    A column encodes comparison values through its own logical codec. An
    aggregate's comparison value follows its result type: ``COUNT``/``AVG``
    compare against a plain ``int``/``float`` and pass through unencoded, while
    ``SUM``/``MIN``/``MAX`` share the wrapped column's type and reuse its encoder
    (so e.g. a ``datetime`` ``MIN`` bound is serialized correctly).
    """

    if isinstance(selectable, Scalar):
        msg = "a scalar subquery is not a value-encoding operand"
        raise QueryCompilationError(msg)
    if isinstance(selectable, SqlCompilable):
        # A dialect expression owns its own value type (its `__decode__`), so its
        # comparison value passes through unencoded; the leaf, not a column codec,
        # defines what that operand compares against.
        return lambda value: value
    if isinstance(selectable, Aggregate):
        if selectable.func in {"COUNT", "AVG"}:
            return lambda value: value
        wrapped = require_field(selectable.column)
        return lambda value: dialect.encode_column_value(wrapped, value)
    column = selectable
    return lambda value: dialect.encode_column_value(column, value)


_COLUMN_COMPARISON_OPERATORS = {
    "eq_col": "=",
    "ne_col": "!=",
    "gt_col": ">",
    "gte_col": ">=",
    "lt_col": "<",
    "lte_col": "<=",
}


def _compile_column_comparison_sql(
    predicate: Predicate[Any],
    column_name: str,
    dialect: QueryDialect,
    *,
    qualified: bool,
    scope_models: tuple[type[Table[Any]], ...],
) -> tuple[str, tuple[object, ...]]:
    """Compile a comparison whose right side is a column or a scalar subquery.

    A scalar-subquery operand renders as a parenthesized correlated select; a
    column operand renders as a qualified column reference whose table must be
    reachable in the current scope (its own tables plus any enclosing query the
    subquery correlates to), else the reference is rejected at compile time.
    """

    operator = _COLUMN_COMPARISON_OPERATORS[predicate.kind]
    operand = predicate.value
    if isinstance(operand, Scalar):
        operand_sql, operand_params = _compile_scalar_sql(
            cast("Scalar[Any, Any]", operand),
            dialect,
            scope_models=scope_models,
        )
        return f"{column_name} {operator} {operand_sql}", operand_params
    other = require_field(operand)
    if require_column_model(other) not in scope_models:
        msg = "comparison references a table that is not in the query"
        raise QueryCompilationError(msg)
    other_ref = _render_column_ref(other, dialect, qualified=qualified)
    return f"{column_name} {operator} {other_ref}", ()


def _compile_subquery_membership_sql(
    predicate: Predicate[Any],
    column_name: str,
    dialect: QueryDialect,
    *,
    scope_models: tuple[type[Table[Any]], ...],
) -> tuple[str, tuple[object, ...]]:
    """Compile ``col IN (subquery)`` / ``col NOT IN (subquery)``."""

    state = require_single_column_subquery(predicate.subquery)
    sub_sql, sub_params = _compile_select_state(
        state,
        dialect,
        outer_models=scope_models,
    )
    operator = "IN" if predicate.kind == "in_subquery" else "NOT IN"
    return f"{column_name} {operator} ({sub_sql})", sub_params


def _compile_exists_sql(
    predicate: Predicate[Any],
    dialect: QueryDialect,
    *,
    scope_models: tuple[type[Table[Any]], ...],
) -> tuple[str, tuple[object, ...]]:
    """Compile ``EXISTS (subquery)`` / ``NOT EXISTS (subquery)``."""

    state = require_subquery_state(predicate.subquery)
    sub_sql, sub_params = _compile_select_state(
        state,
        dialect,
        outer_models=scope_models,
    )
    keyword = "EXISTS" if predicate.kind == "exists" else "NOT EXISTS"
    return f"{keyword} ({sub_sql})", sub_params


def _compile_value_predicate_sql(
    predicate: Predicate[Any],
    selectable: Selectable,
    column_name: str,
    dialect: QueryDialect,
) -> tuple[str, tuple[object, ...]]:
    """Compile a predicate whose right side is a literal value (or none)."""

    encode = _predicate_value_encoder(selectable, dialect)
    if predicate.kind in {"eq", "ne"}:
        return _compile_equality_predicate_sql(predicate, encode, column_name, dialect)
    if predicate.kind in {"is_null", "is_not_null"}:
        operator = "IS NULL" if predicate.kind == "is_null" else "IS NOT NULL"
        return f"{column_name} {operator}", ()
    if predicate.kind in {"in", "not_in"}:
        return _compile_membership_predicate_sql(
            predicate,
            encode,
            column_name,
            dialect,
        )
    if predicate.kind in {"like", "not_like"}:
        return _compile_like_predicate_sql(
            predicate,
            require_field(predicate.column),
            column_name,
            dialect,
        )
    if predicate.kind in _COMPARISON_OPERATORS:
        return _compile_comparison_predicate_sql(
            predicate, encode, column_name, dialect
        )
    if predicate.kind == "between":
        return _compile_between_predicate_sql(predicate, encode, column_name, dialect)
    msg = "unknown predicate kind"
    raise QueryCompilationError(msg)


def _compile_column_predicate_sql(
    predicate: Predicate[Any],
    dialect: QueryDialect,
    *,
    qualified: bool,
    scope_models: tuple[type[Table[Any]], ...],
) -> tuple[str, tuple[object, ...]]:
    selectable = require_selectable(predicate.column)
    column_name = _render_selectable(selectable, dialect, qualified=qualified)
    if predicate.kind in _COLUMN_COMPARISON_OPERATORS:
        return _compile_column_comparison_sql(
            predicate,
            column_name,
            dialect,
            qualified=qualified,
            scope_models=scope_models,
        )
    if predicate.kind in SUBQUERY_PREDICATE_KINDS:
        return _compile_subquery_membership_sql(
            predicate,
            column_name,
            dialect,
            scope_models=scope_models,
        )
    return _compile_value_predicate_sql(predicate, selectable, column_name, dialect)


def _compile_predicate_sql(
    predicate: Predicate[Any],
    dialect: QueryDialect,
    *,
    qualified: bool,
    scope_models: tuple[type[Table[Any]], ...],
) -> tuple[str, tuple[object, ...]]:
    if predicate.kind in {"and", "or"}:
        return _compile_compound_predicate_sql(
            predicate,
            dialect,
            qualified=qualified,
            scope_models=scope_models,
        )
    if predicate.kind == "not":
        return _compile_negated_predicate_sql(
            predicate,
            dialect,
            qualified=qualified,
            scope_models=scope_models,
        )
    if predicate.kind in EXISTENCE_PREDICATE_KINDS:
        return _compile_exists_sql(predicate, dialect, scope_models=scope_models)
    return _compile_column_predicate_sql(
        predicate,
        dialect,
        qualified=qualified,
        scope_models=scope_models,
    )


def _compile_group_by_sql(
    state: SelectState,
    dialect: QueryDialect,
    *,
    qualified: bool,
) -> str:
    group_by = ", ".join(
        _render_column_ref(column, dialect, qualified=qualified)
        for column in state.groupings
    )
    return f"GROUP BY {group_by}"


def _compile_ordering_sql(
    ordering: OrderBy[Any],
    models: tuple[type[Table[Any]], ...],
    dialect: QueryDialect,
    *,
    qualified: bool,
) -> str:
    ensure_ordering_targets_models(ordering, models)
    selectable = require_selectable(ordering.column)
    column_name = _render_selectable(selectable, dialect, qualified=qualified)
    return f"{column_name} {ordering.direction}"


def _compile_predicates_sql(
    predicates: tuple[Predicate[Any], ...],
    dialect: QueryDialect,
    *,
    qualified: bool,
    scope_models: tuple[type[Table[Any]], ...],
) -> tuple[str, tuple[object, ...]]:
    predicate_sql_parts: list[str] = []
    predicate_params: list[object] = []
    for predicate in predicates:
        predicate_sql, compiled_params = _compile_predicate_sql(
            predicate,
            dialect,
            qualified=qualified,
            scope_models=scope_models,
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
        if value is MISSING:
            continue
        row_values[name] = dialect.encode_column_value(column, value)
    return row_values


def _insert_returning_clause(
    model_class: type[Table[Any]],
    dialect: QueryDialect,
) -> str:
    columns = require_model_columns(model_class)
    rendered = ", ".join(dialect.quote_identifier(name) for name in columns)
    return f" RETURNING {rendered}"


def _compile_insert_sql(
    state: InsertState,
    dialect: QueryDialect,
) -> tuple[str, tuple[object, ...]]:
    model_class = state.model()
    if model_class is None:
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
        _insert_returning_clause(model_class, dialect) if state.returning else ""
    )
    if not names:
        if len(encoded_rows) > 1:
            msg = "bulk insert requires at least one explicit column"
            raise QueryCompilationError(msg)
        return dialect.empty_insert_sql(quoted_table) + returning, ()
    quoted_columns = ", ".join(dialect.quote_identifier(name) for name in names)
    row_placeholder = "(" + ", ".join(dialect.placeholder for _ in names) + ")"
    values_clause = ", ".join(row_placeholder for _ in encoded_rows)
    sql = (
        "INSERT INTO "  # noqa: S608
        + quoted_table
        + f" ({quoted_columns}) VALUES {values_clause}{returning}"
    )
    params = tuple(row_values[name] for row_values in encoded_rows for name in names)
    return sql, params


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
    table_name = require_model_table_name(state.model)
    set_sql_parts: list[str] = []
    params: tuple[object, ...] = ()
    for assignment in state.assignments:
        ensure_assignment_targets_model(assignment, state.model)
        column = require_field(assignment.column)
        column_name = _render_column_ref(column, dialect)
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
            qualified=False,
            scope_models=(state.model,),
        )
        sql_parts.append(f" WHERE {predicate_sql}")
        params = (*params, *predicate_params)
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
            qualified=False,
            scope_models=(state.model,),
        )
        sql = f"{sql} WHERE {predicate_sql}"
    return sql, params


def _compile_select_list(
    state: SelectState,
    dialect: QueryDialect,
    *,
    qualified: bool,
    scope_models: tuple[type[Table[Any]], ...],
) -> tuple[str, tuple[object, ...]]:
    """Render the projected columns, collecting any scalar-subquery parameters.

    A scalar subquery in the select list carries its own placeholders, so the
    list -- not just the ``WHERE`` clause -- can contribute parameters; they come
    first in textual order, which is exactly the order returned here.
    """

    parts: list[str] = []
    params: tuple[object, ...] = ()
    for field in state.fields:
        if isinstance(field, Scalar):
            scalar_sql, scalar_params = _compile_scalar_sql(
                field,
                dialect,
                scope_models=scope_models,
            )
            parts.append(scalar_sql)
            params = (*params, *scalar_params)
            continue
        parts.append(
            _render_selectable(field, dialect, qualified=qualified, projection=True),
        )
    return ", ".join(parts), params


def _compile_select_state(
    state: SelectState,
    dialect: QueryDialect,
    *,
    outer_models: tuple[type[Table[Any]], ...] = (),
) -> tuple[str, tuple[object, ...]]:
    if not state.explicit_all and not state.predicates:
        msg = "select requires all() or where() before execution"
        raise QueryCompilationError(msg)
    own_models = state.result_models()
    # A subquery (compiled with an enclosing scope) qualifies every column so an
    # inner reference never collides with an identically named outer column;
    # correlated references resolve against the enclosing scope.
    qualified = bool(state.joins) or bool(outer_models)
    scope_models = (*own_models, *outer_models)
    for column in state.fields:
        if isinstance(column, Scalar):
            continue
        if selectable_owner_model(column) not in own_models:
            msg = "select references a table that is not in the query"
            raise QueryCompilationError(msg)
    ensure_grouping_covers_projection(state)
    table_name = require_model_table_name(state.model)
    quoted_columns, params = _compile_select_list(
        state,
        dialect,
        qualified=qualified,
        scope_models=scope_models,
    )
    select_keyword = "SELECT DISTINCT" if state.distinct else "SELECT"
    quoted_table = dialect.quote_identifier(table_name)
    sql_parts = [
        f"{select_keyword} {quoted_columns} FROM {quoted_table}",
    ]
    for join in state.joins:
        join_table = dialect.quote_identifier(require_model_table_name(join.model))
        left_ref = _render_column_ref(join.left_column, dialect, qualified=True)
        right_ref = _render_column_ref(join.right_column, dialect, qualified=True)
        sql_parts.append(
            f"{join.join_type} JOIN {join_table} ON {left_ref} = {right_ref}"
        )
    if state.predicates:
        predicate_sql, predicate_params = _compile_predicates_sql(
            state.predicates,
            dialect,
            qualified=qualified,
            scope_models=scope_models,
        )
        sql_parts.append(f"WHERE {predicate_sql}")
        params = (*params, *predicate_params)
    if state.groupings:
        sql_parts.append(_compile_group_by_sql(state, dialect, qualified=qualified))
    if state.having:
        having_sql, having_params = _compile_predicates_sql(
            state.having,
            dialect,
            qualified=qualified,
            scope_models=scope_models,
        )
        sql_parts.append(f"HAVING {having_sql}")
        params = (*params, *having_params)
    if state.orderings:
        order_by = ", ".join(
            _compile_ordering_sql(ordering, own_models, dialect, qualified=qualified)
            for ordering in state.orderings
        )
        sql_parts.append(f"ORDER BY {order_by}")
    limit_parts, limit_params = _compile_limit_offset_sql(state, dialect)
    sql_parts.extend(limit_parts)
    params = (*params, *limit_params)
    return " ".join(sql_parts), params


def _compile_limit_offset_sql(
    state: SelectState,
    dialect: QueryDialect,
) -> tuple[list[str], tuple[object, ...]]:
    parts: list[str] = []
    params: tuple[object, ...] = ()
    if state.limit_value is not None:
        parts.append(f"LIMIT {dialect.placeholder}")
        params = (*params, state.limit_value)
    if state.offset_value is not None:
        if state.limit_value is None:
            parts.append("LIMIT -1")
        parts.append(f"OFFSET {dialect.placeholder}")
        params = (*params, state.offset_value)
    return parts, params


def compile_select_sql_for_dialect(
    state: SelectState,
    dialect: QueryDialect,
) -> tuple[str, tuple[object, ...]]:
    """Compile a select query's state into backend Dialect SQL."""

    return _compile_select_state(state, dialect)


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

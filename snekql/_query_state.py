"""Query state: the immutable description a Query Builder produces.

This module is the seam shared by the Query Builder (which produces state),
Query Compilation (which lowers state to backend Dialect SQL), and
Materialization (which decodes rows into the result shape). It owns the state
dataclasses plus the accessors and validators that interpret and guard their
contents, so none of the three layers needs to import another.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal, cast

from snekql._dialect_expr import SqlCompilable
from snekql.errors import (
    ModelDeclarationError,
    QueryCompilationError,
    QueryConstructionError,
)
from snekql.expressions import (
    Aggregate,
    Assignment,
    OrderBy,
    Predicate,
    Scalar,
)
from snekql.model import (
    Model,
    Table,
    require_model_columns,
)
from snekql.storage import Attr

# A projectable expression: a column, an aggregate over a column, a scalar
# subquery standing in for a single value, or an open-AST dialect expression
# (e.g. a MariaDB JSON path operator) the core renders/decodes structurally.
type Selectable = (
    Attr[Any, Any, Any, Any, Any]
    | Aggregate[Any, Any]
    | Scalar[Any, Any]
    | SqlCompilable
)


type JoinType = Literal["INNER", "LEFT"]


@dataclass(frozen=True)
class JoinSpec:
    """One joined table and the equality condition that brings it into scope."""

    model: type[Table[Any]]
    join_type: JoinType
    left_column: Attr[Any, Any, Any, Any, Any]
    right_column: Attr[Any, Any, Any, Any, Any]


@dataclass(frozen=True)
class SelectState:
    model: type[Table[Any]]
    fields: tuple[Selectable, ...]
    returns_model: bool = False
    explicit_all: bool = False
    distinct: bool = False
    predicates: tuple[Predicate[Any], ...] = ()
    groupings: tuple[Attr[Any, Any, Any, Any, Any], ...] = ()
    having: tuple[Predicate[Any], ...] = ()
    orderings: tuple[OrderBy[Any], ...] = ()
    limit_value: int | None = None
    offset_value: int | None = None
    joins: tuple[JoinSpec, ...] = ()

    def result_models(self) -> tuple[type[Table[Any]], ...]:
        """Return the base model followed by each joined model, in join order."""

        return (self.model, *(join.model for join in self.joins))


@dataclass(frozen=True)
class UpdateState:
    model: type[Table[Any]]
    assignments: tuple[Assignment[Any], ...] = ()
    explicit_all: bool = False
    predicates: tuple[Predicate[Any], ...] = ()


@dataclass(frozen=True)
class DeleteState:
    model: type[Table[Any]]
    explicit_all: bool = False
    predicates: tuple[Predicate[Any], ...] = ()


@dataclass(frozen=True)
class InsertState:
    """Immutable insert-statement state shared by every insert query variant.

    ``rows`` holds the pending model instances to persist (one for a single
    insert, many for a bulk insert). ``returning`` records whether the write
    should yield rows via ``RETURNING``; ``returning_fields`` records an explicit
    column projection for that clause (empty means project every column and
    decode each row into a Fetched model). ``multi`` records whether the builder
    was created from a sequence, so an empty bulk batch stays typed and
    executable as a no-op even though it carries no rows to read a model from.
    """

    rows: tuple[Table[Any], ...]
    returning: bool = False
    returning_fields: tuple[Selectable, ...] = ()
    multi: bool = False

    def model(self) -> type[Table[Any]] | None:
        """Return the inserted model class, or None for an empty bulk batch."""

        if not self.rows:
            return None
        return type(self.rows[0])


def require_field(value: object) -> Attr[Any, Any, Any, Any, Any]:
    if not isinstance(value, Attr):
        msg = "select requires a model or field"
        raise QueryConstructionError(msg)
    return cast("Attr[Any, Any, Any, Any, Any]", value)


def require_selectable(value: object) -> Selectable:
    if isinstance(value, Aggregate):
        return cast("Aggregate[Any, Any]", value)
    if isinstance(value, Scalar):
        return cast("Scalar[Any, Any]", value)
    if isinstance(value, SqlCompilable):
        return value
    return require_field(value)


def require_subquery_state(subquery: object) -> SelectState:
    """Return a nested query's compiled state, rejecting non-select operands."""

    state = getattr(subquery, "state", None)
    if not isinstance(state, SelectState):
        msg = "a subquery requires a select query"
        raise QueryConstructionError(msg)
    return state


def require_single_column_subquery(subquery: object) -> SelectState:
    """Return a nested query's state, requiring it to project exactly one column.

    ``IN (subquery)`` and scalar subqueries are only meaningful against a
    single-column select; a model select (every column) or a multi-column tuple
    select is rejected at construction.
    """

    state = require_subquery_state(subquery)
    if state.returns_model or len(state.fields) != 1:
        msg = "a subquery value set must select exactly one column"
        raise QueryConstructionError(msg)
    return state


def require_column_name(column: Attr[Any, Any, Any, Any, Any]) -> str:
    if column.name is None:
        msg = "field is not bound to a model"
        raise QueryConstructionError(msg)
    return column.name


def require_column_model(column: Attr[Any, Any, Any, Any, Any]) -> type[Table[Any]]:
    owner = column.owner
    if owner is None:
        msg = "field is not bound to a model"
        raise QueryConstructionError(msg)
    model = cast("type[Table[Any]]", owner)
    try:
        _ = require_model_columns(model)
    except ModelDeclarationError as error:
        msg = "field is not bound to a table model"
        raise QueryConstructionError(msg) from error
    return model


def selectable_owner_model(field: Selectable) -> type[Table[Any]]:
    """Return the table model owning a selectable (column or aggregate).

    An aggregate carries its owner directly (the wrapped column's table, or the
    model for ``COUNT(*)``), so the scope check can treat columns and aggregates
    uniformly. A scalar subquery has no single owning table -- it correlates to
    whatever enclosing scope it references -- so it is not a valid argument here;
    callers handle scalar fields before reaching this seam.
    """

    if isinstance(field, Scalar):
        msg = "a scalar subquery has no single owning table"
        raise QueryConstructionError(msg)
    if isinstance(field, SqlCompilable):
        # A dialect expression names its own owning table; the core scope-checks
        # it through this seam without knowing the concrete leaf type.
        return field.__owner_model__()
    if isinstance(field, Aggregate):
        owner = field.owner
        if owner is None:
            msg = "aggregate is not bound to a table model"
            raise QueryConstructionError(msg)
        model = cast("type[Table[Any]]", owner)
        try:
            _ = require_model_columns(model)
        except ModelDeclarationError as error:
            msg = "aggregate is not bound to a table model"
            raise QueryConstructionError(msg) from error
        return model
    return require_column_model(field)


def require_returning_fields(
    state: InsertState,
    fields: tuple[object, ...],
) -> tuple[Selectable, ...]:
    """Validate an explicit ``returning()`` projection against the inserted model.

    Each field must be a plain column bound to a table model; when the batch has
    rows (so the inserted model is known) it must be a column of that model. An
    empty bulk batch has no model to compare against, so each field is only
    checked for being a bound table column -- it carries its own owner.
    """

    model_class = state.model()
    columns = require_model_columns(model_class) if model_class is not None else None
    selectables: list[Selectable] = []
    for field in fields:
        column = require_field(field)
        name = require_column_name(column)
        owner = require_column_model(column)
        if columns is not None and (name not in columns or owner is not model_class):
            msg = "returning() column must belong to the inserted model"
            raise QueryConstructionError(msg)
        selectables.append(column)
    return tuple(selectables)


def require_insert_model(row: object) -> type[Table[Any]]:
    if not isinstance(row, Model):
        msg = "insert requires a snekql model instance"
        raise QueryConstructionError(msg)
    model_row = cast("Model[Any, Any]", row)
    return cast("type[Table[Any]]", model_row.__class__)


SUBQUERY_PREDICATE_KINDS = {"in_subquery", "not_in_subquery"}
EXISTENCE_PREDICATE_KINDS = {"exists", "not_exists"}


def ensure_predicate_targets_models(
    predicate: Predicate[Any],
    models: tuple[type[Table[Any]], ...],
) -> None:
    if predicate.kind == "":
        msg = "where predicates must be built from columns"
        raise QueryConstructionError(msg)
    if predicate.kind in EXISTENCE_PREDICATE_KINDS:
        # EXISTS carries no outer column; correlation to the outer scope is
        # resolved when the subquery compiles, not at construction.
        _ = require_subquery_state(predicate.subquery)
        return
    if predicate.kind in SUBQUERY_PREDICATE_KINDS:
        _ = require_single_column_subquery(predicate.subquery)
    if predicate.column is not None:
        if isinstance(predicate.column, Aggregate):
            msg = "aggregates cannot appear in where(); use having()"
            raise QueryConstructionError(msg)
        if isinstance(predicate.column, SqlCompilable):
            if predicate.column.__owner_model__() not in models:
                msg = "predicate references a table that is not in the query"
                raise QueryConstructionError(msg)
        else:
            column = require_field(predicate.column)
            if require_column_model(column) not in models:
                msg = "predicate references a table that is not in the query"
                raise QueryConstructionError(msg)
    for child in predicate.children:
        ensure_predicate_targets_models(child, models)


def ensure_having_targets(
    predicate: Predicate[Any],
    state: SelectState,
) -> None:
    """Validate that a HAVING predicate targets only aggregates or grouped columns.

    SQL allows ``HAVING`` to reference the per-group aggregates and the grouping
    keys, never an ungrouped bare column. Aggregates carry their owner directly;
    a plain column must appear in ``group_by`` (and, like ``where``, name a table
    already in scope).
    """

    if predicate.kind == "":
        msg = "having predicates must be built from columns or aggregates"
        raise QueryConstructionError(msg)
    if predicate.column is not None:
        ensure_having_selectable(predicate.column, state)
    for child in predicate.children:
        ensure_having_targets(child, state)


def ensure_having_selectable(column: object, state: SelectState) -> None:
    selectable = require_selectable(column)
    models = state.result_models()
    if selectable_owner_model(selectable) not in models:
        msg = "having references a table that is not in the query"
        raise QueryConstructionError(msg)
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
    models: tuple[type[Table[Any]], ...],
) -> None:
    if ordering.column is None or ordering.direction not in {"ASC", "DESC"}:
        msg = "orderings must be built from columns"
        raise QueryConstructionError(msg)
    selectable = require_selectable(ordering.column)
    if selectable_owner_model(selectable) not in models:
        msg = "ordering references a table that is not in the query"
        raise QueryConstructionError(msg)


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
    model: type[Table[Any]],
) -> None:
    if assignment.column is None:
        msg = "assignments must be built from columns"
        raise QueryConstructionError(msg)
    column = require_field(assignment.column)
    if require_column_model(column) is not model:
        msg = "assignment references a table that is not in the query"
        raise QueryConstructionError(msg)

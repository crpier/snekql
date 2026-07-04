"""Query state: the immutable description a Query Builder produces.

This module is the seam shared by the Query Builder (which produces state),
Query Compilation (which lowers state to backend Dialect SQL), and
Materialization (which decodes rows into the result shape). It owns the state
dataclasses plus the ownership and shape accessors that interpret and guard
their contents, so none of the three layers needs to import another. Scope
policy -- which tables an operand may reference -- lives in
:mod:`snekql._query_scope`, which imports downward into this module.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal, cast

from snekql._dialect_expr import SqlCompilable
from snekql.errors import (
    ModelDeclarationError,
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
    returning: bool = False
    returning_fields: tuple[Selectable, ...] = ()


@dataclass(frozen=True)
class DeleteState:
    model: type[Table[Any]]
    explicit_all: bool = False
    predicates: tuple[Predicate[Any], ...] = ()
    returning: bool = False
    returning_fields: tuple[Selectable, ...] = ()


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
    # Plain columns are the overwhelmingly common selectable; test the concrete
    # ``Attr`` first so the hot path never reaches the structural
    # ``SqlCompilable`` protocol check (a runtime-checkable ``isinstance`` that
    # walks the operand's attributes). Dialect leaves -- the only ``SqlCompilable``
    # values -- are disjoint from ``Attr``/``Aggregate``/``Scalar``, so the
    # reordering selects the same branch for every value.
    if isinstance(value, Attr):
        return cast("Attr[Any, Any, Any, Any, Any]", value)
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

    # A bound column is the common case; resolve it before the structural
    # ``SqlCompilable`` protocol check (an attribute-walking runtime-checkable
    # ``isinstance``). ``Attr`` is disjoint from the other selectable kinds, so
    # the fast path never changes which branch a value takes.
    if isinstance(field, Attr):
        return require_column_model(field)
    if isinstance(field, Scalar):
        msg = "a scalar subquery has no single owning table"
        raise QueryConstructionError(msg)
    if isinstance(field, SqlCompilable):
        # A dialect expression names its own owning table; the core scope-checks
        # it through this seam without knowing the concrete leaf type.
        return field.__owner_model__()
    # Only an aggregate remains: it carries its owning table directly.
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


def require_model_returning_fields(
    model_class: type[Table[Any]] | None,
    fields: tuple[object, ...],
) -> tuple[Selectable, ...]:
    """Validate an explicit ``returning()`` projection against a written model.

    Each field must be a plain column bound to a table model; when the model is
    known it must be a column of that model. An empty bulk insert has no model to
    compare against, so each field is only checked for being a bound table column
    -- it carries its own owner.
    """

    columns = require_model_columns(model_class) if model_class is not None else None
    selectables: list[Selectable] = []
    for field in fields:
        column = require_field(field)
        name = require_column_name(column)
        owner = require_column_model(column)
        if columns is not None and (name not in columns or owner is not model_class):
            msg = "returning() column must belong to the written model"
            raise QueryConstructionError(msg)
        selectables.append(column)
    return tuple(selectables)


def require_returning_fields(
    state: InsertState,
    fields: tuple[object, ...],
) -> tuple[Selectable, ...]:
    """Validate an insert ``returning()`` projection against inserted rows."""

    return require_model_returning_fields(state.model(), fields)


def require_insert_model(row: object) -> type[Table[Any]]:
    if not isinstance(row, Model):
        msg = "insert requires a snekql model instance"
        raise QueryConstructionError(msg)
    model_row = cast("Model[Any, Any]", row)
    return cast("type[Table[Any]]", model_row.__class__)


SUBQUERY_PREDICATE_KINDS = {"in_subquery", "not_in_subquery"}
EXISTENCE_PREDICATE_KINDS = {"exists", "not_exists"}

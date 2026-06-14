"""Query Builder objects and factory functions."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, replace
from typing import Any, Literal, Protocol, Self, TypeVar, TypeVarTuple, cast, overload

from snekql._model_materialization import decode_model_row
from snekql._query_dialect import QueryDialect
from snekql.errors import (
    ModelDeclarationError,
    QueryCompilationError,
    QueryConstructionError,
)
from snekql.expressions import Assignment, JoinOn, OrderBy, Predicate
from snekql.model import (
    Model,
    Table,
    require_model_columns,
    require_model_table_name,
)
from snekql.storage import MISSING, Attr, StorageBackend
from snekql.validation import NonNegativeInt, validate_boundary

ModelT = TypeVar("ModelT", bound=Table[Any])
ReadModelT = TypeVar("ReadModelT", bound=Table[Any])
SelectOwnerT = TypeVar("SelectOwnerT", bound=Table[Any])
OwnerT = TypeVar("OwnerT", bound=Table[Any])
SelectableOwnerT_co = TypeVar("SelectableOwnerT_co", bound=Table[Any], covariant=True)
SelectableReadT_co = TypeVar("SelectableReadT_co", bound=Table[Any], covariant=True)
T = TypeVar("T")
T1 = TypeVar("T1")
T2 = TypeVar("T2")
T3 = TypeVar("T3")
Ts = TypeVarTuple("Ts")

_BINARY_PREDICATE_CHILD_COUNT = 2
_UNARY_PREDICATE_CHILD_COUNT = 1


class _SelectableModelClass(Protocol[SelectableOwnerT_co, SelectableReadT_co]):
    """Structural type for model classes accepted by `select(Model)`.

    The protocol lets pyright connect the writable owner model type with the
    fetched read model type exposed by table model classes.
    """

    @classmethod
    def __owner_type__(cls) -> type[SelectableOwnerT_co]: ...

    @classmethod
    def __read_type__(cls) -> type[SelectableReadT_co]: ...


type JoinType = Literal["INNER", "LEFT"]


@dataclass(frozen=True)
class _JoinSpec:
    """One joined table and the equality condition that brings it into scope."""

    model: type[Table[Any]]
    join_type: JoinType
    left_column: Attr[Any, Any, Any, Any, Any]
    right_column: Attr[Any, Any, Any, Any, Any]


@dataclass(frozen=True)
class _SelectState:
    model: type[Table[Any]]
    fields: tuple[Attr[Any, Any, Any, Any, Any], ...]
    returns_model: bool = False
    explicit_all: bool = False
    predicates: tuple[Predicate[Any], ...] = ()
    orderings: tuple[OrderBy[Any], ...] = ()
    limit_value: int | None = None
    offset_value: int | None = None
    joins: tuple[_JoinSpec, ...] = ()

    def result_models(self) -> tuple[type[Table[Any]], ...]:
        """Return the base model followed by each joined model, in join order."""

        return (self.model, *(join.model for join in self.joins))


@dataclass(frozen=True)
class _UpdateState:
    model: type[Table[Any]]
    assignments: tuple[Assignment[Any], ...] = ()
    explicit_all: bool = False
    predicates: tuple[Predicate[Any], ...] = ()


@dataclass(frozen=True)
class _DeleteState:
    model: type[Table[Any]]
    explicit_all: bool = False
    predicates: tuple[Predicate[Any], ...] = ()


class _BaseSelectQuery:
    """Immutable select-state plumbing shared by every select query.

    Holds the state object and the transitions that never change a query's
    generic shape (`all`, `limit`, `offset`). Subclasses add the typed surface
    (`where`/`order_by`/`join`) whose return types depend on their parameters.
    """

    state: _SelectState

    def __init__(self, state: _SelectState | None = None) -> None:
        if state is None:
            state = _empty_select_state()
        self.state = state

    def _replace_state(self, state: _SelectState) -> Self:
        return type(self)(state)

    def all(self) -> Self:
        """Select every row explicitly instead of providing predicates."""

        state = _select_all(self.state)
        if state is self.state:
            return self
        return self._replace_state(state)

    @validate_boundary(error_type=QueryConstructionError)
    def limit(self, value: NonNegativeInt) -> Self:
        """Limit the number of selected rows."""

        return self._replace_state(_select_limit(self.state, value))

    @validate_boundary(error_type=QueryConstructionError)
    def offset(self, value: NonNegativeInt) -> Self:
        """Skip the given number of selected rows."""

        return self._replace_state(_select_offset(self.state, value))


class _FluentSelectQuery[FluentOwnerT: Table[Any]](_BaseSelectQuery):
    """Model-select fluent surface whose `where`/`order_by` are owner-scoped.

    Used by model selects (`SelectModelQuery`, `JoinModelQuery`): the owner
    union types `where`/`order_by` directly, rejecting out-of-scope predicates
    at the call site. Projection selects defer that check to fetch instead (see
    the dual-union scope check), so they do not share this surface.
    """

    def where(self, *predicates: Predicate[FluentOwnerT]) -> Self:
        """Filter selected rows by AND-combined column predicates."""

        return self._replace_state(_select_where(self.state, predicates))

    def order_by(self, *ordering: OrderBy[FluentOwnerT]) -> Self:
        """Order selected rows by the given column orderings."""

        return self._replace_state(_select_order_by(self.state, ordering))


class SelectModelQuery[SelectOwnerT: Table[Any], ReadModelT: Table[Any]](
    _FluentSelectQuery[SelectOwnerT],
):
    """Immutable select query that returns fetched table model instances."""

    def join[NewOwnerT: Table[Any], NewReadT: Table[Any]](
        self,
        model: _SelectableModelClass[NewOwnerT, NewReadT],
        on: JoinOn[NewOwnerT, SelectOwnerT] | JoinOn[SelectOwnerT, NewOwnerT],
    ) -> JoinModelQuery[SelectOwnerT | NewOwnerT, ReadModelT, NewReadT]:
        """Inner-join another table, appending its fetched model to each row."""

        return cast(
            "JoinModelQuery[SelectOwnerT | NewOwnerT, ReadModelT, NewReadT]",
            JoinModelQuery[Any, *tuple[Any, ...]](
                _select_join(self.state, model, on, "INNER"),
            ),
        )

    def left_join[NewOwnerT: Table[Any], NewReadT: Table[Any]](
        self,
        model: _SelectableModelClass[NewOwnerT, NewReadT],
        on: JoinOn[NewOwnerT, SelectOwnerT] | JoinOn[SelectOwnerT, NewOwnerT],
    ) -> JoinModelQuery[SelectOwnerT | NewOwnerT, ReadModelT, NewReadT | None]:
        """Left-join another table; its fetched model is optional per row."""

        return cast(
            "JoinModelQuery[SelectOwnerT | NewOwnerT, ReadModelT, NewReadT | None]",
            JoinModelQuery[Any, *tuple[Any, ...]](
                _select_join(self.state, model, on, "LEFT"),
            ),
        )


class JoinModelQuery[JoinOwnerT: Table[Any], *ResultTs](
    _FluentSelectQuery[JoinOwnerT],
):
    """Immutable model-select across joined tables; rows are model tuples.

    `JoinOwnerT` accumulates a union of every joined table's `Pending` owner, so
    `where`/`order_by` accept predicates from any joined table (via the covariant
    `Predicate`) and reject columns from tables not in the query. `*ResultTs`
    accumulates the per-table fetched models: `join` appends `T[Fetched]` and
    `left_join` appends `T[Fetched] | None`.
    """

    def join[NewOwnerT: Table[Any], NewReadT: Table[Any]](
        self,
        model: _SelectableModelClass[NewOwnerT, NewReadT],
        on: JoinOn[NewOwnerT, JoinOwnerT] | JoinOn[JoinOwnerT, NewOwnerT],
    ) -> JoinModelQuery[JoinOwnerT | NewOwnerT, *ResultTs, NewReadT]:
        """Inner-join another table, appending its fetched model to each row."""

        return cast(
            "JoinModelQuery[JoinOwnerT | NewOwnerT, *ResultTs, NewReadT]",
            JoinModelQuery[Any, *tuple[Any, ...]](
                _select_join(self.state, model, on, "INNER"),
            ),
        )

    def left_join[NewOwnerT: Table[Any], NewReadT: Table[Any]](
        self,
        model: _SelectableModelClass[NewOwnerT, NewReadT],
        on: JoinOn[NewOwnerT, JoinOwnerT] | JoinOn[JoinOwnerT, NewOwnerT],
    ) -> JoinModelQuery[JoinOwnerT | NewOwnerT, *ResultTs, NewReadT | None]:
        """Left-join another table; its fetched model is optional per row."""

        return cast(
            "JoinModelQuery[JoinOwnerT | NewOwnerT, *ResultTs, NewReadT | None]",
            JoinModelQuery[Any, *tuple[Any, ...]](
                _select_join(self.state, model, on, "LEFT"),
            ),
        )


class SelectValueQuery[ScopeT: Table[Any], RefT: Table[Any], T](_BaseSelectQuery):
    """Projection select of one column; fetch yields one scalar value per row.

    Carries the dual-union scope check shared by projection selects. `ScopeT` is
    the FROM/JOIN graph, seeded with the projected column's table (the implicit
    `FROM` anchor) and grown by `join`/`left_join`. `RefT` is every referenced
    table: the projected column plus any added by `where`/`order_by`.
    `fetch_all`/`fetch_one` unify the two through one fresh type variable, which
    forces `RefT <: ScopeT` -- referencing a table that was never joined is a
    type error. `ScopeT` is pinned invariant by `_pin_scope` so the constraint
    does not collapse.
    """

    def _pin_scope(self, _scope: ScopeT) -> None:
        """Phantom input-position member that pins `ScopeT` to invariant."""

    def where[RefOwnerT: Table[Any]](
        self,
        *predicates: Predicate[RefOwnerT],
    ) -> SelectValueQuery[ScopeT, RefT | RefOwnerT, T]:
        """Filter rows, widening the referenced-table union by the predicates."""

        return cast(
            "SelectValueQuery[ScopeT, RefT | RefOwnerT, T]",
            SelectValueQuery[Any, Any, T](_select_where(self.state, predicates)),
        )

    def order_by[RefOwnerT: Table[Any]](
        self,
        *ordering: OrderBy[RefOwnerT],
    ) -> SelectValueQuery[ScopeT, RefT | RefOwnerT, T]:
        """Order rows, widening the referenced-table union by the orderings."""

        return cast(
            "SelectValueQuery[ScopeT, RefT | RefOwnerT, T]",
            SelectValueQuery[Any, Any, T](_select_order_by(self.state, ordering)),
        )

    def join[
        NewOwnerT: Table[Any],
        NewReadT: Table[Any],
        LeftT: Table[Any],
        RightT: Table[Any],
    ](
        self,
        model: _SelectableModelClass[NewOwnerT, NewReadT],
        on: JoinOn[LeftT, RightT],
    ) -> SelectValueQuery[ScopeT | LeftT | RightT, RefT, T]:
        """Inner-join another table into the scope without changing the result."""

        return cast(
            "SelectValueQuery[ScopeT | LeftT | RightT, RefT, T]",
            SelectValueQuery[Any, Any, T](
                _select_join(self.state, model, on, "INNER", project=True),
            ),
        )

    def left_join[
        NewOwnerT: Table[Any],
        NewReadT: Table[Any],
        LeftT: Table[Any],
        RightT: Table[Any],
    ](
        self,
        model: _SelectableModelClass[NewOwnerT, NewReadT],
        on: JoinOn[LeftT, RightT],
    ) -> SelectValueQuery[ScopeT | LeftT | RightT, RefT, T]:
        """Left-join another table into the scope without changing the result."""

        return cast(
            "SelectValueQuery[ScopeT | LeftT | RightT, RefT, T]",
            SelectValueQuery[Any, Any, T](
                _select_join(self.state, model, on, "LEFT", project=True),
            ),
        )


class SelectTupleQuery[ScopeT: Table[Any], RefT: Table[Any], *Ts](_BaseSelectQuery):
    """Projection select of several columns; fetch yields a tuple per row.

    Carries the same dual-union scope check as `SelectValueQuery` (see its
    docstring): `ScopeT` is the joined FROM graph, `RefT` is every referenced
    table, and the fetch overloads force `RefT <: ScopeT`. `*Ts` is the fixed
    tuple of projected read types, unchanged by joins -- a join only declares
    how tables connect, never the result shape.
    """

    def _pin_scope(self, _scope: ScopeT) -> None:
        """Phantom input-position member that pins `ScopeT` to invariant."""

    def where[RefOwnerT: Table[Any]](
        self,
        *predicates: Predicate[RefOwnerT],
    ) -> SelectTupleQuery[ScopeT, RefT | RefOwnerT, *Ts]:
        """Filter rows, widening the referenced-table union by the predicates."""

        return cast(
            "SelectTupleQuery[ScopeT, RefT | RefOwnerT, *Ts]",
            SelectTupleQuery[Any, Any, *Ts](_select_where(self.state, predicates)),
        )

    def order_by[RefOwnerT: Table[Any]](
        self,
        *ordering: OrderBy[RefOwnerT],
    ) -> SelectTupleQuery[ScopeT, RefT | RefOwnerT, *Ts]:
        """Order rows, widening the referenced-table union by the orderings."""

        return cast(
            "SelectTupleQuery[ScopeT, RefT | RefOwnerT, *Ts]",
            SelectTupleQuery[Any, Any, *Ts](_select_order_by(self.state, ordering)),
        )

    def join[
        NewOwnerT: Table[Any],
        NewReadT: Table[Any],
        LeftT: Table[Any],
        RightT: Table[Any],
    ](
        self,
        model: _SelectableModelClass[NewOwnerT, NewReadT],
        on: JoinOn[LeftT, RightT],
    ) -> SelectTupleQuery[ScopeT | LeftT | RightT, RefT, *Ts]:
        """Inner-join another table into the scope without changing the result."""

        return cast(
            "SelectTupleQuery[ScopeT | LeftT | RightT, RefT, *Ts]",
            SelectTupleQuery[Any, Any, *Ts](
                _select_join(self.state, model, on, "INNER", project=True),
            ),
        )

    def left_join[
        NewOwnerT: Table[Any],
        NewReadT: Table[Any],
        LeftT: Table[Any],
        RightT: Table[Any],
    ](
        self,
        model: _SelectableModelClass[NewOwnerT, NewReadT],
        on: JoinOn[LeftT, RightT],
    ) -> SelectTupleQuery[ScopeT | LeftT | RightT, RefT, *Ts]:
        """Left-join another table into the scope without changing the result."""

        return cast(
            "SelectTupleQuery[ScopeT | LeftT | RightT, RefT, *Ts]",
            SelectTupleQuery[Any, Any, *Ts](
                _select_join(self.state, model, on, "LEFT", project=True),
            ),
        )


class InsertQuery[ModelT: Table[Any]]:
    """Immutable insert statement for one pending table model instance."""

    row: ModelT

    def __init__(self, row: ModelT) -> None:
        self.row: ModelT = row


class UpdateQuery[ModelT: Table[Any]]:
    """Immutable update statement for one table model."""

    state: _UpdateState

    def __init__(self, state: _UpdateState | None = None) -> None:
        if state is None:
            state = _UpdateState(model=Table[Any])
        self.state: _UpdateState = state

    def all(self) -> Self:
        state = _update_all(self.state)
        if state is self.state:
            return self
        return cast("Self", UpdateQuery[ModelT](state))

    def set(self, *assignments: Assignment[ModelT]) -> Self:
        state = _update_set(self.state, assignments)
        return cast("Self", UpdateQuery[ModelT](state))

    def where(self, *predicates: Predicate[ModelT]) -> Self:
        state = _update_where(self.state, predicates)
        return cast("Self", UpdateQuery[ModelT](state))


class DeleteQuery[ModelT: Table[Any]]:
    """Immutable delete statement for one table model."""

    state: _DeleteState

    def __init__(self, state: _DeleteState | None = None) -> None:
        if state is None:
            state = _DeleteState(model=Table[Any])
        self.state: _DeleteState = state

    def all(self) -> Self:
        state = _delete_all(self.state)
        if state is self.state:
            return self
        return cast("Self", DeleteQuery[ModelT](state))

    def where(self, *predicates: Predicate[ModelT]) -> Self:
        state = _delete_where(self.state, predicates)
        return cast("Self", DeleteQuery[ModelT](state))


type AnySelectQuery = (
    SelectModelQuery[Any, Any]
    | SelectValueQuery[Any, Any, Any]
    | SelectTupleQuery[Any, Any, *tuple[Any, ...]]
    | JoinModelQuery[Any, *tuple[Any, ...]]
)


def _empty_select_state() -> _SelectState:
    return _SelectState(model=Table[Any], fields=())


def _select_all(state: _SelectState) -> _SelectState:
    if state.predicates:
        msg = "all() cannot be combined with where()"
        raise QueryConstructionError(msg)
    if state.explicit_all:
        return state
    return replace(state, explicit_all=True)


def _select_where(
    state: _SelectState,
    predicates: tuple[Predicate[Any], ...],
) -> _SelectState:
    if not predicates:
        msg = "where() requires at least one predicate"
        raise QueryConstructionError(msg)
    if state.explicit_all:
        msg = "where() cannot be combined with all()"
        raise QueryConstructionError(msg)
    for predicate in predicates:
        _ensure_predicate_targets_models(predicate, state.result_models())
    return replace(state, predicates=(*state.predicates, *predicates))


def _select_order_by(
    state: _SelectState,
    orderings: tuple[OrderBy[Any], ...],
) -> _SelectState:
    if not orderings:
        msg = "order_by() requires at least one ordering"
        raise QueryConstructionError(msg)
    for ordering in orderings:
        _ensure_ordering_targets_models(ordering, state.result_models())
    return replace(state, orderings=(*state.orderings, *orderings))


def _select_join(
    state: _SelectState,
    model: object,
    on: object,
    join_type: JoinType,
    *,
    project: bool = False,
) -> _SelectState:
    if not isinstance(model, type):
        msg = "join requires a table model"
        raise QueryConstructionError(msg)
    table_model = cast("type[Table[Any]]", model)
    try:
        new_columns = require_model_columns(table_model)
    except ModelDeclarationError as error:
        msg = "join requires a table model"
        raise QueryConstructionError(msg) from error
    if not isinstance(on, JoinOn):
        msg = "join requires an on= condition built from references()"
        raise QueryConstructionError(msg)
    condition = cast("JoinOn[Any, Any]", on)
    left_column = _require_field(condition.left_column)
    right_column = _require_field(condition.right_column)
    related = {_require_column_model(left_column), _require_column_model(right_column)}
    if table_model not in related:
        msg = "join condition must reference the joined table"
        raise QueryConstructionError(msg)
    already_joined = set(state.result_models())
    if table_model in already_joined:
        msg = "table is already joined"
        raise QueryConstructionError(msg)
    if not (related - {table_model}) <= already_joined:
        msg = "join condition must relate the joined table to an already-joined table"
        raise QueryConstructionError(msg)
    spec = _JoinSpec(
        model=table_model,
        join_type=join_type,
        left_column=left_column,
        right_column=right_column,
    )
    if project:
        # Projection selects keep their fixed projected columns; a join only
        # brings the table into the FROM graph, it never widens the SELECT list.
        return replace(state, joins=(*state.joins, spec))
    return replace(
        state,
        fields=(*state.fields, *new_columns.values()),
        returns_model=True,
        joins=(*state.joins, spec),
    )


def _select_limit(state: _SelectState, value: NonNegativeInt) -> _SelectState:
    return replace(state, limit_value=value)


def _select_offset(state: _SelectState, value: NonNegativeInt) -> _SelectState:
    return replace(state, offset_value=value)


def _update_all(state: _UpdateState) -> _UpdateState:
    if state.predicates:
        msg = "all() cannot be combined with where()"
        raise QueryConstructionError(msg)
    if state.explicit_all:
        return state
    return replace(state, explicit_all=True)


def _update_set(
    state: _UpdateState,
    assignments: tuple[Assignment[Any], ...],
) -> _UpdateState:
    if not assignments:
        msg = "set() requires at least one assignment"
        raise QueryConstructionError(msg)
    for assignment in assignments:
        _ensure_assignment_targets_model(assignment, state.model)
    return replace(state, assignments=(*state.assignments, *assignments))


def _update_where(
    state: _UpdateState,
    predicates: tuple[Predicate[Any], ...],
) -> _UpdateState:
    if not predicates:
        msg = "where() requires at least one predicate"
        raise QueryConstructionError(msg)
    if state.explicit_all:
        msg = "where() cannot be combined with all()"
        raise QueryConstructionError(msg)
    for predicate in predicates:
        _ensure_predicate_targets_models(predicate, (state.model,))
    return replace(state, predicates=(*state.predicates, *predicates))


def _delete_all(state: _DeleteState) -> _DeleteState:
    if state.predicates:
        msg = "all() cannot be combined with where()"
        raise QueryConstructionError(msg)
    if state.explicit_all:
        return state
    return replace(state, explicit_all=True)


def _delete_where(
    state: _DeleteState,
    predicates: tuple[Predicate[Any], ...],
) -> _DeleteState:
    if not predicates:
        msg = "where() requires at least one predicate"
        raise QueryConstructionError(msg)
    if state.explicit_all:
        msg = "where() cannot be combined with all()"
        raise QueryConstructionError(msg)
    for predicate in predicates:
        _ensure_predicate_targets_models(predicate, (state.model,))
    return replace(state, predicates=(*state.predicates, *predicates))


def _require_field(value: object) -> Attr[Any, Any, Any, Any, Any]:
    if not isinstance(value, Attr):
        msg = "select requires a model or field"
        raise QueryConstructionError(msg)
    return cast("Attr[Any, Any, Any, Any, Any]", value)


def _require_column_name(column: Attr[Any, Any, Any, Any, Any]) -> str:
    if column.name is None:
        msg = "field is not bound to a model"
        raise QueryConstructionError(msg)
    return column.name


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

    quoted_name = dialect.quote_identifier(_require_column_name(column))
    if not qualified:
        return quoted_name
    table_name = require_model_table_name(_require_column_model(column))
    return f"{dialect.quote_identifier(table_name)}.{quoted_name}"


def _require_column_model(column: Attr[Any, Any, Any, Any, Any]) -> type[Table[Any]]:
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


def _ensure_predicate_targets_models(
    predicate: Predicate[Any],
    models: tuple[type[Table[Any]], ...],
) -> None:
    if predicate.kind == "":
        msg = "where predicates must be built from columns"
        raise QueryConstructionError(msg)
    if predicate.column is not None:
        column = _require_field(predicate.column)
        if _require_column_model(column) not in models:
            msg = "predicate references a table that is not in the query"
            raise QueryConstructionError(msg)
    for child in predicate.children:
        _ensure_predicate_targets_models(child, models)


def _ensure_ordering_targets_models(
    ordering: OrderBy[Any],
    models: tuple[type[Table[Any]], ...],
) -> None:
    if ordering.column is None or ordering.direction not in {"ASC", "DESC"}:
        msg = "orderings must be built from columns"
        raise QueryConstructionError(msg)
    column = _require_field(ordering.column)
    if _require_column_model(column) not in models:
        msg = "ordering references a table that is not in the query"
        raise QueryConstructionError(msg)


def _ensure_assignment_targets_model(
    assignment: Assignment[Any],
    model: type[Table[Any]],
) -> None:
    if assignment.column is None:
        msg = "assignments must be built from columns"
        raise QueryConstructionError(msg)
    column = _require_field(assignment.column)
    if _require_column_model(column) is not model:
        msg = "assignment references a table that is not in the query"
        raise QueryConstructionError(msg)
    if column.is_generated or column.primary_key:
        msg = "generated and primary key columns cannot update"
        raise QueryConstructionError(msg)


def _require_insert_model(row: object) -> type[Table[Any]]:
    if not isinstance(row, Model):
        msg = "insert requires a snekql model instance"
        raise QueryConstructionError(msg)
    model_row = cast("Model[Any, Any]", row)
    return cast("type[Table[Any]]", model_row.__class__)


def _encode_insert_row(
    query: InsertQuery[Any],
    dialect: QueryDialect,
) -> tuple[type[Table[Any]], dict[str, object]]:
    model_class = _require_insert_model(query.row)
    row_values: dict[str, object] = {}
    for name, column in require_model_columns(model_class).items():
        value = getattr(query.row, name)
        if value is MISSING:
            continue
        row_values[name] = dialect.encode_column_value(column, value)
    return model_class, row_values


def _compile_insert_sql(
    query: InsertQuery[Any],
    dialect: QueryDialect,
) -> tuple[str, tuple[object, ...]]:
    model_class, row_values = _encode_insert_row(query, dialect)
    table_name = require_model_table_name(model_class)
    quoted_table = dialect.quote_identifier(table_name)
    if not row_values:
        return dialect.empty_insert_sql(quoted_table), ()
    names = tuple(row_values)
    quoted_columns = ", ".join(dialect.quote_identifier(name) for name in names)
    placeholders = ", ".join(dialect.placeholder for _ in names)
    sql = "INSERT INTO " + quoted_table + f" ({quoted_columns}) VALUES ({placeholders})"  # noqa: S608
    params = tuple(row_values[name] for name in names)
    return sql, params


def _compile_compound_predicate_sql(
    predicate: Predicate[Any],
    models: tuple[type[Table[Any]], ...],
    dialect: QueryDialect,
    *,
    qualified: bool,
) -> tuple[str, tuple[object, ...]]:
    if len(predicate.children) != _BINARY_PREDICATE_CHILD_COUNT:
        msg = "compound predicate is malformed"
        raise QueryCompilationError(msg)
    left_sql, left_params = _compile_predicate_sql(
        predicate.children[0],
        models,
        dialect,
        qualified=qualified,
    )
    right_sql, right_params = _compile_predicate_sql(
        predicate.children[1],
        models,
        dialect,
        qualified=qualified,
    )
    operator = "AND" if predicate.kind == "and" else "OR"
    return f"({left_sql}) {operator} ({right_sql})", (*left_params, *right_params)


def _compile_negated_predicate_sql(
    predicate: Predicate[Any],
    models: tuple[type[Table[Any]], ...],
    dialect: QueryDialect,
    *,
    qualified: bool,
) -> tuple[str, tuple[object, ...]]:
    if len(predicate.children) != _UNARY_PREDICATE_CHILD_COUNT:
        msg = "negated predicate is malformed"
        raise QueryCompilationError(msg)
    child_sql, child_params = _compile_predicate_sql(
        predicate.children[0],
        models,
        dialect,
        qualified=qualified,
    )
    return f"NOT ({child_sql})", child_params


def _compile_equality_predicate_sql(
    predicate: Predicate[Any],
    column: Attr[Any, Any, Any, Any, Any],
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
        (dialect.encode_column_value(column, predicate.value),),
    )


def _compile_membership_predicate_sql(
    predicate: Predicate[Any],
    column: Attr[Any, Any, Any, Any, Any],
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
    params = tuple(
        dialect.encode_column_value(column, value) for value in predicate.values
    )
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


def _compile_column_predicate_sql(
    predicate: Predicate[Any],
    dialect: QueryDialect,
    *,
    qualified: bool,
) -> tuple[str, tuple[object, ...]]:
    column = _require_field(predicate.column)
    column_name = _render_column_ref(column, dialect, qualified=qualified)
    if predicate.kind in {"eq", "ne"}:
        return _compile_equality_predicate_sql(
            predicate,
            column,
            column_name,
            dialect,
        )
    if predicate.kind == "is_null":
        return f"{column_name} IS NULL", ()
    if predicate.kind == "is_not_null":
        return f"{column_name} IS NOT NULL", ()
    if predicate.kind in {"in", "not_in"}:
        return _compile_membership_predicate_sql(
            predicate,
            column,
            column_name,
            dialect,
        )
    if predicate.kind in {"like", "not_like"}:
        return _compile_like_predicate_sql(predicate, column, column_name, dialect)
    msg = "unknown predicate kind"
    raise QueryCompilationError(msg)


def _compile_predicate_sql(
    predicate: Predicate[Any],
    models: tuple[type[Table[Any]], ...],
    dialect: QueryDialect,
    *,
    qualified: bool,
) -> tuple[str, tuple[object, ...]]:
    _ensure_predicate_targets_models(predicate, models)
    if predicate.kind in {"and", "or"}:
        return _compile_compound_predicate_sql(
            predicate,
            models,
            dialect,
            qualified=qualified,
        )
    if predicate.kind == "not":
        return _compile_negated_predicate_sql(
            predicate,
            models,
            dialect,
            qualified=qualified,
        )
    return _compile_column_predicate_sql(predicate, dialect, qualified=qualified)


def _compile_ordering_sql(
    ordering: OrderBy[Any],
    models: tuple[type[Table[Any]], ...],
    dialect: QueryDialect,
    *,
    qualified: bool,
) -> str:
    _ensure_ordering_targets_models(ordering, models)
    column = _require_field(ordering.column)
    column_name = _render_column_ref(column, dialect, qualified=qualified)
    return f"{column_name} {ordering.direction}"


def _compile_predicates_sql(
    predicates: tuple[Predicate[Any], ...],
    models: tuple[type[Table[Any]], ...],
    dialect: QueryDialect,
    *,
    qualified: bool,
) -> tuple[str, tuple[object, ...]]:
    predicate_sql_parts: list[str] = []
    predicate_params: list[object] = []
    for predicate in predicates:
        predicate_sql, compiled_params = _compile_predicate_sql(
            predicate,
            models,
            dialect,
            qualified=qualified,
        )
        predicate_sql_parts.append(f"({predicate_sql})")
        predicate_params.extend(compiled_params)
    return " AND ".join(predicate_sql_parts), tuple(predicate_params)


def _compile_update_sql(
    query: UpdateQuery[Any],
    dialect: QueryDialect,
) -> tuple[str, tuple[object, ...]]:
    state = query.state
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
        _ensure_assignment_targets_model(assignment, state.model)
        column = _require_field(assignment.column)
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
            (state.model,),
            dialect,
            qualified=False,
        )
        sql_parts.append(f" WHERE {predicate_sql}")
        params = (*params, *predicate_params)
    return "".join(sql_parts), params


def _compile_delete_sql(
    query: DeleteQuery[Any],
    dialect: QueryDialect,
) -> tuple[str, tuple[object, ...]]:
    state = query.state
    if not state.explicit_all and not state.predicates:
        msg = "delete requires all() or where() before execution"
        raise QueryCompilationError(msg)
    table_name = require_model_table_name(state.model)
    sql = "DELETE FROM " + dialect.quote_identifier(table_name)  # noqa: S608
    params: tuple[object, ...] = ()
    if state.predicates:
        predicate_sql, params = _compile_predicates_sql(
            state.predicates,
            (state.model,),
            dialect,
            qualified=False,
        )
        sql = f"{sql} WHERE {predicate_sql}"
    return sql, params


def _compile_select_state(
    state: _SelectState,
    dialect: QueryDialect,
) -> tuple[str, tuple[object, ...]]:
    if not state.explicit_all and not state.predicates:
        msg = "select requires all() or where() before execution"
        raise QueryCompilationError(msg)
    qualified = bool(state.joins)
    models = state.result_models()
    for column in state.fields:
        if _require_column_model(column) not in models:
            msg = "select references a table that is not in the query"
            raise QueryCompilationError(msg)
    table_name = require_model_table_name(state.model)
    quoted_columns = ", ".join(
        _render_column_ref(column, dialect, qualified=qualified)
        for column in state.fields
    )
    sql_parts = [
        "SELECT " + quoted_columns + " FROM " + dialect.quote_identifier(table_name),  # noqa: S608
    ]
    for join in state.joins:
        join_table = dialect.quote_identifier(require_model_table_name(join.model))
        left_ref = _render_column_ref(join.left_column, dialect, qualified=True)
        right_ref = _render_column_ref(join.right_column, dialect, qualified=True)
        sql_parts.append(
            f"{join.join_type} JOIN {join_table} ON {left_ref} = {right_ref}"
        )
    params: tuple[object, ...] = ()
    if state.predicates:
        predicate_sql, predicate_params = _compile_predicates_sql(
            state.predicates,
            models,
            dialect,
            qualified=qualified,
        )
        sql_parts.append(f"WHERE {predicate_sql}")
        params = (*params, *predicate_params)
    if state.orderings:
        order_by = ", ".join(
            _compile_ordering_sql(ordering, models, dialect, qualified=qualified)
            for ordering in state.orderings
        )
        sql_parts.append(f"ORDER BY {order_by}")
    if state.limit_value is not None:
        sql_parts.append(f"LIMIT {dialect.placeholder}")
        params = (*params, state.limit_value)
    if state.offset_value is not None:
        if state.limit_value is None:
            sql_parts.append("LIMIT -1")
        sql_parts.append(f"OFFSET {dialect.placeholder}")
        params = (*params, state.offset_value)
    return " ".join(sql_parts), params


def compile_select_sql_for_dialect(
    query: AnySelectQuery,
    dialect: QueryDialect,
) -> tuple[str, tuple[object, ...]]:
    """Compile a select query into backend Dialect SQL."""

    return _compile_select_state(query.state, dialect)


def _materialize_join_row(
    state: _SelectState,
    row: Sequence[object],
    *,
    backend: StorageBackend,
) -> tuple[object, ...]:
    """Split one joined row into a Fetched model per table, in join order.

    A left-joined table whose columns are all NULL produced no matching row, so
    its tuple slot is materialized as None rather than a model.
    """

    elements: list[object] = []
    offset = 0
    for index, model in enumerate(state.result_models()):
        columns = require_model_columns(model)
        width = len(columns)
        chunk = row[offset : offset + width]
        offset += width
        is_left_join = index > 0 and state.joins[index - 1].join_type == "LEFT"
        if is_left_join and all(value is None for value in chunk):
            elements.append(None)
            continue
        values = {name: chunk[position] for position, name in enumerate(columns)}
        elements.append(decode_model_row(model, values, backend=backend))
    return tuple(elements)


def materialize_select_row_for_backend(
    query: AnySelectQuery,
    row: Sequence[object],
    *,
    backend: StorageBackend,
) -> object:
    """Materialize one database row into the select query's result shape.

    Shared by every backend: a join select decodes the row into a tuple of
    Fetched models (one per joined table), a model select decodes the whole row
    into a Fetched Model, a single-column select returns one decoded scalar, and
    a multi-column select returns a tuple of decoded scalars in order.
    """

    state = query.state
    assert len(row) == len(state.fields), (  # noqa: S101
        "database row shape did not match select query"
    )
    if state.joins and state.returns_model:
        return _materialize_join_row(state, row, backend=backend)
    if state.returns_model:
        values = {
            _require_column_name(column): row[index]
            for index, column in enumerate(state.fields)
        }
        return decode_model_row(state.model, values, backend=backend)
    decoded_values = tuple(
        column.decode(row[index], backend=backend)
        for index, column in enumerate(state.fields)
    )
    if len(decoded_values) == 1:
        return decoded_values[0]
    return decoded_values


def compile_write_sql_for_dialect(
    query: object,
    dialect: QueryDialect,
) -> tuple[str, tuple[object, ...]]:
    """Compile a write query into backend Dialect SQL."""

    if isinstance(query, InsertQuery):
        return _compile_insert_sql(cast("InsertQuery[Any]", query), dialect)
    if isinstance(query, UpdateQuery):
        return _compile_update_sql(cast("UpdateQuery[Any]", query), dialect)
    if isinstance(query, DeleteQuery):
        return _compile_delete_sql(cast("DeleteQuery[Any]", query), dialect)
    msg = "execute requires a write query"
    raise QueryCompilationError(msg)


@overload
def select[SelectOwnerT: Table[Any], ReadModelT: Table[Any]](
    model: _SelectableModelClass[SelectOwnerT, ReadModelT],
    /,
) -> SelectModelQuery[SelectOwnerT, ReadModelT]: ...


# Projection overloads capture each column's owner separately. `ScopeT` is
# seeded with the FIRST column's table (the implicit `FROM` anchor); `RefT` is
# the union of every column's owner. The dual union is what lets the fetch
# overloads reject referencing a table that was never joined.
@overload
def select[Owner1T: Table[Any], T1](
    field1: Attr[Any, Any, Owner1T, Any, T1],
    /,
) -> SelectValueQuery[Owner1T, Owner1T, T1]: ...


@overload
def select[Owner1T: Table[Any], T1, Owner2T: Table[Any], T2](
    field1: Attr[Any, Any, Owner1T, Any, T1],
    field2: Attr[Any, Any, Owner2T, Any, T2],
    /,
) -> SelectTupleQuery[Owner1T, Owner1T | Owner2T, T1, T2]: ...


@overload
def select[
    Owner1T: Table[Any],
    T1,
    Owner2T: Table[Any],
    T2,
    Owner3T: Table[Any],
    T3,
](
    field1: Attr[Any, Any, Owner1T, Any, T1],
    field2: Attr[Any, Any, Owner2T, Any, T2],
    field3: Attr[Any, Any, Owner3T, Any, T3],
    /,
) -> SelectTupleQuery[Owner1T, Owner1T | Owner2T | Owner3T, T1, T2, T3]: ...


def select(*args: object) -> object:
    if len(args) == 0:
        msg = "select requires a model or field"
        raise QueryConstructionError(msg)
    if any(isinstance(argument, type) for argument in args):
        if len(args) != 1 or not isinstance(args[0], type):
            msg = "mixed model and field selection is invalid"
            raise QueryConstructionError(msg)
        model = cast("type[Table[Any]]", args[0])
        try:
            columns = require_model_columns(model)
        except ModelDeclarationError as error:
            msg = "select requires a table model"
            raise QueryConstructionError(msg) from error
        state = _SelectState(
            model=model,
            fields=tuple(columns.values()),
            returns_model=True,
        )
        return SelectModelQuery[Any, Any](state)
    fields = tuple(_require_field(argument) for argument in args)
    # The first projected column's table is the implicit FROM anchor; columns
    # from other tables must be brought into scope with join()/left_join(),
    # which the dual-union scope check enforces statically.
    model = _require_column_model(fields[0])
    state = _SelectState(model=model, fields=fields)
    if len(fields) == 1:
        return SelectValueQuery[Any, Any, Any](state)
    return SelectTupleQuery[Any, Any, *tuple[Any, ...]](state)


def insert[ModelT: Table[Any]](row: ModelT, /) -> InsertQuery[ModelT]:
    return InsertQuery(row)


def update[ModelT: Table[Any]](model: type[ModelT], /) -> UpdateQuery[ModelT]:
    try:
        _ = require_model_columns(model)
    except ModelDeclarationError as error:
        msg = "update requires a table model"
        raise QueryConstructionError(msg) from error
    return UpdateQuery(_UpdateState(model=cast("type[Table[Any]]", model)))


def delete[ModelT: Table[Any]](model: type[ModelT], /) -> DeleteQuery[ModelT]:
    try:
        _ = require_model_columns(model)
    except ModelDeclarationError as error:
        msg = "delete requires a table model"
        raise QueryConstructionError(msg) from error
    return DeleteQuery(_DeleteState(model=cast("type[Table[Any]]", model)))

"""Query Builder objects and factory functions.

The Query Builder produces immutable query state (see :mod:`snekql._query_state`).
Query Compilation (:mod:`snekql._query_compile`) lowers that state to backend
Dialect SQL, and Materialization (:mod:`snekql._query_materialize`) decodes
result rows; this module owns only the typed construction surface.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import replace
from typing import Any, Protocol, Self, TypeVar, TypeVarTuple, cast, overload

from snekql._dialect_expr import DialectSelectable
from snekql._query_state import (
    DeleteState,
    InsertState,
    JoinSpec,
    JoinType,
    SelectState,
    UpdateState,
    ensure_assignment_targets_model,
    ensure_having_targets,
    ensure_ordering_targets_models,
    ensure_predicate_targets_models,
    require_column_model,
    require_field,
    require_insert_model,
    require_returning_fields,
    require_selectable,
    require_single_column_subquery,
    require_subquery_state,
    selectable_owner_model,
)
from snekql.errors import ModelDeclarationError, QueryConstructionError
from snekql.expressions import (
    Aggregate,
    Assignment,
    JoinOn,
    OrderBy,
    Predicate,
    Scalar,
)
from snekql.model import Table, require_model_columns
from snekql.storage import Attr
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


class _SelectableModelClass(Protocol[SelectableOwnerT_co, SelectableReadT_co]):
    """Structural type for model classes accepted by `select(Model)`.

    The protocol lets pyright connect the writable owner model type with the
    fetched read model type exposed by table model classes.
    """

    @classmethod
    def __owner_type__(cls) -> type[SelectableOwnerT_co]: ...

    @classmethod
    def __read_type__(cls) -> type[SelectableReadT_co]: ...


class _InsertableModel(Protocol[SelectableOwnerT_co, SelectableReadT_co]):
    """Structural type for pending model instances accepted by `insert(row)`.

    A pending model instance exposes its own writable owner type and the fetched
    read type its class declares, so `insert` can thread both through the query:
    the owner anchors backend validation, and the read type is what a
    `.returning()` write yields. The protocol matches an instance (not a class),
    so a `User[Pending]` value binds owner to `User[Pending]` and read to
    `User[Fetched]`.
    """

    @classmethod
    def __owner_type__(cls) -> type[SelectableOwnerT_co]: ...

    @classmethod
    def __read_type__(cls) -> type[SelectableReadT_co]: ...


class _BaseSelectQuery:
    """Immutable select-state plumbing shared by every select query.

    Holds the state object and the transitions that never change a query's
    generic shape (`all`, `limit`, `offset`). Subclasses add the typed surface
    (`where`/`order_by`/`join`) whose return types depend on their parameters.
    """

    state: SelectState

    def __init__(self, state: SelectState | None = None) -> None:
        if state is None:
            state = _empty_select_state()
        self.state = state

    def _replace_state(self, state: SelectState) -> Self:
        return type(self)(state)

    def all(self) -> Self:
        """Select every row explicitly instead of providing predicates."""

        state = _select_all(self.state)
        if state is self.state:
            return self
        return self._replace_state(state)

    def distinct(self) -> Self:
        """Collapse duplicate rows by emitting ``SELECT DISTINCT``."""

        state = _select_distinct(self.state)
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

    def __subquery_value_type__(self) -> T:
        """Typing-only witness of this select's single projected value type.

        Lets a one-column select satisfy the ``_ColumnSubquery`` protocol that
        ``in_subquery``/``not_in_subquery`` use, without importing the query
        layer into the expressions layer. Never called at runtime.
        """

        raise NotImplementedError

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

    def group_by[RefOwnerT: Table[Any]](
        self,
        *columns: Attr[Any, Any, RefOwnerT, Any, Any],
    ) -> SelectValueQuery[ScopeT, RefT | RefOwnerT, T]:
        """Group rows by columns, widening the referenced-table union by them."""

        return cast(
            "SelectValueQuery[ScopeT, RefT | RefOwnerT, T]",
            SelectValueQuery[Any, Any, T](_select_group_by(self.state, columns)),
        )

    def having[RefOwnerT: Table[Any]](
        self,
        *predicates: Predicate[RefOwnerT],
    ) -> SelectValueQuery[ScopeT, RefT | RefOwnerT, T]:
        """Filter groups by aggregate or grouped column, widening the union."""

        return cast(
            "SelectValueQuery[ScopeT, RefT | RefOwnerT, T]",
            SelectValueQuery[Any, Any, T](_select_having(self.state, predicates)),
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
        """Left-join another table into the scope without changing the result.

        Nullability caveat: a projected column taken from the nullable side keeps
        its non-optional read type even though an unmatched row yields `None` at
        runtime. Use a model-select left join when you need that nullability in
        the types.
        """

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

    def group_by[RefOwnerT: Table[Any]](
        self,
        *columns: Attr[Any, Any, RefOwnerT, Any, Any],
    ) -> SelectTupleQuery[ScopeT, RefT | RefOwnerT, *Ts]:
        """Group rows by columns, widening the referenced-table union by them."""

        return cast(
            "SelectTupleQuery[ScopeT, RefT | RefOwnerT, *Ts]",
            SelectTupleQuery[Any, Any, *Ts](_select_group_by(self.state, columns)),
        )

    def having[RefOwnerT: Table[Any]](
        self,
        *predicates: Predicate[RefOwnerT],
    ) -> SelectTupleQuery[ScopeT, RefT | RefOwnerT, *Ts]:
        """Filter groups by aggregate or grouped column, widening the union."""

        return cast(
            "SelectTupleQuery[ScopeT, RefT | RefOwnerT, *Ts]",
            SelectTupleQuery[Any, Any, *Ts](_select_having(self.state, predicates)),
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
        """Left-join another table into the scope without changing the result.

        Nullability caveat: a projected column taken from the nullable side keeps
        its non-optional read type even though an unmatched row yields `None` at
        runtime. Use a model-select left join when you need that nullability in
        the types.
        """

        return cast(
            "SelectTupleQuery[ScopeT | LeftT | RightT, RefT, *Ts]",
            SelectTupleQuery[Any, Any, *Ts](
                _select_join(self.state, model, on, "LEFT", project=True),
            ),
        )


class _BaseInsertQuery:
    """Immutable insert-state plumbing shared by every insert query variant."""

    state: InsertState

    def __init__(self, state: InsertState) -> None:
        self.state = state


class InsertQuery[OwnerT: Table[Any], ReadT: Table[Any]](_BaseInsertQuery):
    """Immutable insert statement for one pending table model instance."""

    @overload
    def returning(self) -> InsertReturningQuery[OwnerT, ReadT]: ...
    @overload
    def returning(
        self,
        field1: Attr[Any, Any, Any, Any, T1],
        /,
    ) -> InsertReturningValueQuery[OwnerT, T1]: ...
    @overload
    def returning(
        self,
        field1: Attr[Any, Any, Any, Any, T1],
        field2: Attr[Any, Any, Any, Any, T2],
        /,
    ) -> InsertReturningTupleQuery[OwnerT, T1, T2]: ...
    @overload
    def returning(
        self,
        field1: Attr[Any, Any, Any, Any, T1],
        field2: Attr[Any, Any, Any, Any, T2],
        field3: Attr[Any, Any, Any, Any, T3],
        /,
    ) -> InsertReturningTupleQuery[OwnerT, T1, T2, T3]: ...
    def returning(self, *fields: object) -> object:
        """Recover columns the database produced for the inserted row.

        With no arguments the inserted row comes back as a Fetched model. Naming
        columns instead projects only those: one column yields its decoded scalar,
        several yield a tuple in the order given.
        """

        return _insert_returning(
            self.state,
            fields,
            model_query=InsertReturningQuery[OwnerT, ReadT],
            value_query=InsertReturningValueQuery[Any, Any],
            tuple_query=InsertReturningTupleQuery[Any, *tuple[Any, ...]],
        )


class InsertManyQuery[OwnerT: Table[Any], ReadT: Table[Any]](_BaseInsertQuery):
    """Immutable bulk insert statement for several pending model instances."""

    @overload
    def returning(self) -> InsertManyReturningQuery[OwnerT, ReadT]: ...
    @overload
    def returning(
        self,
        field1: Attr[Any, Any, Any, Any, T1],
        /,
    ) -> InsertManyReturningValueQuery[OwnerT, T1]: ...
    @overload
    def returning(
        self,
        field1: Attr[Any, Any, Any, Any, T1],
        field2: Attr[Any, Any, Any, Any, T2],
        /,
    ) -> InsertManyReturningTupleQuery[OwnerT, T1, T2]: ...
    @overload
    def returning(
        self,
        field1: Attr[Any, Any, Any, Any, T1],
        field2: Attr[Any, Any, Any, Any, T2],
        field3: Attr[Any, Any, Any, Any, T3],
        /,
    ) -> InsertManyReturningTupleQuery[OwnerT, T1, T2, T3]: ...
    def returning(self, *fields: object) -> object:
        """Recover columns the database produced for each inserted row.

        With no arguments each inserted row comes back as a Fetched model. Naming
        columns instead projects only those: one column yields a list of decoded
        scalars, several yield a list of tuples in the order given.
        """

        return _insert_returning(
            self.state,
            fields,
            model_query=InsertManyReturningQuery[OwnerT, ReadT],
            value_query=InsertManyReturningValueQuery[Any, Any],
            tuple_query=InsertManyReturningTupleQuery[Any, *tuple[Any, ...]],
        )


class InsertReturningQuery[OwnerT: Table[Any], ReadT: Table[Any]](_BaseInsertQuery):
    """Single insert whose execution yields the Fetched model it produced."""


class InsertManyReturningQuery[OwnerT: Table[Any], ReadT: Table[Any]](_BaseInsertQuery):
    """Bulk insert whose execution yields the Fetched models it produced."""


class InsertReturningValueQuery[OwnerT: Table[Any], T](_BaseInsertQuery):
    """Single insert whose execution yields one decoded RETURNING column."""


class InsertReturningTupleQuery[OwnerT: Table[Any], *Ts](_BaseInsertQuery):
    """Single insert whose execution yields a tuple of RETURNING columns."""


class InsertManyReturningValueQuery[OwnerT: Table[Any], T](_BaseInsertQuery):
    """Bulk insert whose execution yields one decoded RETURNING column per row."""


class InsertManyReturningTupleQuery[OwnerT: Table[Any], *Ts](_BaseInsertQuery):
    """Bulk insert whose execution yields a tuple of RETURNING columns per row."""


def _insert_returning(
    state: InsertState,
    fields: tuple[object, ...],
    *,
    model_query: type[_BaseInsertQuery],
    value_query: type[_BaseInsertQuery],
    tuple_query: type[_BaseInsertQuery],
) -> object:
    """Build the right returning query for a (possibly empty) column projection.

    No columns keeps the whole-row model projection; a single column becomes a
    value query, several columns a tuple query. The query classes are passed in
    so the single-insert and bulk builders share one transition.
    """

    if not fields:
        return model_query(replace(state, returning=True))
    selectables = require_returning_fields(state, fields)
    projected = replace(state, returning=True, returning_fields=selectables)
    if len(selectables) == 1:
        return value_query(projected)
    return tuple_query(projected)


type AnyInsertQuery = (
    InsertQuery[Any, Any]
    | InsertManyQuery[Any, Any]
    | InsertReturningQuery[Any, Any]
    | InsertManyReturningQuery[Any, Any]
    | InsertReturningValueQuery[Any, Any]
    | InsertReturningTupleQuery[Any, *tuple[Any, ...]]
    | InsertManyReturningValueQuery[Any, Any]
    | InsertManyReturningTupleQuery[Any, *tuple[Any, ...]]
)


type AnyWriteQuery = AnyInsertQuery | UpdateQuery[Any] | DeleteQuery[Any]


class UpdateQuery[ModelT: Table[Any]]:
    """Immutable update statement for one table model."""

    state: UpdateState

    def __init__(self, state: UpdateState | None = None) -> None:
        if state is None:
            state = UpdateState(model=Table[Any])
        self.state: UpdateState = state

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

    state: DeleteState

    def __init__(self, state: DeleteState | None = None) -> None:
        if state is None:
            state = DeleteState(model=Table[Any])
        self.state: DeleteState = state

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


def _empty_select_state() -> SelectState:
    return SelectState(model=Table[Any], fields=())


def _select_all(state: SelectState) -> SelectState:
    if state.predicates:
        msg = "all() cannot be combined with where()"
        raise QueryConstructionError(msg)
    if state.explicit_all:
        return state
    return replace(state, explicit_all=True)


def _select_distinct(state: SelectState) -> SelectState:
    if state.distinct:
        return state
    return replace(state, distinct=True)


def _select_where(
    state: SelectState,
    predicates: tuple[Predicate[Any], ...],
) -> SelectState:
    if not predicates:
        msg = "where() requires at least one predicate"
        raise QueryConstructionError(msg)
    if state.explicit_all:
        msg = "where() cannot be combined with all()"
        raise QueryConstructionError(msg)
    for predicate in predicates:
        ensure_predicate_targets_models(predicate, state.result_models())
    return replace(state, predicates=(*state.predicates, *predicates))


def _select_order_by(
    state: SelectState,
    orderings: tuple[OrderBy[Any], ...],
) -> SelectState:
    if not orderings:
        msg = "order_by() requires at least one ordering"
        raise QueryConstructionError(msg)
    for ordering in orderings:
        ensure_ordering_targets_models(ordering, state.result_models())
    return replace(state, orderings=(*state.orderings, *orderings))


def _select_group_by(
    state: SelectState,
    columns: tuple[Attr[Any, Any, Any, Any, Any], ...],
) -> SelectState:
    if not columns:
        msg = "group_by() requires at least one column"
        raise QueryConstructionError(msg)
    grouped = tuple(require_field(column) for column in columns)
    models = state.result_models()
    for column in grouped:
        if require_column_model(column) not in models:
            msg = "group_by references a table that is not in the query"
            raise QueryConstructionError(msg)
    return replace(state, groupings=(*state.groupings, *grouped))


def _select_having(
    state: SelectState,
    predicates: tuple[Predicate[Any], ...],
) -> SelectState:
    if not predicates:
        msg = "having() requires at least one predicate"
        raise QueryConstructionError(msg)
    for predicate in predicates:
        ensure_having_targets(predicate, state)
    return replace(state, having=(*state.having, *predicates))


def _select_join(
    state: SelectState,
    model: object,
    on: object,
    join_type: JoinType,
    *,
    project: bool = False,
) -> SelectState:
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
    left_column = require_field(condition.left_column)
    right_column = require_field(condition.right_column)
    related = {require_column_model(left_column), require_column_model(right_column)}
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
    spec = JoinSpec(
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


def _select_limit(state: SelectState, value: NonNegativeInt) -> SelectState:
    return replace(state, limit_value=value)


def _select_offset(state: SelectState, value: NonNegativeInt) -> SelectState:
    return replace(state, offset_value=value)


def _update_all(state: UpdateState) -> UpdateState:
    if state.predicates:
        msg = "all() cannot be combined with where()"
        raise QueryConstructionError(msg)
    if state.explicit_all:
        return state
    return replace(state, explicit_all=True)


def _update_set(
    state: UpdateState,
    assignments: tuple[Assignment[Any], ...],
) -> UpdateState:
    if not assignments:
        msg = "set() requires at least one assignment"
        raise QueryConstructionError(msg)
    for assignment in assignments:
        ensure_assignment_targets_model(assignment, state.model)
    return replace(state, assignments=(*state.assignments, *assignments))


def _update_where(
    state: UpdateState,
    predicates: tuple[Predicate[Any], ...],
) -> UpdateState:
    if not predicates:
        msg = "where() requires at least one predicate"
        raise QueryConstructionError(msg)
    if state.explicit_all:
        msg = "where() cannot be combined with all()"
        raise QueryConstructionError(msg)
    for predicate in predicates:
        ensure_predicate_targets_models(predicate, (state.model,))
    return replace(state, predicates=(*state.predicates, *predicates))


def _delete_all(state: DeleteState) -> DeleteState:
    if state.predicates:
        msg = "all() cannot be combined with where()"
        raise QueryConstructionError(msg)
    if state.explicit_all:
        return state
    return replace(state, explicit_all=True)


def _delete_where(
    state: DeleteState,
    predicates: tuple[Predicate[Any], ...],
) -> DeleteState:
    if not predicates:
        msg = "where() requires at least one predicate"
        raise QueryConstructionError(msg)
    if state.explicit_all:
        msg = "where() cannot be combined with all()"
        raise QueryConstructionError(msg)
    for predicate in predicates:
        ensure_predicate_targets_models(predicate, (state.model,))
    return replace(state, predicates=(*state.predicates, *predicates))


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


# A lone aggregate projects one scalar over the (grouped or whole-table) set; it
# reuses the value-select machinery because the aggregate carries its result `T`.
@overload
def select[Owner1T: Table[Any], T1](
    field1: Aggregate[Owner1T, T1],
    /,
) -> SelectValueQuery[Owner1T, Owner1T, T1]: ...


# A lone scalar subquery projects its single value; its owner is type-erased
# (a scalar correlates to an enclosing scope rather than anchoring one).
@overload
def select[Owner1T: Table[Any], T1](
    field1: Scalar[Owner1T, T1],
    /,
) -> SelectValueQuery[Owner1T, Owner1T, T1]: ...


# A lone open-AST dialect expression projects its single decoded value; the
# result type `T1` flows from the leaf selectable, and its owning table is
# type-erased (the core never names the leaf, so scope is checked at runtime).
@overload
def select[T1](
    field1: DialectSelectable[T1],
    /,
) -> SelectValueQuery[Any, Any, T1]: ...


# Multi-column projections accept a column, an aggregate, or a scalar subquery in
# each slot: a single union arm per position binds the same `OwnerT`/`T` whichever
# it is, so grouped projections (`select(User.country, count(User.id))`) and
# scalar projections (`select(User.id, scalar(...))`) reuse the tuple machinery
# without a combinatorial overload explosion.
@overload
def select[Owner1T: Table[Any], T1, Owner2T: Table[Any], T2](
    field1: Attr[Any, Any, Owner1T, Any, T1]
    | Aggregate[Owner1T, T1]
    | Scalar[Owner1T, T1]
    | DialectSelectable[T1],
    field2: Attr[Any, Any, Owner2T, Any, T2]
    | Aggregate[Owner2T, T2]
    | Scalar[Owner2T, T2]
    | DialectSelectable[T2],
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
    field1: Attr[Any, Any, Owner1T, Any, T1]
    | Aggregate[Owner1T, T1]
    | Scalar[Owner1T, T1]
    | DialectSelectable[T1],
    field2: Attr[Any, Any, Owner2T, Any, T2]
    | Aggregate[Owner2T, T2]
    | Scalar[Owner2T, T2]
    | DialectSelectable[T2],
    field3: Attr[Any, Any, Owner3T, Any, T3]
    | Aggregate[Owner3T, T3]
    | Scalar[Owner3T, T3]
    | DialectSelectable[T3],
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
        state = SelectState(
            model=model,
            fields=tuple(columns.values()),
            returns_model=True,
        )
        return SelectModelQuery[Any, Any](state)
    fields = tuple(require_selectable(argument) for argument in args)
    # The first projected column/aggregate's table is the implicit FROM anchor;
    # columns from other tables must be brought into scope with
    # join()/left_join(), which the dual-union scope check enforces statically. A
    # scalar subquery has no owning table, so it can never anchor the FROM.
    anchor = next(
        (field for field in fields if not isinstance(field, Scalar)),
        None,
    )
    if anchor is None:
        msg = "a projection must select at least one column or aggregate"
        raise QueryConstructionError(msg)
    model = selectable_owner_model(anchor)
    state = SelectState(model=model, fields=fields)
    if len(fields) == 1:
        return SelectValueQuery[Any, Any, Any](state)
    return SelectTupleQuery[Any, Any, *tuple[Any, ...]](state)


def exists(subquery: AnySelectQuery, /) -> Predicate[Any]:
    """Build an ``EXISTS (subquery)`` predicate.

    The subquery's projection is irrelevant to ``EXISTS`` (only whether it yields
    a row), so any select is accepted. A correlated subquery references the outer
    query through a column comparison (e.g. ``Order.user_id.eq_col(User.id)``);
    that correlation is resolved when the enclosing query compiles.
    """

    _ = require_subquery_state(subquery)
    return Predicate(kind="exists", subquery=subquery)


def not_exists(subquery: AnySelectQuery, /) -> Predicate[Any]:
    """Build a ``NOT EXISTS (subquery)`` predicate (see :func:`exists`)."""

    _ = require_subquery_state(subquery)
    return Predicate(kind="not_exists", subquery=subquery)


def scalar[T](subquery: SelectValueQuery[Any, Any, T], /) -> Scalar[Any, T]:
    """Wrap a single-column select as a scalar subquery usable as a value.

    The result is a selectable (projectable alongside columns) and a comparison
    operand (the right side of a ``*_col`` comparison). The subquery must project
    exactly one column and is expected to yield at most one row per evaluation.
    """

    _ = require_single_column_subquery(subquery)
    return Scalar(subquery=subquery)


@overload
def insert[OwnerT: Table[Any], ReadT: Table[Any]](
    row: _InsertableModel[OwnerT, ReadT],
    /,
) -> InsertQuery[OwnerT, ReadT]: ...


@overload
def insert[OwnerT: Table[Any], ReadT: Table[Any]](
    rows: Sequence[_InsertableModel[OwnerT, ReadT]],
    /,
) -> InsertManyQuery[OwnerT, ReadT]: ...


def insert(row_or_rows: object, /) -> object:
    """Build an insert from a single pending model or a sequence of them.

    A single model compiles to one ``INSERT ... VALUES (...)``; a sequence
    compiles to one multi-row ``INSERT ... VALUES (...), (...)`` and is a no-op
    when empty. Call ``.returning()`` on either to get the Fetched model(s) the
    database produced (generated keys, server defaults) back from the write.
    """

    if isinstance(row_or_rows, Sequence):
        rows = tuple(cast("Sequence[Table[Any]]", row_or_rows))
        for row in rows:
            _ = require_insert_model(row)
        return InsertManyQuery[Any, Any](InsertState(rows=rows, multi=True))
    _ = require_insert_model(row_or_rows)
    return InsertQuery[Any, Any](
        InsertState(rows=(cast("Table[Any]", row_or_rows),)),
    )


def update[ModelT: Table[Any]](model: type[ModelT], /) -> UpdateQuery[ModelT]:
    try:
        _ = require_model_columns(model)
    except ModelDeclarationError as error:
        msg = "update requires a table model"
        raise QueryConstructionError(msg) from error
    return UpdateQuery(UpdateState(model=cast("type[Table[Any]]", model)))


def delete[ModelT: Table[Any]](model: type[ModelT], /) -> DeleteQuery[ModelT]:
    try:
        _ = require_model_columns(model)
    except ModelDeclarationError as error:
        msg = "delete requires a table model"
        raise QueryConstructionError(msg) from error
    return DeleteQuery(DeleteState(model=cast("type[Table[Any]]", model)))

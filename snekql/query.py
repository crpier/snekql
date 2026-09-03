"""Query Builder objects and factory functions.

The Query Builder produces immutable query state (see :mod:`snekql._query_state`).
Query Compilation (:mod:`snekql._query_compile`) lowers that state to backend
Dialect SQL, and Materialization (:mod:`snekql._query_materialize`) decodes
result rows; this module owns only the typed construction surface.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import replace
from typing import (
    TYPE_CHECKING,
    Any,
    Never,
    Protocol,
    Self,
    TypeVar,
    TypeVarTuple,
    cast,
    overload,
)

from snekql._dialect_expr import DialectSelectable
from snekql._query_scope import (
    ScopeResolver,
    ensure_assignment_targets_model,
    ensure_grouping_targets_models,
    ensure_having_targets,
    ensure_ordering_targets_models,
    ensure_predicate_targets_models,
)
from snekql._query_state import (
    DeleteState,
    InsertState,
    JoinSpec,
    JoinType,
    SelectState,
    UpdateState,
    require_column_model,
    require_field,
    require_insert_model,
    require_model_returning_fields,
    require_returning_fields,
    require_selectable,
    require_single_column_subquery,
    require_subquery_state,
    selectable_owner_model,
)
from snekql.errors import (
    ModelDeclarationError,
    QueryCompilationError,
    QueryConstructionError,
)
from snekql.expressions import (
    Aggregate,
    Assignment,
    ColumnRef,
    DoNothing,
    DoUpdate,
    ExistencePredicate,
    JoinOn,
    OrderBy,
    Predicate,
    Scalar,
    _Assignment,
    _JoinOn,
    _OrderBy,
    _PredicateNode,
    _require_predicate_node,
    _Scalar,
)
from snekql.model import Pending, Table, require_model_backend, require_model_columns
from snekql.storage import Attr
from snekql.validation import NonNegativeInt, validate_boundary

if TYPE_CHECKING:
    from snekql._query_compile import InspectedQuery

FamilyT_co = TypeVar("FamilyT_co", covariant=True)
ModelT = TypeVar("ModelT", bound=Table[Any])
ReadModelT = TypeVar("ReadModelT", bound=Table[Any])
SelectOwnerT = TypeVar("SelectOwnerT", bound=Table[Any])
OwnerT = TypeVar("OwnerT", bound=Table[Any])
SelectableOwnerT = TypeVar("SelectableOwnerT", bound=Table[Any])
SelectableReadT_co = TypeVar("SelectableReadT_co", bound=Table[Any], covariant=True)
T = TypeVar("T")
T1 = TypeVar("T1")
T2 = TypeVar("T2")
T3 = TypeVar("T3")
Ts = TypeVarTuple("Ts")


class _SelectableModelClass(Protocol[FamilyT_co, SelectableOwnerT, SelectableReadT_co]):
    """Structural type for model classes accepted by `select(Model)`.

    The protocol lets the checker connect the writable owner model type with the
    fetched read model type exposed by table model classes.
    """

    @classmethod
    def __backend_family_type__(cls) -> FamilyT_co: ...

    @classmethod
    def __owner_type__(cls) -> type[SelectableOwnerT]: ...

    @classmethod
    def __owner_invariant__(cls, owner: SelectableOwnerT) -> SelectableOwnerT: ...

    @classmethod
    def __read_type__(cls) -> type[SelectableReadT_co]: ...


class InsertableModel(Protocol[FamilyT_co, SelectableOwnerT, SelectableReadT_co]):
    """Structural type for pending model instances accepted by `insert(row)`.

    A pending model instance exposes its own writable owner type and the fetched
    read type its class declares, so `insert` can thread both through the query:
    the owner anchors backend validation, and the read type is what a
    `.returning()` write yields. The protocol matches an instance (not a class),
    so a `User[Pending]` value binds owner to `User[Pending]` and read to
    `User[Fetched]`.
    """

    @classmethod
    def __backend_family_type__(cls) -> FamilyT_co: ...

    @classmethod
    def __owner_type__(cls) -> type[SelectableOwnerT]: ...

    @classmethod
    def __owner_invariant__(cls, owner: SelectableOwnerT) -> SelectableOwnerT: ...

    @classmethod
    def __read_type__(cls) -> type[SelectableReadT_co]: ...

    def __state_type__(self) -> Pending: ...


class _SqlInspectionMixin:
    """`repr`/`str` that render a built query's own backend Dialect SQL.

    Resolves the Dialect from the query's model backend (see
    :func:`snekql._query_compile.inspect_query_sql`), so a query renders its SQL
    for debugging with no Database. Because immutable builder transitions return
    a fresh query carrying the full accumulated state, ``repr(query)`` of a
    composed ``query = query.where(...)`` shows the final SQL.

    Neither hook raises: a query that is not yet compilable (e.g. a select
    missing ``all()``/``where()``) renders as ``<ClassName incomplete: reason>``.
    The compile helper is imported lazily so this module keeps no load-time
    dependency on Query Compilation (the dependency stays builder -> state <-
    compilation).
    """

    def _inspected_sql(self) -> InspectedQuery:
        # Lazy import so this module carries no load-time dependency on Query
        # Compilation; the dependency stays builder -> state <- compilation.
        from snekql._query_compile import inspect_query_sql  # noqa: PLC0415

        return inspect_query_sql(self)

    def __repr__(self) -> str:
        name = type(self).__name__
        try:
            inspected = self._inspected_sql()
        except QueryCompilationError as reason:
            return f"<{name} incomplete: {reason}>"
        return f"<{name}: {inspected.sql} | params={inspected.params!r}>"

    def __str__(self) -> str:
        name = type(self).__name__
        try:
            inspected = self._inspected_sql()
        except QueryCompilationError as reason:
            return f"<{name} incomplete: {reason}>"
        return (
            "-- parameterized (executes):\n"
            f"{inspected.sql}\n"
            f"-- params: {inspected.params!r}\n"
            "\n"
            "-- inlined literals (approximate, not executed):\n"
            f"{inspected.inlined_sql}"
        )


class _BaseSelectQuery(_SqlInspectionMixin):
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

    @overload
    def where(self, predicate: Predicate[FluentOwnerT], /) -> Self: ...

    @overload
    def where(
        self,
        predicate: Predicate[FluentOwnerT],
        second: Predicate[FluentOwnerT],
        /,
        *predicates: Predicate[FluentOwnerT],
    ) -> Self: ...

    def where(self, *predicates: Predicate[FluentOwnerT]) -> Self:
        """Filter selected rows by AND-combined column predicates."""

        return self._replace_state(_select_where(self.state, predicates))

    @overload
    def order_by(self, ordering: OrderBy[FluentOwnerT], /) -> Self: ...

    @overload
    def order_by(
        self,
        ordering: OrderBy[FluentOwnerT],
        second: OrderBy[FluentOwnerT],
        /,
        *orderings: OrderBy[FluentOwnerT],
    ) -> Self: ...

    def order_by(self, *ordering: OrderBy[FluentOwnerT]) -> Self:
        """Order selected rows by the given column orderings."""

        return self._replace_state(_select_order_by(self.state, ordering))


class _QueryShape[FamilyT, ScopeT, RefT, RowT]:
    """Private nominal carrier for executable select scope and row shape."""

    def _pin_scope(self, scope: ScopeT) -> ScopeT:
        """Keep scope invariant so references cannot widen beyond joined tables."""

        return scope

    def _reference_type(self) -> RefT:
        """Typing-only covariant witness for every referenced table."""

        raise NotImplementedError

    def _row_type(self) -> RowT:
        """Typing-only covariant witness for the materialized row type."""

        raise NotImplementedError


class _OptionalQueryShape[FamilyT, ScopeT, RefT, RowT](
    _QueryShape[FamilyT, ScopeT, RefT, RowT]
):
    """Select shape whose absence is distinct from every possible row value."""


type _Select[FamilyT, RowT] = _QueryShape[FamilyT, Any, Any, RowT]
type Select[RowT] = _Select[Any, RowT]
"""Public annotation for a select query yielding `RowT` per row.

The `Any` scope coordinates deliberately erase private builder state at a stored
query or function boundary. Direct builder calls retain their concrete scope and
reference coordinates, so the Query Runtime can still reject unjoined references.
"""


class SelectModelQuery[FamilyT, SelectOwnerT: Table[Any], ReadModelT: Table[Any]](
    _FluentSelectQuery[SelectOwnerT],
    _OptionalQueryShape[FamilyT, SelectOwnerT, SelectOwnerT, ReadModelT],
):
    """Immutable select query that returns fetched table model instances."""

    @overload
    def join[NewOwnerT: Table[Any], NewReadT: Table[Any]](
        self,
        model: _SelectableModelClass[FamilyT, NewOwnerT, NewReadT],
        on: JoinOn[NewOwnerT, SelectOwnerT],
    ) -> JoinModelQuery[FamilyT, SelectOwnerT | NewOwnerT, ReadModelT, NewReadT]: ...

    @overload
    def join[NewOwnerT: Table[Any], NewReadT: Table[Any]](
        self,
        model: _SelectableModelClass[FamilyT, NewOwnerT, NewReadT],
        on: JoinOn[SelectOwnerT, NewOwnerT],
    ) -> JoinModelQuery[FamilyT, SelectOwnerT | NewOwnerT, ReadModelT, NewReadT]: ...

    def join(
        self,
        model: object,
        on: object,
    ) -> JoinModelQuery[FamilyT, Any, *tuple[Any, ...]]:
        """Inner-join another table, appending its fetched model to each row."""

        return JoinModelQuery[FamilyT, Any, *tuple[Any, ...]](
            _select_join(self.state, model, on, "INNER"),
        )

    @overload
    def left_join[NewOwnerT: Table[Any], NewReadT: Table[Any]](
        self,
        model: _SelectableModelClass[FamilyT, NewOwnerT, NewReadT],
        on: JoinOn[NewOwnerT, SelectOwnerT],
    ) -> JoinModelQuery[
        FamilyT, SelectOwnerT | NewOwnerT, ReadModelT, NewReadT | None
    ]: ...

    @overload
    def left_join[NewOwnerT: Table[Any], NewReadT: Table[Any]](
        self,
        model: _SelectableModelClass[FamilyT, NewOwnerT, NewReadT],
        on: JoinOn[SelectOwnerT, NewOwnerT],
    ) -> JoinModelQuery[
        FamilyT, SelectOwnerT | NewOwnerT, ReadModelT, NewReadT | None
    ]: ...

    def left_join(
        self,
        model: object,
        on: object,
    ) -> JoinModelQuery[FamilyT, Any, *tuple[Any, ...]]:
        """Left-join another table; its fetched model is optional per row."""

        return JoinModelQuery[FamilyT, Any, *tuple[Any, ...]](
            _select_join(self.state, model, on, "LEFT"),
        )


class JoinModelQuery[FamilyT, JoinOwnerT: Table[Any], *ResultTs](
    _FluentSelectQuery[JoinOwnerT],
    _OptionalQueryShape[FamilyT, JoinOwnerT, JoinOwnerT, tuple[*ResultTs]],
):
    """Immutable model-select across joined tables; rows are model tuples.

    `JoinOwnerT` accumulates a union of every joined table's `Pending` owner, so
    `where`/`order_by` accept predicates from any joined table (via the covariant
    `Predicate`) and reject columns from tables not in the query. `*ResultTs`
    accumulates the per-table fetched models: `join` appends `T[Fetched]` and
    `left_join` appends `T[Fetched] | None`.
    """

    @overload
    def join[NewOwnerT: Table[Any], NewReadT: Table[Any]](
        self,
        model: _SelectableModelClass[FamilyT, NewOwnerT, NewReadT],
        on: JoinOn[NewOwnerT, JoinOwnerT],
    ) -> JoinModelQuery[FamilyT, JoinOwnerT | NewOwnerT, *ResultTs, NewReadT]: ...

    @overload
    def join[NewOwnerT: Table[Any], NewReadT: Table[Any]](
        self,
        model: _SelectableModelClass[FamilyT, NewOwnerT, NewReadT],
        on: JoinOn[JoinOwnerT, NewOwnerT],
    ) -> JoinModelQuery[FamilyT, JoinOwnerT | NewOwnerT, *ResultTs, NewReadT]: ...

    def join(
        self,
        model: object,
        on: object,
    ) -> JoinModelQuery[FamilyT, Any, *tuple[Any, ...]]:
        """Inner-join another table, appending its fetched model to each row."""

        return JoinModelQuery[FamilyT, Any, *tuple[Any, ...]](
            _select_join(self.state, model, on, "INNER"),
        )

    @overload
    def left_join[NewOwnerT: Table[Any], NewReadT: Table[Any]](
        self,
        model: _SelectableModelClass[FamilyT, NewOwnerT, NewReadT],
        on: JoinOn[NewOwnerT, JoinOwnerT],
    ) -> JoinModelQuery[
        FamilyT, JoinOwnerT | NewOwnerT, *ResultTs, NewReadT | None
    ]: ...

    @overload
    def left_join[NewOwnerT: Table[Any], NewReadT: Table[Any]](
        self,
        model: _SelectableModelClass[FamilyT, NewOwnerT, NewReadT],
        on: JoinOn[JoinOwnerT, NewOwnerT],
    ) -> JoinModelQuery[
        FamilyT, JoinOwnerT | NewOwnerT, *ResultTs, NewReadT | None
    ]: ...

    def left_join(
        self,
        model: object,
        on: object,
    ) -> JoinModelQuery[FamilyT, Any, *tuple[Any, ...]]:
        """Left-join another table; its fetched model is optional per row."""

        return JoinModelQuery[FamilyT, Any, *tuple[Any, ...]](
            _select_join(self.state, model, on, "LEFT"),
        )


class SelectValueQuery[FamilyT, ScopeT: Table[Any], RefT: Table[Any], T, CompareT = T](
    _BaseSelectQuery,
    _QueryShape[FamilyT, ScopeT, RefT, T],
):
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

    def __subquery_value_type__(self) -> T:
        """Typing-only witness of this select's single projected value type.

        Lets a one-column select satisfy the ``_ColumnSubquery`` protocol that
        ``in_subquery``/``not_in_subquery`` use, without importing the query
        layer into the expressions layer. Never called at runtime.
        """

        raise NotImplementedError

    @overload
    def where[RefOwnerT: Table[Any]](
        self,
        predicate: Predicate[RefOwnerT],
        /,
    ) -> SelectValueQuery[FamilyT, ScopeT, RefT | RefOwnerT, T, CompareT]: ...

    @overload
    def where[RefOwnerT: Table[Any]](
        self,
        predicate: Predicate[RefOwnerT],
        second: Predicate[RefOwnerT],
        /,
        *predicates: Predicate[RefOwnerT],
    ) -> SelectValueQuery[FamilyT, ScopeT, RefT | RefOwnerT, T, CompareT]: ...

    def where[RefOwnerT: Table[Any]](
        self,
        *predicates: Predicate[RefOwnerT],
    ) -> SelectValueQuery[FamilyT, ScopeT, RefT | RefOwnerT, T, CompareT]:
        """Filter rows, widening the referenced-table union by the predicates."""

        return cast(
            "SelectValueQuery[FamilyT, ScopeT, RefT | RefOwnerT, T, CompareT]",
            SelectValueQuery[FamilyT, Any, Any, T, CompareT](
                _select_where(self.state, predicates)
            ),
        )

    @overload
    def order_by[RefOwnerT: Table[Any]](
        self,
        ordering: OrderBy[RefOwnerT],
        /,
    ) -> SelectValueQuery[FamilyT, ScopeT, RefT | RefOwnerT, T, CompareT]: ...

    @overload
    def order_by[RefOwnerT: Table[Any]](
        self,
        ordering: OrderBy[RefOwnerT],
        second: OrderBy[RefOwnerT],
        /,
        *orderings: OrderBy[RefOwnerT],
    ) -> SelectValueQuery[FamilyT, ScopeT, RefT | RefOwnerT, T, CompareT]: ...

    def order_by[RefOwnerT: Table[Any]](
        self,
        *ordering: OrderBy[RefOwnerT],
    ) -> SelectValueQuery[FamilyT, ScopeT, RefT | RefOwnerT, T, CompareT]:
        """Order rows, widening the referenced-table union by the orderings."""

        return cast(
            "SelectValueQuery[FamilyT, ScopeT, RefT | RefOwnerT, T, CompareT]",
            SelectValueQuery[FamilyT, Any, Any, T, CompareT](
                _select_order_by(self.state, ordering)
            ),
        )

    @overload
    def group_by[RefOwnerT: Table[Any]](
        self,
        column: Attr[Any, Any, RefOwnerT, Any, Any],
        /,
    ) -> SelectValueQuery[FamilyT, ScopeT, RefT | RefOwnerT, T, CompareT]: ...

    @overload
    def group_by[RefOwnerT: Table[Any]](
        self,
        column: Attr[Any, Any, RefOwnerT, Any, Any],
        second: Attr[Any, Any, RefOwnerT, Any, Any],
        /,
        *columns: Attr[Any, Any, RefOwnerT, Any, Any],
    ) -> SelectValueQuery[FamilyT, ScopeT, RefT | RefOwnerT, T, CompareT]: ...

    def group_by[RefOwnerT: Table[Any]](
        self,
        *columns: Attr[Any, Any, RefOwnerT, Any, Any],
    ) -> SelectValueQuery[FamilyT, ScopeT, RefT | RefOwnerT, T, CompareT]:
        """Group rows by columns, widening the referenced-table union by them."""

        return cast(
            "SelectValueQuery[FamilyT, ScopeT, RefT | RefOwnerT, T, CompareT]",
            SelectValueQuery[FamilyT, Any, Any, T, CompareT](
                _select_group_by(self.state, columns)
            ),
        )

    @overload
    def having[RefOwnerT: Table[Any]](
        self,
        predicate: Predicate[RefOwnerT],
        /,
    ) -> SelectValueQuery[FamilyT, ScopeT, RefT | RefOwnerT, T, CompareT]: ...

    @overload
    def having[RefOwnerT: Table[Any]](
        self,
        predicate: Predicate[RefOwnerT],
        second: Predicate[RefOwnerT],
        /,
        *predicates: Predicate[RefOwnerT],
    ) -> SelectValueQuery[FamilyT, ScopeT, RefT | RefOwnerT, T, CompareT]: ...

    def having[RefOwnerT: Table[Any]](
        self,
        *predicates: Predicate[RefOwnerT],
    ) -> SelectValueQuery[FamilyT, ScopeT, RefT | RefOwnerT, T, CompareT]:
        """Filter groups by aggregate or grouped column, widening the union."""

        return cast(
            "SelectValueQuery[FamilyT, ScopeT, RefT | RefOwnerT, T, CompareT]",
            SelectValueQuery[FamilyT, Any, Any, T, CompareT](
                _select_having(self.state, predicates)
            ),
        )

    @overload
    def join[NewOwnerT: Table[Any], NewReadT: Table[Any]](
        self,
        model: _SelectableModelClass[FamilyT, NewOwnerT, NewReadT],
        on: JoinOn[NewOwnerT, ScopeT],
    ) -> SelectValueQuery[FamilyT, ScopeT | NewOwnerT, RefT, T, CompareT]: ...

    @overload
    def join[NewOwnerT: Table[Any], NewReadT: Table[Any]](
        self,
        model: _SelectableModelClass[FamilyT, NewOwnerT, NewReadT],
        on: JoinOn[ScopeT, NewOwnerT],
    ) -> SelectValueQuery[FamilyT, ScopeT | NewOwnerT, RefT, T, CompareT]: ...

    def join(
        self,
        model: object,
        on: object,
    ) -> SelectValueQuery[FamilyT, Any, Any, T, CompareT]:
        """Inner-join another table into the scope without changing the result."""

        return SelectValueQuery[FamilyT, Any, Any, T, CompareT](
            _select_join(self.state, model, on, "INNER", project=True),
        )

    def left_join(
        self,
        model: Never,
        on: Never,
    ) -> Never:
        """Reject projection left joins whose nullable result cannot be typed."""

        del model, on
        msg = "projection left_join is not supported; select models instead"
        raise QueryConstructionError(msg)


class SelectTupleQuery[FamilyT, ScopeT: Table[Any], RefT: Table[Any], *Ts](
    _BaseSelectQuery,
    _OptionalQueryShape[FamilyT, ScopeT, RefT, tuple[*Ts]],
):
    """Projection select of several columns; fetch yields a tuple per row.

    Carries the same dual-union scope check as `SelectValueQuery` (see its
    docstring): `ScopeT` is the joined FROM graph, `RefT` is every referenced
    table, and the fetch overloads force `RefT <: ScopeT`. `*Ts` is the fixed
    tuple of projected read types, unchanged by joins -- a join only declares
    how tables connect, never the result shape.
    """

    @overload
    def where[RefOwnerT: Table[Any]](
        self,
        predicate: Predicate[RefOwnerT],
        /,
    ) -> SelectTupleQuery[FamilyT, ScopeT, RefT | RefOwnerT, *Ts]: ...

    @overload
    def where[RefOwnerT: Table[Any]](
        self,
        predicate: Predicate[RefOwnerT],
        second: Predicate[RefOwnerT],
        /,
        *predicates: Predicate[RefOwnerT],
    ) -> SelectTupleQuery[FamilyT, ScopeT, RefT | RefOwnerT, *Ts]: ...

    def where[RefOwnerT: Table[Any]](
        self,
        *predicates: Predicate[RefOwnerT],
    ) -> SelectTupleQuery[FamilyT, ScopeT, RefT | RefOwnerT, *Ts]:
        """Filter rows, widening the referenced-table union by the predicates."""

        return cast(
            "SelectTupleQuery[FamilyT, ScopeT, RefT | RefOwnerT, *Ts]",
            SelectTupleQuery[FamilyT, Any, Any, *Ts](
                _select_where(self.state, predicates)
            ),
        )

    @overload
    def order_by[RefOwnerT: Table[Any]](
        self,
        ordering: OrderBy[RefOwnerT],
        /,
    ) -> SelectTupleQuery[FamilyT, ScopeT, RefT | RefOwnerT, *Ts]: ...

    @overload
    def order_by[RefOwnerT: Table[Any]](
        self,
        ordering: OrderBy[RefOwnerT],
        second: OrderBy[RefOwnerT],
        /,
        *orderings: OrderBy[RefOwnerT],
    ) -> SelectTupleQuery[FamilyT, ScopeT, RefT | RefOwnerT, *Ts]: ...

    def order_by[RefOwnerT: Table[Any]](
        self,
        *ordering: OrderBy[RefOwnerT],
    ) -> SelectTupleQuery[FamilyT, ScopeT, RefT | RefOwnerT, *Ts]:
        """Order rows, widening the referenced-table union by the orderings."""

        return cast(
            "SelectTupleQuery[FamilyT, ScopeT, RefT | RefOwnerT, *Ts]",
            SelectTupleQuery[FamilyT, Any, Any, *Ts](
                _select_order_by(self.state, ordering)
            ),
        )

    @overload
    def group_by[RefOwnerT: Table[Any]](
        self,
        column: Attr[Any, Any, RefOwnerT, Any, Any],
        /,
    ) -> SelectTupleQuery[FamilyT, ScopeT, RefT | RefOwnerT, *Ts]: ...

    @overload
    def group_by[RefOwnerT: Table[Any]](
        self,
        column: Attr[Any, Any, RefOwnerT, Any, Any],
        second: Attr[Any, Any, RefOwnerT, Any, Any],
        /,
        *columns: Attr[Any, Any, RefOwnerT, Any, Any],
    ) -> SelectTupleQuery[FamilyT, ScopeT, RefT | RefOwnerT, *Ts]: ...

    def group_by[RefOwnerT: Table[Any]](
        self,
        *columns: Attr[Any, Any, RefOwnerT, Any, Any],
    ) -> SelectTupleQuery[FamilyT, ScopeT, RefT | RefOwnerT, *Ts]:
        """Group rows by columns, widening the referenced-table union by them."""

        return cast(
            "SelectTupleQuery[FamilyT, ScopeT, RefT | RefOwnerT, *Ts]",
            SelectTupleQuery[FamilyT, Any, Any, *Ts](
                _select_group_by(self.state, columns)
            ),
        )

    @overload
    def having[RefOwnerT: Table[Any]](
        self,
        predicate: Predicate[RefOwnerT],
        /,
    ) -> SelectTupleQuery[FamilyT, ScopeT, RefT | RefOwnerT, *Ts]: ...

    @overload
    def having[RefOwnerT: Table[Any]](
        self,
        predicate: Predicate[RefOwnerT],
        second: Predicate[RefOwnerT],
        /,
        *predicates: Predicate[RefOwnerT],
    ) -> SelectTupleQuery[FamilyT, ScopeT, RefT | RefOwnerT, *Ts]: ...

    def having[RefOwnerT: Table[Any]](
        self,
        *predicates: Predicate[RefOwnerT],
    ) -> SelectTupleQuery[FamilyT, ScopeT, RefT | RefOwnerT, *Ts]:
        """Filter groups by aggregate or grouped column, widening the union."""

        return cast(
            "SelectTupleQuery[FamilyT, ScopeT, RefT | RefOwnerT, *Ts]",
            SelectTupleQuery[FamilyT, Any, Any, *Ts](
                _select_having(self.state, predicates)
            ),
        )

    @overload
    def join[NewOwnerT: Table[Any], NewReadT: Table[Any]](
        self,
        model: _SelectableModelClass[FamilyT, NewOwnerT, NewReadT],
        on: JoinOn[NewOwnerT, ScopeT],
    ) -> SelectTupleQuery[FamilyT, ScopeT | NewOwnerT, RefT, *Ts]: ...

    @overload
    def join[NewOwnerT: Table[Any], NewReadT: Table[Any]](
        self,
        model: _SelectableModelClass[FamilyT, NewOwnerT, NewReadT],
        on: JoinOn[ScopeT, NewOwnerT],
    ) -> SelectTupleQuery[FamilyT, ScopeT | NewOwnerT, RefT, *Ts]: ...

    def join(
        self,
        model: object,
        on: object,
    ) -> SelectTupleQuery[FamilyT, Any, Any, *Ts]:
        """Inner-join another table into the scope without changing the result."""

        return SelectTupleQuery[FamilyT, Any, Any, *Ts](
            _select_join(self.state, model, on, "INNER", project=True),
        )

    def left_join(
        self,
        model: Never,
        on: Never,
    ) -> Never:
        """Reject projection left joins whose nullable result cannot be typed."""

        del model, on
        msg = "projection left_join is not supported; select models instead"
        raise QueryConstructionError(msg)


class _BaseInsertQuery[FamilyT, OwnerT: Table[Any]](_SqlInspectionMixin):
    """Immutable insert-state plumbing shared by every insert query variant."""

    state: InsertState

    def __init__(self, state: InsertState) -> None:
        self.state = state

    @overload
    def on_conflict(
        self,
        target: Attr[Any, Any, OwnerT, Any, Any],
        /,
        *,
        action: DoUpdate[OwnerT] | type[DoNothing],
    ) -> Self: ...

    @overload
    def on_conflict(
        self,
        target: Attr[Any, Any, OwnerT, Any, Any],
        second: Attr[Any, Any, OwnerT, Any, Any],
        /,
        *targets: Attr[Any, Any, OwnerT, Any, Any],
        action: DoUpdate[OwnerT] | type[DoNothing],
    ) -> Self: ...

    def on_conflict(
        self,
        *targets: Attr[Any, Any, OwnerT, Any, Any],
        action: DoUpdate[OwnerT] | type[DoNothing],
    ) -> Self:
        """Handle an insert conflict with `DoUpdate` or `DoNothing`.

        Targets and assignments must belong to the inserted model. SQLite uses
        the targets to select a primary key or unique index. MariaDB checks every
        unique key because its duplicate-key syntax has no target clause.

        ```python
        insert(User(email=email, status=status)).on_conflict(
            User.email,
            action=DoUpdate(User.status.to_inserted()),
        )
        ```
        """

        if not targets:
            msg = "on_conflict requires at least one target column"
            raise QueryConstructionError(msg)
        model = self.state.model()
        target_model = model or require_column_model(require_field(targets[0]))
        scope = ScopeResolver(own_models=(target_model,))
        checked_targets: list[Attr[Any, Any, Any, Any, Any]] = []
        for target in targets:
            column = require_field(target)
            if require_column_model(column) is not target_model:
                msg = "on_conflict target must belong to the inserted model"
                raise QueryConstructionError(msg)
            checked_targets.append(column)
        if isinstance(action, DoUpdate):
            for assignment in action.assignments:
                ensure_assignment_targets_model(assignment, scope)
        elif action is not DoNothing:
            msg = "on_conflict action must be DoUpdate(...) or DoNothing"
            raise QueryConstructionError(msg)
        return type(self)(
            replace(
                self.state,
                conflict_action=action,
                conflict_targets=tuple(checked_targets),
            )
        )


class _WriteShape[FamilyT, ResultT]:
    """Private nominal carrier for one write query's execution result."""

    def _result_type(self) -> ResultT:
        """Typing-only covariant witness for the execution result."""

        raise NotImplementedError


type _Write[FamilyT, ResultT] = _WriteShape[FamilyT, ResultT]
type Write[ResultT] = _Write[Any, ResultT]
"""Public annotation for a write query yielding `ResultT` on execution.

The result is `None` for inserts without `returning`, `int` for plain update and
delete statements, and the selected model or projection shape for writes with
`returning`.
"""


class _ReturningQuery[FamilyT, ResultT](_WriteShape[FamilyT, ResultT]):
    """Write query that materializes one or more returned rows."""


class InsertQuery[FamilyT, OwnerT: Table[Any], ReadT: Table[Any]](
    _BaseInsertQuery[FamilyT, OwnerT],
    _WriteShape[FamilyT, None],
):
    """Immutable insert statement for one pending table model instance."""

    @overload
    def returning(self) -> InsertReturningQuery[FamilyT, OwnerT, ReadT]: ...
    # BEGIN GENERATED INSERT RETURNING OVERLOADS
    @overload
    def returning[T1](
        self,
        field1: Attr[Any, Any, OwnerT, Any, T1],
        /,
    ) -> InsertReturningValueQuery[FamilyT, OwnerT, T1]: ...

    @overload
    def returning[T1, T2](
        self,
        field1: Attr[Any, Any, OwnerT, Any, T1],
        field2: Attr[Any, Any, OwnerT, Any, T2],
        /,
    ) -> InsertReturningTupleQuery[FamilyT, OwnerT, T1, T2]: ...

    @overload
    def returning[T1, T2, T3](
        self,
        field1: Attr[Any, Any, OwnerT, Any, T1],
        field2: Attr[Any, Any, OwnerT, Any, T2],
        field3: Attr[Any, Any, OwnerT, Any, T3],
        /,
    ) -> InsertReturningTupleQuery[FamilyT, OwnerT, T1, T2, T3]: ...

    @overload
    def returning[T1, T2, T3, T4](
        self,
        field1: Attr[Any, Any, OwnerT, Any, T1],
        field2: Attr[Any, Any, OwnerT, Any, T2],
        field3: Attr[Any, Any, OwnerT, Any, T3],
        field4: Attr[Any, Any, OwnerT, Any, T4],
        /,
    ) -> InsertReturningTupleQuery[FamilyT, OwnerT, T1, T2, T3, T4]: ...

    @overload
    def returning[T1, T2, T3, T4, T5](
        self,
        field1: Attr[Any, Any, OwnerT, Any, T1],
        field2: Attr[Any, Any, OwnerT, Any, T2],
        field3: Attr[Any, Any, OwnerT, Any, T3],
        field4: Attr[Any, Any, OwnerT, Any, T4],
        field5: Attr[Any, Any, OwnerT, Any, T5],
        /,
    ) -> InsertReturningTupleQuery[FamilyT, OwnerT, T1, T2, T3, T4, T5]: ...

    @overload
    def returning[T1, T2, T3, T4, T5, T6](
        self,
        field1: Attr[Any, Any, OwnerT, Any, T1],
        field2: Attr[Any, Any, OwnerT, Any, T2],
        field3: Attr[Any, Any, OwnerT, Any, T3],
        field4: Attr[Any, Any, OwnerT, Any, T4],
        field5: Attr[Any, Any, OwnerT, Any, T5],
        field6: Attr[Any, Any, OwnerT, Any, T6],
        /,
    ) -> InsertReturningTupleQuery[FamilyT, OwnerT, T1, T2, T3, T4, T5, T6]: ...

    @overload
    def returning[T1, T2, T3, T4, T5, T6, T7](
        self,
        field1: Attr[Any, Any, OwnerT, Any, T1],
        field2: Attr[Any, Any, OwnerT, Any, T2],
        field3: Attr[Any, Any, OwnerT, Any, T3],
        field4: Attr[Any, Any, OwnerT, Any, T4],
        field5: Attr[Any, Any, OwnerT, Any, T5],
        field6: Attr[Any, Any, OwnerT, Any, T6],
        field7: Attr[Any, Any, OwnerT, Any, T7],
        /,
    ) -> InsertReturningTupleQuery[FamilyT, OwnerT, T1, T2, T3, T4, T5, T6, T7]: ...

    @overload
    def returning[T1, T2, T3, T4, T5, T6, T7, T8](
        self,
        field1: Attr[Any, Any, OwnerT, Any, T1],
        field2: Attr[Any, Any, OwnerT, Any, T2],
        field3: Attr[Any, Any, OwnerT, Any, T3],
        field4: Attr[Any, Any, OwnerT, Any, T4],
        field5: Attr[Any, Any, OwnerT, Any, T5],
        field6: Attr[Any, Any, OwnerT, Any, T6],
        field7: Attr[Any, Any, OwnerT, Any, T7],
        field8: Attr[Any, Any, OwnerT, Any, T8],
        /,
    ) -> InsertReturningTupleQuery[FamilyT, OwnerT, T1, T2, T3, T4, T5, T6, T7, T8]: ...

    # END GENERATED INSERT RETURNING OVERLOADS
    def returning(self, *fields: object) -> object:
        """Recover columns the database produced for the inserted row.

        With no arguments the inserted row comes back as a Fetched model. Naming
        columns instead projects only those: one column yields its decoded scalar,
        several yield a tuple in the order given.
        """

        return _insert_returning(
            self.state,
            fields,
            model_query=InsertReturningQuery[FamilyT, OwnerT, ReadT],
            value_query=InsertReturningValueQuery[FamilyT, Any, Any],
            tuple_query=InsertReturningTupleQuery[FamilyT, Any, *tuple[Any, ...]],
        )


class InsertManyQuery[FamilyT, OwnerT: Table[Any], ReadT: Table[Any]](
    _BaseInsertQuery[FamilyT, OwnerT],
    _WriteShape[FamilyT, None],
):
    """Immutable bulk insert statement for several pending model instances."""

    @overload
    def returning(self) -> InsertManyReturningQuery[FamilyT, OwnerT, ReadT]: ...
    # BEGIN GENERATED INSERT MANY RETURNING OVERLOADS
    @overload
    def returning[T1](
        self,
        field1: Attr[Any, Any, OwnerT, Any, T1],
        /,
    ) -> InsertManyReturningValueQuery[FamilyT, OwnerT, T1]: ...

    @overload
    def returning[T1, T2](
        self,
        field1: Attr[Any, Any, OwnerT, Any, T1],
        field2: Attr[Any, Any, OwnerT, Any, T2],
        /,
    ) -> InsertManyReturningTupleQuery[FamilyT, OwnerT, T1, T2]: ...

    @overload
    def returning[T1, T2, T3](
        self,
        field1: Attr[Any, Any, OwnerT, Any, T1],
        field2: Attr[Any, Any, OwnerT, Any, T2],
        field3: Attr[Any, Any, OwnerT, Any, T3],
        /,
    ) -> InsertManyReturningTupleQuery[FamilyT, OwnerT, T1, T2, T3]: ...

    @overload
    def returning[T1, T2, T3, T4](
        self,
        field1: Attr[Any, Any, OwnerT, Any, T1],
        field2: Attr[Any, Any, OwnerT, Any, T2],
        field3: Attr[Any, Any, OwnerT, Any, T3],
        field4: Attr[Any, Any, OwnerT, Any, T4],
        /,
    ) -> InsertManyReturningTupleQuery[FamilyT, OwnerT, T1, T2, T3, T4]: ...

    @overload
    def returning[T1, T2, T3, T4, T5](
        self,
        field1: Attr[Any, Any, OwnerT, Any, T1],
        field2: Attr[Any, Any, OwnerT, Any, T2],
        field3: Attr[Any, Any, OwnerT, Any, T3],
        field4: Attr[Any, Any, OwnerT, Any, T4],
        field5: Attr[Any, Any, OwnerT, Any, T5],
        /,
    ) -> InsertManyReturningTupleQuery[FamilyT, OwnerT, T1, T2, T3, T4, T5]: ...

    @overload
    def returning[T1, T2, T3, T4, T5, T6](
        self,
        field1: Attr[Any, Any, OwnerT, Any, T1],
        field2: Attr[Any, Any, OwnerT, Any, T2],
        field3: Attr[Any, Any, OwnerT, Any, T3],
        field4: Attr[Any, Any, OwnerT, Any, T4],
        field5: Attr[Any, Any, OwnerT, Any, T5],
        field6: Attr[Any, Any, OwnerT, Any, T6],
        /,
    ) -> InsertManyReturningTupleQuery[FamilyT, OwnerT, T1, T2, T3, T4, T5, T6]: ...

    @overload
    def returning[T1, T2, T3, T4, T5, T6, T7](
        self,
        field1: Attr[Any, Any, OwnerT, Any, T1],
        field2: Attr[Any, Any, OwnerT, Any, T2],
        field3: Attr[Any, Any, OwnerT, Any, T3],
        field4: Attr[Any, Any, OwnerT, Any, T4],
        field5: Attr[Any, Any, OwnerT, Any, T5],
        field6: Attr[Any, Any, OwnerT, Any, T6],
        field7: Attr[Any, Any, OwnerT, Any, T7],
        /,
    ) -> InsertManyReturningTupleQuery[FamilyT, OwnerT, T1, T2, T3, T4, T5, T6, T7]: ...

    @overload
    def returning[T1, T2, T3, T4, T5, T6, T7, T8](
        self,
        field1: Attr[Any, Any, OwnerT, Any, T1],
        field2: Attr[Any, Any, OwnerT, Any, T2],
        field3: Attr[Any, Any, OwnerT, Any, T3],
        field4: Attr[Any, Any, OwnerT, Any, T4],
        field5: Attr[Any, Any, OwnerT, Any, T5],
        field6: Attr[Any, Any, OwnerT, Any, T6],
        field7: Attr[Any, Any, OwnerT, Any, T7],
        field8: Attr[Any, Any, OwnerT, Any, T8],
        /,
    ) -> InsertManyReturningTupleQuery[
        FamilyT, OwnerT, T1, T2, T3, T4, T5, T6, T7, T8
    ]: ...

    # END GENERATED INSERT MANY RETURNING OVERLOADS
    def returning(self, *fields: object) -> object:
        """Recover columns the database produced for each inserted row.

        With no arguments each inserted row comes back as a Fetched model. Naming
        columns instead projects only those: one column yields a list of decoded
        scalars, several yield a list of tuples in the order given.
        """

        return _insert_returning(
            self.state,
            fields,
            model_query=InsertManyReturningQuery[FamilyT, OwnerT, ReadT],
            value_query=InsertManyReturningValueQuery[FamilyT, Any, Any],
            tuple_query=InsertManyReturningTupleQuery[FamilyT, Any, *tuple[Any, ...]],
        )


class InsertReturningQuery[FamilyT, OwnerT: Table[Any], ReadT: Table[Any]](
    _BaseInsertQuery[FamilyT, OwnerT],
    _ReturningQuery[FamilyT, ReadT],
):
    """Single insert whose execution yields the Fetched model it produced."""


class InsertManyReturningQuery[FamilyT, OwnerT: Table[Any], ReadT: Table[Any]](
    _BaseInsertQuery[FamilyT, OwnerT],
    _ReturningQuery[FamilyT, list[ReadT]],
):
    """Bulk insert whose execution yields the Fetched models it produced."""


class InsertReturningValueQuery[FamilyT, OwnerT: Table[Any], T](
    _BaseInsertQuery[FamilyT, OwnerT],
    _ReturningQuery[FamilyT, T],
):
    """Single insert whose execution yields one decoded RETURNING column."""


class InsertReturningTupleQuery[FamilyT, OwnerT: Table[Any], *Ts](
    _BaseInsertQuery[FamilyT, OwnerT],
    _ReturningQuery[FamilyT, tuple[*Ts]],
):
    """Single insert whose execution yields a tuple of RETURNING columns."""


class InsertManyReturningValueQuery[FamilyT, OwnerT: Table[Any], T](
    _BaseInsertQuery[FamilyT, OwnerT],
    _ReturningQuery[FamilyT, list[T]],
):
    """Bulk insert whose execution yields one decoded RETURNING column per row."""


class InsertManyReturningTupleQuery[FamilyT, OwnerT: Table[Any], *Ts](
    _BaseInsertQuery[FamilyT, OwnerT],
    _ReturningQuery[FamilyT, list[tuple[*Ts]]],
):
    """Bulk insert whose execution yields a tuple of RETURNING columns per row."""


def _insert_returning(
    state: InsertState,
    fields: tuple[object, ...],
    *,
    model_query: type[_BaseInsertQuery[Any, Any]],
    value_query: type[_BaseInsertQuery[Any, Any]],
    tuple_query: type[_BaseInsertQuery[Any, Any]],
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
    InsertQuery[Any, Any, Any]
    | InsertManyQuery[Any, Any, Any]
    | InsertReturningQuery[Any, Any, Any]
    | InsertManyReturningQuery[Any, Any, Any]
    | InsertReturningValueQuery[Any, Any, Any]
    | InsertReturningTupleQuery[Any, Any, *tuple[Any, ...]]
    | InsertManyReturningValueQuery[Any, Any, Any]
    | InsertManyReturningTupleQuery[Any, Any, *tuple[Any, ...]]
)


type AnyWriteQuery = (
    AnyInsertQuery
    | UpdateQuery[Any, Any, Any]
    | UpdateReturningQuery[Any, Any, Any]
    | UpdateReturningValueQuery[Any, Any, Any, Any]
    | UpdateReturningTupleQuery[Any, Any, Any, *tuple[Any, ...]]
    | DeleteQuery[Any, Any, Any]
    | DeleteReturningQuery[Any, Any, Any]
    | DeleteReturningValueQuery[Any, Any, Any, Any]
    | DeleteReturningTupleQuery[Any, Any, Any, *tuple[Any, ...]]
)


class _UpdateQuery[FamilyT, ModelT: Table[Any], ReadT: Table[Any]](_SqlInspectionMixin):
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
        return type(self)(state)

    @overload
    def returning(self) -> UpdateReturningQuery[FamilyT, ModelT, ReadT]: ...
    # BEGIN GENERATED UPDATE RETURNING OVERLOADS
    @overload
    def returning[T1](
        self,
        field1: Attr[Any, Any, ModelT, Any, T1],
        /,
    ) -> UpdateReturningValueQuery[FamilyT, ModelT, ReadT, T1]: ...

    @overload
    def returning[T1, T2](
        self,
        field1: Attr[Any, Any, ModelT, Any, T1],
        field2: Attr[Any, Any, ModelT, Any, T2],
        /,
    ) -> UpdateReturningTupleQuery[FamilyT, ModelT, ReadT, T1, T2]: ...

    @overload
    def returning[T1, T2, T3](
        self,
        field1: Attr[Any, Any, ModelT, Any, T1],
        field2: Attr[Any, Any, ModelT, Any, T2],
        field3: Attr[Any, Any, ModelT, Any, T3],
        /,
    ) -> UpdateReturningTupleQuery[FamilyT, ModelT, ReadT, T1, T2, T3]: ...

    @overload
    def returning[T1, T2, T3, T4](
        self,
        field1: Attr[Any, Any, ModelT, Any, T1],
        field2: Attr[Any, Any, ModelT, Any, T2],
        field3: Attr[Any, Any, ModelT, Any, T3],
        field4: Attr[Any, Any, ModelT, Any, T4],
        /,
    ) -> UpdateReturningTupleQuery[FamilyT, ModelT, ReadT, T1, T2, T3, T4]: ...

    @overload
    def returning[T1, T2, T3, T4, T5](
        self,
        field1: Attr[Any, Any, ModelT, Any, T1],
        field2: Attr[Any, Any, ModelT, Any, T2],
        field3: Attr[Any, Any, ModelT, Any, T3],
        field4: Attr[Any, Any, ModelT, Any, T4],
        field5: Attr[Any, Any, ModelT, Any, T5],
        /,
    ) -> UpdateReturningTupleQuery[FamilyT, ModelT, ReadT, T1, T2, T3, T4, T5]: ...

    @overload
    def returning[T1, T2, T3, T4, T5, T6](
        self,
        field1: Attr[Any, Any, ModelT, Any, T1],
        field2: Attr[Any, Any, ModelT, Any, T2],
        field3: Attr[Any, Any, ModelT, Any, T3],
        field4: Attr[Any, Any, ModelT, Any, T4],
        field5: Attr[Any, Any, ModelT, Any, T5],
        field6: Attr[Any, Any, ModelT, Any, T6],
        /,
    ) -> UpdateReturningTupleQuery[FamilyT, ModelT, ReadT, T1, T2, T3, T4, T5, T6]: ...

    @overload
    def returning[T1, T2, T3, T4, T5, T6, T7](
        self,
        field1: Attr[Any, Any, ModelT, Any, T1],
        field2: Attr[Any, Any, ModelT, Any, T2],
        field3: Attr[Any, Any, ModelT, Any, T3],
        field4: Attr[Any, Any, ModelT, Any, T4],
        field5: Attr[Any, Any, ModelT, Any, T5],
        field6: Attr[Any, Any, ModelT, Any, T6],
        field7: Attr[Any, Any, ModelT, Any, T7],
        /,
    ) -> UpdateReturningTupleQuery[
        FamilyT, ModelT, ReadT, T1, T2, T3, T4, T5, T6, T7
    ]: ...

    @overload
    def returning[T1, T2, T3, T4, T5, T6, T7, T8](
        self,
        field1: Attr[Any, Any, ModelT, Any, T1],
        field2: Attr[Any, Any, ModelT, Any, T2],
        field3: Attr[Any, Any, ModelT, Any, T3],
        field4: Attr[Any, Any, ModelT, Any, T4],
        field5: Attr[Any, Any, ModelT, Any, T5],
        field6: Attr[Any, Any, ModelT, Any, T6],
        field7: Attr[Any, Any, ModelT, Any, T7],
        field8: Attr[Any, Any, ModelT, Any, T8],
        /,
    ) -> UpdateReturningTupleQuery[
        FamilyT, ModelT, ReadT, T1, T2, T3, T4, T5, T6, T7, T8
    ]: ...

    # END GENERATED UPDATE RETURNING OVERLOADS
    def returning(self, *fields: object) -> object:
        """Return rows produced by SQLite ``UPDATE ... RETURNING``."""

        return _update_returning(self.state, fields)

    @overload
    def set(self, assignment: Assignment[ModelT], /) -> Self: ...

    @overload
    def set(
        self,
        assignment: Assignment[ModelT],
        second: Assignment[ModelT],
        /,
        *assignments: Assignment[ModelT],
    ) -> Self: ...

    def set(self, *assignments: Assignment[ModelT]) -> Self:
        state = _update_set(self.state, assignments)
        return type(self)(state)

    @overload
    def where(self, predicate: Predicate[ModelT], /) -> Self: ...

    @overload
    def where(
        self,
        predicate: Predicate[ModelT],
        second: Predicate[ModelT],
        /,
        *predicates: Predicate[ModelT],
    ) -> Self: ...

    def where(self, *predicates: Predicate[ModelT]) -> Self:
        state = _update_where(self.state, predicates)
        return type(self)(state)


class UpdateQuery[FamilyT, ModelT: Table[Any], ReadT: Table[Any]](
    _UpdateQuery[FamilyT, ModelT, ReadT],
    _WriteShape[FamilyT, int],
):
    """Update whose execution yields the number of affected rows."""


class UpdateReturningQuery[FamilyT, ModelT: Table[Any], ReadT: Table[Any]](
    _UpdateQuery[FamilyT, ModelT, ReadT],
    _ReturningQuery[FamilyT, list[ReadT]],
):
    """Update whose execution yields a Fetched model for each returned row."""


class UpdateReturningValueQuery[FamilyT, ModelT: Table[Any], ReadT: Table[Any], T](
    _UpdateQuery[FamilyT, ModelT, ReadT],
    _ReturningQuery[FamilyT, list[T]],
):
    """Update whose execution yields one decoded RETURNING column per row."""


class UpdateReturningTupleQuery[FamilyT, ModelT: Table[Any], ReadT: Table[Any], *Ts](
    _UpdateQuery[FamilyT, ModelT, ReadT],
    _ReturningQuery[FamilyT, list[tuple[*Ts]]],
):
    """Update whose execution yields a tuple of RETURNING columns per row."""


class _DeleteQuery[FamilyT, ModelT: Table[Any], ReadT: Table[Any]](_SqlInspectionMixin):
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
        return type(self)(state)

    @overload
    def returning(self) -> DeleteReturningQuery[FamilyT, ModelT, ReadT]: ...
    # BEGIN GENERATED DELETE RETURNING OVERLOADS
    @overload
    def returning[T1](
        self,
        field1: Attr[Any, Any, ModelT, Any, T1],
        /,
    ) -> DeleteReturningValueQuery[FamilyT, ModelT, ReadT, T1]: ...

    @overload
    def returning[T1, T2](
        self,
        field1: Attr[Any, Any, ModelT, Any, T1],
        field2: Attr[Any, Any, ModelT, Any, T2],
        /,
    ) -> DeleteReturningTupleQuery[FamilyT, ModelT, ReadT, T1, T2]: ...

    @overload
    def returning[T1, T2, T3](
        self,
        field1: Attr[Any, Any, ModelT, Any, T1],
        field2: Attr[Any, Any, ModelT, Any, T2],
        field3: Attr[Any, Any, ModelT, Any, T3],
        /,
    ) -> DeleteReturningTupleQuery[FamilyT, ModelT, ReadT, T1, T2, T3]: ...

    @overload
    def returning[T1, T2, T3, T4](
        self,
        field1: Attr[Any, Any, ModelT, Any, T1],
        field2: Attr[Any, Any, ModelT, Any, T2],
        field3: Attr[Any, Any, ModelT, Any, T3],
        field4: Attr[Any, Any, ModelT, Any, T4],
        /,
    ) -> DeleteReturningTupleQuery[FamilyT, ModelT, ReadT, T1, T2, T3, T4]: ...

    @overload
    def returning[T1, T2, T3, T4, T5](
        self,
        field1: Attr[Any, Any, ModelT, Any, T1],
        field2: Attr[Any, Any, ModelT, Any, T2],
        field3: Attr[Any, Any, ModelT, Any, T3],
        field4: Attr[Any, Any, ModelT, Any, T4],
        field5: Attr[Any, Any, ModelT, Any, T5],
        /,
    ) -> DeleteReturningTupleQuery[FamilyT, ModelT, ReadT, T1, T2, T3, T4, T5]: ...

    @overload
    def returning[T1, T2, T3, T4, T5, T6](
        self,
        field1: Attr[Any, Any, ModelT, Any, T1],
        field2: Attr[Any, Any, ModelT, Any, T2],
        field3: Attr[Any, Any, ModelT, Any, T3],
        field4: Attr[Any, Any, ModelT, Any, T4],
        field5: Attr[Any, Any, ModelT, Any, T5],
        field6: Attr[Any, Any, ModelT, Any, T6],
        /,
    ) -> DeleteReturningTupleQuery[FamilyT, ModelT, ReadT, T1, T2, T3, T4, T5, T6]: ...

    @overload
    def returning[T1, T2, T3, T4, T5, T6, T7](
        self,
        field1: Attr[Any, Any, ModelT, Any, T1],
        field2: Attr[Any, Any, ModelT, Any, T2],
        field3: Attr[Any, Any, ModelT, Any, T3],
        field4: Attr[Any, Any, ModelT, Any, T4],
        field5: Attr[Any, Any, ModelT, Any, T5],
        field6: Attr[Any, Any, ModelT, Any, T6],
        field7: Attr[Any, Any, ModelT, Any, T7],
        /,
    ) -> DeleteReturningTupleQuery[
        FamilyT, ModelT, ReadT, T1, T2, T3, T4, T5, T6, T7
    ]: ...

    @overload
    def returning[T1, T2, T3, T4, T5, T6, T7, T8](
        self,
        field1: Attr[Any, Any, ModelT, Any, T1],
        field2: Attr[Any, Any, ModelT, Any, T2],
        field3: Attr[Any, Any, ModelT, Any, T3],
        field4: Attr[Any, Any, ModelT, Any, T4],
        field5: Attr[Any, Any, ModelT, Any, T5],
        field6: Attr[Any, Any, ModelT, Any, T6],
        field7: Attr[Any, Any, ModelT, Any, T7],
        field8: Attr[Any, Any, ModelT, Any, T8],
        /,
    ) -> DeleteReturningTupleQuery[
        FamilyT, ModelT, ReadT, T1, T2, T3, T4, T5, T6, T7, T8
    ]: ...

    # END GENERATED DELETE RETURNING OVERLOADS
    def returning(self, *fields: object) -> object:
        """Return rows produced by SQLite ``DELETE ... RETURNING``."""

        return _delete_returning(self.state, fields)

    @overload
    def where(self, predicate: Predicate[ModelT], /) -> Self: ...

    @overload
    def where(
        self,
        predicate: Predicate[ModelT],
        second: Predicate[ModelT],
        /,
        *predicates: Predicate[ModelT],
    ) -> Self: ...

    def where(self, *predicates: Predicate[ModelT]) -> Self:
        state = _delete_where(self.state, predicates)
        return type(self)(state)


class DeleteQuery[FamilyT, ModelT: Table[Any], ReadT: Table[Any]](
    _DeleteQuery[FamilyT, ModelT, ReadT],
    _WriteShape[FamilyT, int],
):
    """Delete whose execution yields the number of affected rows."""


class DeleteReturningQuery[FamilyT, ModelT: Table[Any], ReadT: Table[Any]](
    _DeleteQuery[FamilyT, ModelT, ReadT],
    _ReturningQuery[FamilyT, list[ReadT]],
):
    """Delete whose execution yields a Fetched model for each returned row."""


class DeleteReturningValueQuery[FamilyT, ModelT: Table[Any], ReadT: Table[Any], T](
    _DeleteQuery[FamilyT, ModelT, ReadT],
    _ReturningQuery[FamilyT, list[T]],
):
    """Delete whose execution yields one decoded RETURNING column per row."""


class DeleteReturningTupleQuery[FamilyT, ModelT: Table[Any], ReadT: Table[Any], *Ts](
    _DeleteQuery[FamilyT, ModelT, ReadT],
    _ReturningQuery[FamilyT, list[tuple[*Ts]]],
):
    """Delete whose execution yields a tuple of RETURNING columns per row."""


type AnySelectQuery = (
    SelectModelQuery[Any, Any, Any]
    | SelectValueQuery[Any, Any, Any, Any, Any]
    | SelectTupleQuery[Any, Any, Any, *tuple[Any, ...]]
    | JoinModelQuery[Any, Any, *tuple[Any, ...]]
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


def _require_factory_predicates(
    predicates: tuple[Predicate[Any], ...],
) -> tuple[_PredicateNode[Any], ...]:
    """Keep caller-defined predicate implementations out of query state."""

    return tuple(_require_predicate_node(predicate) for predicate in predicates)


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
    scope = ScopeResolver(own_models=state.result_models())
    checked_predicates = _require_factory_predicates(predicates)
    for predicate in checked_predicates:
        ensure_predicate_targets_models(predicate, scope)
    return replace(state, predicates=(*state.predicates, *checked_predicates))


def _select_order_by(
    state: SelectState,
    orderings: tuple[OrderBy[Any], ...],
) -> SelectState:
    if not orderings:
        msg = "order_by() requires at least one ordering"
        raise QueryConstructionError(msg)
    scope = ScopeResolver(own_models=state.result_models())
    checked_orderings: list[_OrderBy[Any]] = []
    for ordering in orderings:
        if not isinstance(ordering, _OrderBy):
            msg = "orderings must be built from columns"
            raise QueryConstructionError(msg)
        ensure_ordering_targets_models(ordering, scope)
        checked_orderings.append(ordering)
    return replace(state, orderings=(*state.orderings, *checked_orderings))


def _select_group_by(
    state: SelectState,
    columns: tuple[Attr[Any, Any, Any, Any, Any], ...],
) -> SelectState:
    if not columns:
        msg = "group_by() requires at least one column"
        raise QueryConstructionError(msg)
    grouped = tuple(require_field(column) for column in columns)
    ensure_grouping_targets_models(
        grouped,
        ScopeResolver(own_models=state.result_models()),
    )
    return replace(state, groupings=(*state.groupings, *grouped))


def _select_having(
    state: SelectState,
    predicates: tuple[Predicate[Any], ...],
) -> SelectState:
    if not predicates:
        msg = "having() requires at least one predicate"
        raise QueryConstructionError(msg)
    scope = ScopeResolver(own_models=state.result_models())
    checked_predicates = _require_factory_predicates(predicates)
    for predicate in checked_predicates:
        ensure_having_targets(predicate, state, scope)
    return replace(state, having=(*state.having, *checked_predicates))


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
    anchor_backend = require_model_backend(state.model)
    joined_backend = require_model_backend(table_model)
    if joined_backend != anchor_backend:
        msg = (
            f"backend mismatch: expected {anchor_backend} model, "
            f"received {joined_backend} model {table_model.__name__}"
        )
        raise QueryConstructionError(msg)
    if not isinstance(on, _JoinOn):
        msg = "join requires an on= condition built from references()"
        raise QueryConstructionError(msg)
    condition = cast("_JoinOn[Any, Any]", on)
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


def _update_returning(state: UpdateState, fields: tuple[object, ...]) -> object:
    """Build the right returning query for an update statement."""

    if not fields:
        return UpdateReturningQuery[Any, Any, Any](replace(state, returning=True))
    selectables = require_model_returning_fields(state.model, fields)
    projected = replace(state, returning=True, returning_fields=selectables)
    if len(selectables) == 1:
        return UpdateReturningValueQuery[Any, Any, Any, Any](projected)
    return UpdateReturningTupleQuery[Any, Any, Any, *tuple[Any, ...]](projected)


def _delete_returning(state: DeleteState, fields: tuple[object, ...]) -> object:
    """Build the right returning query for a delete statement."""

    if not fields:
        return DeleteReturningQuery[Any, Any, Any](replace(state, returning=True))
    selectables = require_model_returning_fields(state.model, fields)
    projected = replace(state, returning=True, returning_fields=selectables)
    if len(selectables) == 1:
        return DeleteReturningValueQuery[Any, Any, Any, Any](projected)
    return DeleteReturningTupleQuery[Any, Any, Any, *tuple[Any, ...]](projected)


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
    scope = ScopeResolver(own_models=(state.model,))
    checked_assignments: list[_Assignment[Any]] = []
    for assignment in assignments:
        if not isinstance(assignment, _Assignment):
            msg = "assignments must be built from columns"
            raise QueryConstructionError(msg)
        ensure_assignment_targets_model(assignment, scope)
        checked_assignments.append(assignment)
    return replace(state, assignments=(*state.assignments, *checked_assignments))


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
    scope = ScopeResolver(own_models=(state.model,))
    checked_predicates = _require_factory_predicates(predicates)
    for predicate in checked_predicates:
        ensure_predicate_targets_models(predicate, scope)
    return replace(state, predicates=(*state.predicates, *checked_predicates))


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
    scope = ScopeResolver(own_models=(state.model,))
    checked_predicates = _require_factory_predicates(predicates)
    for predicate in checked_predicates:
        ensure_predicate_targets_models(predicate, scope)
    return replace(state, predicates=(*state.predicates, *checked_predicates))


@overload
def select[FamilyT, SelectOwnerT: Table[Any], ReadModelT: Table[Any]](
    model: _SelectableModelClass[FamilyT, SelectOwnerT, ReadModelT],
    /,
) -> SelectModelQuery[FamilyT, SelectOwnerT, ReadModelT]: ...


@overload
def select[Owner1T: Table[Any], T1, CompareT](
    field1: Attr[Any, Any, Owner1T, Any, T1, Any, CompareT],
    /,
) -> SelectValueQuery[Any, Owner1T, Owner1T, T1, CompareT]: ...


@overload
def select[Owner1T: Table[Any], T1, CompareT](
    field1: Aggregate[Owner1T, T1, CompareT],
    /,
) -> SelectValueQuery[Any, Owner1T, Owner1T, T1, CompareT]: ...


@overload
def select[Owner1T: Table[Any], T1, CompareT](
    field1: DialectSelectable[Owner1T, T1, CompareT],
    /,
) -> SelectValueQuery[Any, Owner1T, Owner1T, T1, CompareT]: ...


# Projection overloads capture each column's owner separately. `ScopeT` is
# seeded with the FIRST column's table (the implicit `FROM` anchor); `RefT` is
# the union of every column's owner. The dual union is what lets the fetch
# overloads reject referencing a table that was never joined.
# Later projection slots also accept a scalar subquery. A single union arm per
# position binds the same `OwnerT`/`T` whichever expression it is, so grouped
# projections (`select(User.country, count(User.id))`) and scalar projections
# (`select(User.id, scalar(...))`) reuse the tuple machinery without a
# combinatorial overload explosion.
# BEGIN GENERATED SELECT OVERLOADS
@overload
def select[
    Owner1T: Table[Any],
    T1,
    Owner2T: Table[Any],
    T2,
](
    field1: Attr[Any, Any, Owner1T, Any, T1]
    | ColumnRef[Owner1T, T1]
    | Aggregate[Owner1T, T1, Any]
    | DialectSelectable[Owner1T, T1, Any],
    field2: Attr[Any, Any, Owner2T, Any, T2]
    | ColumnRef[Owner2T, T2]
    | Aggregate[Owner2T, T2, Any]
    | Scalar[Owner2T, T2, Any]
    | DialectSelectable[Owner2T, T2, Any],
    /,
) -> SelectTupleQuery[Any, Owner1T, Owner1T | Owner2T, T1, T2]: ...


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
    | ColumnRef[Owner1T, T1]
    | Aggregate[Owner1T, T1, Any]
    | DialectSelectable[Owner1T, T1, Any],
    field2: Attr[Any, Any, Owner2T, Any, T2]
    | ColumnRef[Owner2T, T2]
    | Aggregate[Owner2T, T2, Any]
    | Scalar[Owner2T, T2, Any]
    | DialectSelectable[Owner2T, T2, Any],
    field3: Attr[Any, Any, Owner3T, Any, T3]
    | ColumnRef[Owner3T, T3]
    | Aggregate[Owner3T, T3, Any]
    | Scalar[Owner3T, T3, Any]
    | DialectSelectable[Owner3T, T3, Any],
    /,
) -> SelectTupleQuery[Any, Owner1T, Owner1T | Owner2T | Owner3T, T1, T2, T3]: ...


@overload
def select[
    Owner1T: Table[Any],
    T1,
    Owner2T: Table[Any],
    T2,
    Owner3T: Table[Any],
    T3,
    Owner4T: Table[Any],
    T4,
](
    field1: Attr[Any, Any, Owner1T, Any, T1]
    | ColumnRef[Owner1T, T1]
    | Aggregate[Owner1T, T1, Any]
    | DialectSelectable[Owner1T, T1, Any],
    field2: Attr[Any, Any, Owner2T, Any, T2]
    | ColumnRef[Owner2T, T2]
    | Aggregate[Owner2T, T2, Any]
    | Scalar[Owner2T, T2, Any]
    | DialectSelectable[Owner2T, T2, Any],
    field3: Attr[Any, Any, Owner3T, Any, T3]
    | ColumnRef[Owner3T, T3]
    | Aggregate[Owner3T, T3, Any]
    | Scalar[Owner3T, T3, Any]
    | DialectSelectable[Owner3T, T3, Any],
    field4: Attr[Any, Any, Owner4T, Any, T4]
    | ColumnRef[Owner4T, T4]
    | Aggregate[Owner4T, T4, Any]
    | Scalar[Owner4T, T4, Any]
    | DialectSelectable[Owner4T, T4, Any],
    /,
) -> SelectTupleQuery[
    Any, Owner1T, Owner1T | Owner2T | Owner3T | Owner4T, T1, T2, T3, T4
]: ...


@overload
def select[
    Owner1T: Table[Any],
    T1,
    Owner2T: Table[Any],
    T2,
    Owner3T: Table[Any],
    T3,
    Owner4T: Table[Any],
    T4,
    Owner5T: Table[Any],
    T5,
](
    field1: Attr[Any, Any, Owner1T, Any, T1]
    | ColumnRef[Owner1T, T1]
    | Aggregate[Owner1T, T1, Any]
    | DialectSelectable[Owner1T, T1, Any],
    field2: Attr[Any, Any, Owner2T, Any, T2]
    | ColumnRef[Owner2T, T2]
    | Aggregate[Owner2T, T2, Any]
    | Scalar[Owner2T, T2, Any]
    | DialectSelectable[Owner2T, T2, Any],
    field3: Attr[Any, Any, Owner3T, Any, T3]
    | ColumnRef[Owner3T, T3]
    | Aggregate[Owner3T, T3, Any]
    | Scalar[Owner3T, T3, Any]
    | DialectSelectable[Owner3T, T3, Any],
    field4: Attr[Any, Any, Owner4T, Any, T4]
    | ColumnRef[Owner4T, T4]
    | Aggregate[Owner4T, T4, Any]
    | Scalar[Owner4T, T4, Any]
    | DialectSelectable[Owner4T, T4, Any],
    field5: Attr[Any, Any, Owner5T, Any, T5]
    | ColumnRef[Owner5T, T5]
    | Aggregate[Owner5T, T5, Any]
    | Scalar[Owner5T, T5, Any]
    | DialectSelectable[Owner5T, T5, Any],
    /,
) -> SelectTupleQuery[
    Any, Owner1T, Owner1T | Owner2T | Owner3T | Owner4T | Owner5T, T1, T2, T3, T4, T5
]: ...


@overload
def select[
    Owner1T: Table[Any],
    T1,
    Owner2T: Table[Any],
    T2,
    Owner3T: Table[Any],
    T3,
    Owner4T: Table[Any],
    T4,
    Owner5T: Table[Any],
    T5,
    Owner6T: Table[Any],
    T6,
](
    field1: Attr[Any, Any, Owner1T, Any, T1]
    | ColumnRef[Owner1T, T1]
    | Aggregate[Owner1T, T1, Any]
    | DialectSelectable[Owner1T, T1, Any],
    field2: Attr[Any, Any, Owner2T, Any, T2]
    | ColumnRef[Owner2T, T2]
    | Aggregate[Owner2T, T2, Any]
    | Scalar[Owner2T, T2, Any]
    | DialectSelectable[Owner2T, T2, Any],
    field3: Attr[Any, Any, Owner3T, Any, T3]
    | ColumnRef[Owner3T, T3]
    | Aggregate[Owner3T, T3, Any]
    | Scalar[Owner3T, T3, Any]
    | DialectSelectable[Owner3T, T3, Any],
    field4: Attr[Any, Any, Owner4T, Any, T4]
    | ColumnRef[Owner4T, T4]
    | Aggregate[Owner4T, T4, Any]
    | Scalar[Owner4T, T4, Any]
    | DialectSelectable[Owner4T, T4, Any],
    field5: Attr[Any, Any, Owner5T, Any, T5]
    | ColumnRef[Owner5T, T5]
    | Aggregate[Owner5T, T5, Any]
    | Scalar[Owner5T, T5, Any]
    | DialectSelectable[Owner5T, T5, Any],
    field6: Attr[Any, Any, Owner6T, Any, T6]
    | ColumnRef[Owner6T, T6]
    | Aggregate[Owner6T, T6, Any]
    | Scalar[Owner6T, T6, Any]
    | DialectSelectable[Owner6T, T6, Any],
    /,
) -> SelectTupleQuery[
    Any,
    Owner1T,
    Owner1T | Owner2T | Owner3T | Owner4T | Owner5T | Owner6T,
    T1,
    T2,
    T3,
    T4,
    T5,
    T6,
]: ...


@overload
def select[
    Owner1T: Table[Any],
    T1,
    Owner2T: Table[Any],
    T2,
    Owner3T: Table[Any],
    T3,
    Owner4T: Table[Any],
    T4,
    Owner5T: Table[Any],
    T5,
    Owner6T: Table[Any],
    T6,
    Owner7T: Table[Any],
    T7,
](
    field1: Attr[Any, Any, Owner1T, Any, T1]
    | ColumnRef[Owner1T, T1]
    | Aggregate[Owner1T, T1, Any]
    | DialectSelectable[Owner1T, T1, Any],
    field2: Attr[Any, Any, Owner2T, Any, T2]
    | ColumnRef[Owner2T, T2]
    | Aggregate[Owner2T, T2, Any]
    | Scalar[Owner2T, T2, Any]
    | DialectSelectable[Owner2T, T2, Any],
    field3: Attr[Any, Any, Owner3T, Any, T3]
    | ColumnRef[Owner3T, T3]
    | Aggregate[Owner3T, T3, Any]
    | Scalar[Owner3T, T3, Any]
    | DialectSelectable[Owner3T, T3, Any],
    field4: Attr[Any, Any, Owner4T, Any, T4]
    | ColumnRef[Owner4T, T4]
    | Aggregate[Owner4T, T4, Any]
    | Scalar[Owner4T, T4, Any]
    | DialectSelectable[Owner4T, T4, Any],
    field5: Attr[Any, Any, Owner5T, Any, T5]
    | ColumnRef[Owner5T, T5]
    | Aggregate[Owner5T, T5, Any]
    | Scalar[Owner5T, T5, Any]
    | DialectSelectable[Owner5T, T5, Any],
    field6: Attr[Any, Any, Owner6T, Any, T6]
    | ColumnRef[Owner6T, T6]
    | Aggregate[Owner6T, T6, Any]
    | Scalar[Owner6T, T6, Any]
    | DialectSelectable[Owner6T, T6, Any],
    field7: Attr[Any, Any, Owner7T, Any, T7]
    | ColumnRef[Owner7T, T7]
    | Aggregate[Owner7T, T7, Any]
    | Scalar[Owner7T, T7, Any]
    | DialectSelectable[Owner7T, T7, Any],
    /,
) -> SelectTupleQuery[
    Any,
    Owner1T,
    Owner1T | Owner2T | Owner3T | Owner4T | Owner5T | Owner6T | Owner7T,
    T1,
    T2,
    T3,
    T4,
    T5,
    T6,
    T7,
]: ...


@overload
def select[
    Owner1T: Table[Any],
    T1,
    Owner2T: Table[Any],
    T2,
    Owner3T: Table[Any],
    T3,
    Owner4T: Table[Any],
    T4,
    Owner5T: Table[Any],
    T5,
    Owner6T: Table[Any],
    T6,
    Owner7T: Table[Any],
    T7,
    Owner8T: Table[Any],
    T8,
](
    field1: Attr[Any, Any, Owner1T, Any, T1]
    | ColumnRef[Owner1T, T1]
    | Aggregate[Owner1T, T1, Any]
    | DialectSelectable[Owner1T, T1, Any],
    field2: Attr[Any, Any, Owner2T, Any, T2]
    | ColumnRef[Owner2T, T2]
    | Aggregate[Owner2T, T2, Any]
    | Scalar[Owner2T, T2, Any]
    | DialectSelectable[Owner2T, T2, Any],
    field3: Attr[Any, Any, Owner3T, Any, T3]
    | ColumnRef[Owner3T, T3]
    | Aggregate[Owner3T, T3, Any]
    | Scalar[Owner3T, T3, Any]
    | DialectSelectable[Owner3T, T3, Any],
    field4: Attr[Any, Any, Owner4T, Any, T4]
    | ColumnRef[Owner4T, T4]
    | Aggregate[Owner4T, T4, Any]
    | Scalar[Owner4T, T4, Any]
    | DialectSelectable[Owner4T, T4, Any],
    field5: Attr[Any, Any, Owner5T, Any, T5]
    | ColumnRef[Owner5T, T5]
    | Aggregate[Owner5T, T5, Any]
    | Scalar[Owner5T, T5, Any]
    | DialectSelectable[Owner5T, T5, Any],
    field6: Attr[Any, Any, Owner6T, Any, T6]
    | ColumnRef[Owner6T, T6]
    | Aggregate[Owner6T, T6, Any]
    | Scalar[Owner6T, T6, Any]
    | DialectSelectable[Owner6T, T6, Any],
    field7: Attr[Any, Any, Owner7T, Any, T7]
    | ColumnRef[Owner7T, T7]
    | Aggregate[Owner7T, T7, Any]
    | Scalar[Owner7T, T7, Any]
    | DialectSelectable[Owner7T, T7, Any],
    field8: Attr[Any, Any, Owner8T, Any, T8]
    | ColumnRef[Owner8T, T8]
    | Aggregate[Owner8T, T8, Any]
    | Scalar[Owner8T, T8, Any]
    | DialectSelectable[Owner8T, T8, Any],
    /,
) -> SelectTupleQuery[
    Any,
    Owner1T,
    Owner1T | Owner2T | Owner3T | Owner4T | Owner5T | Owner6T | Owner7T | Owner8T,
    T1,
    T2,
    T3,
    T4,
    T5,
    T6,
    T7,
    T8,
]: ...


# END GENERATED SELECT OVERLOADS


def select(*args: object) -> object:
    """Build a dialect-neutral select with backend-erased typing."""

    return build_select(*args)


def build_select(*args: object) -> object:
    """Build a select without overload narrowing, for Backend Namespace wrappers."""

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
        return SelectModelQuery[Any, Any, Any](state)
    fields = tuple(require_selectable(argument) for argument in args)
    if isinstance(fields[0], _Scalar):
        msg = "a scalar subquery cannot be the first projected field"
        raise QueryConstructionError(msg)
    # The first projected column/aggregate's table is the implicit FROM anchor;
    # columns from other tables must be brought into scope with
    # join()/left_join(), which the dual-union scope check enforces statically. A
    # scalar subquery has no owning table, so it can never anchor the FROM.
    anchor = next(
        (field for field in fields if not isinstance(field, _Scalar)),
        None,
    )
    if anchor is None:
        msg = "a projection must select at least one column or aggregate"
        raise QueryConstructionError(msg)
    model = selectable_owner_model(anchor)
    state = SelectState(model=model, fields=fields)
    if len(fields) == 1:
        return SelectValueQuery[Any, Any, Any, Any](state)
    return SelectTupleQuery[Any, Any, Any, *tuple[Any, ...]](state)


def exists(subquery: AnySelectQuery, /) -> Predicate[Any]:
    """Build an ``EXISTS (subquery)`` predicate.

    The subquery's projection is irrelevant to ``EXISTS`` (only whether it yields
    a row), so any select is accepted. A correlated subquery references the outer
    query through a column comparison (e.g. ``Order.user_id.eq_col(User.id)``);
    that correlation is resolved when the enclosing query compiles.
    """

    _ = require_subquery_state(subquery)
    return ExistencePredicate(subquery=subquery, negated=False)


def not_exists(subquery: AnySelectQuery, /) -> Predicate[Any]:
    """Build a ``NOT EXISTS (subquery)`` predicate (see :func:`exists`)."""

    _ = require_subquery_state(subquery)
    return ExistencePredicate(subquery=subquery, negated=True)


def scalar[T, CompareT](
    subquery: SelectValueQuery[Any, Any, Any, T, CompareT], /
) -> Scalar[Any, T | None, CompareT]:
    """Wrap a single-column select as a scalar subquery usable as a value.

    The result is a selectable (projectable alongside columns) and a comparison
    operand (the right side of a ``*_col`` comparison). The subquery must project
    exactly one column and is expected to yield at most one row per evaluation.

    The projected value type is always optional: a SQL scalar subquery evaluates
    to ``NULL`` on an empty/no-match result set regardless of the inner column's
    ``NOT NULL`` constraint, so the slot decodes to ``None`` rather than the inner
    type alone (#203 F10).
    """

    _ = require_single_column_subquery(subquery)
    return _Scalar(subquery=subquery)


@overload
def insert[FamilyT, OwnerT: Table[Any], ReadT: Table[Any]](
    row: InsertableModel[FamilyT, OwnerT, ReadT],
    /,
) -> InsertQuery[FamilyT, OwnerT, ReadT]: ...


@overload
def insert[FamilyT, OwnerT: Table[Any], ReadT: Table[Any]](
    rows: Sequence[InsertableModel[FamilyT, OwnerT, ReadT]],
    /,
) -> InsertManyQuery[FamilyT, OwnerT, ReadT]: ...


def insert(row_or_rows: object, /) -> object:
    """Build an insert from a single pending model or a sequence of them.

    A single model compiles to one ``INSERT ... VALUES (...)``; a sequence
    compiles to one multi-row ``INSERT ... VALUES (...), (...)`` and is a no-op
    when empty. Call ``.returning()`` on either to get the Fetched model(s) the
    database produced (generated keys, server defaults) back from the write.

    Backend namespaces wrap this dialect-blind builder with their own
    ``insert`` that documents the driver's write behavior.
    """

    return build_insert(row_or_rows)


def build_insert(row_or_rows: object, /) -> object:
    """Build an insert query without overload narrowing, for backend wrappers."""

    if isinstance(row_or_rows, Sequence):
        rows = tuple(cast("Sequence[Table[Any]]", row_or_rows))
        model: type[Table[Any]] | None = None
        for row in rows:
            row_model = require_insert_model(row)
            if model is None:
                model = row_model
            elif row_model is not model:
                msg = "bulk insert rows must be instances of the same model"
                raise QueryConstructionError(msg)
        return InsertManyQuery[Any, Any, Any](InsertState(rows=rows, multi=True))
    _ = require_insert_model(row_or_rows)
    return InsertQuery[Any, Any, Any](
        InsertState(rows=(cast("Table[Any]", row_or_rows),)),
    )


def update[FamilyT, ModelT: Table[Any], ReadT: Table[Any]](
    model: _SelectableModelClass[FamilyT, ModelT, ReadT], /
) -> UpdateQuery[FamilyT, ModelT, ReadT]:
    try:
        _ = require_model_columns(cast("type[object]", model))
    except ModelDeclarationError as error:
        msg = "update requires a table model"
        raise QueryConstructionError(msg) from error
    return UpdateQuery[Any, Any, Any](
        UpdateState(model=cast("type[Table[Any]]", model))
    )


def delete[FamilyT, ModelT: Table[Any], ReadT: Table[Any]](
    model: _SelectableModelClass[FamilyT, ModelT, ReadT], /
) -> DeleteQuery[FamilyT, ModelT, ReadT]:
    try:
        _ = require_model_columns(cast("type[object]", model))
    except ModelDeclarationError as error:
        msg = "delete requires a table model"
        raise QueryConstructionError(msg) from error
    return DeleteQuery[Any, Any, Any](
        DeleteState(model=cast("type[Table[Any]]", model))
    )

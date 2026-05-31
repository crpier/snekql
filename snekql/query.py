"""Query Builder objects and factory functions."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, replace
from typing import Any, Generic, Protocol, Self, TypeVar, TypeVarTuple, cast, overload

from snekql.errors import (
    ModelDeclarationError,
    QueryCompilationError,
    QueryConstructionError,
)
from snekql.expressions import Assignment, OrderBy, Predicate
from snekql.model import (
    Table,
    decode_model_row,
    encode_model_row,
    require_model_columns,
    require_model_table_name,
)
from snekql.schema import quote_sqlite_identifier
from snekql.storage import Attr
from snekql.validation import NonNegativeInt, validate_boundary

ModelT = TypeVar("ModelT", bound=Table[Any])
ReadModelT = TypeVar("ReadModelT", bound=Table[Any])
SelectOwnerT = TypeVar("SelectOwnerT", bound=Table[Any])
OwnerT = TypeVar("OwnerT", bound=Table[Any])
SelectableOwnerT = TypeVar("SelectableOwnerT", bound=Table[Any], covariant=True)
SelectableReadT = TypeVar("SelectableReadT", bound=Table[Any], covariant=True)
T = TypeVar("T")
T1 = TypeVar("T1")
T2 = TypeVar("T2")
T3 = TypeVar("T3")
Ts = TypeVarTuple("Ts")


class _SelectableModelClass(Protocol[SelectableOwnerT, SelectableReadT]):
    """Structural type for model classes accepted by `select(Model)`.

    The protocol lets pyright connect the writable owner model type with the
    fetched read model type exposed by table model classes.
    """

    @classmethod
    def __owner_type__(cls) -> type[SelectableOwnerT]: ...

    @classmethod
    def __read_type__(cls) -> type[SelectableReadT]: ...


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


class SelectModelQuery(Generic[SelectOwnerT, ReadModelT]):
    """Immutable select query that returns fetched table model instances."""

    state: _SelectState

    def __init__(self, state: _SelectState | None = None) -> None:
        if state is None:
            state = _empty_select_state()
        self.state = state

    def all(self) -> Self:
        state = _select_all(self.state)
        if state is self.state:
            return self
        return cast(Self, SelectModelQuery[SelectOwnerT, ReadModelT](state))

    def where(
        self,
        predicate: Predicate[SelectOwnerT],
        /,
        *predicates: Predicate[SelectOwnerT],
    ) -> Self:
        state = _select_where(self.state, (predicate, *predicates))
        return cast(Self, SelectModelQuery[SelectOwnerT, ReadModelT](state))

    def order_by(self, *ordering: OrderBy[SelectOwnerT]) -> Self:
        state = _select_order_by(self.state, ordering)
        return cast(Self, SelectModelQuery[SelectOwnerT, ReadModelT](state))

    @validate_boundary(
        QueryConstructionError, "limit() requires a non-negative integer"
    )
    def limit(self, value: NonNegativeInt) -> Self:
        state = _select_limit(self.state, value)
        return cast(Self, SelectModelQuery[SelectOwnerT, ReadModelT](state))

    @validate_boundary(
        QueryConstructionError, "offset() requires a non-negative integer"
    )
    def offset(self, value: NonNegativeInt) -> Self:
        state = _select_offset(self.state, value)
        return cast(Self, SelectModelQuery[SelectOwnerT, ReadModelT](state))


class SelectValueQuery(Generic[OwnerT, T]):
    """Immutable select query that returns one scalar column value per row."""

    state: _SelectState

    def __init__(self, state: _SelectState | None = None) -> None:
        if state is None:
            state = _empty_select_state()
        self.state = state

    def all(self) -> Self:
        state = _select_all(self.state)
        if state is self.state:
            return self
        return cast(Self, SelectValueQuery[OwnerT, T](state))

    def where(
        self,
        predicate: Predicate[OwnerT],
        /,
        *predicates: Predicate[OwnerT],
    ) -> Self:
        state = _select_where(self.state, (predicate, *predicates))
        return cast(Self, SelectValueQuery[OwnerT, T](state))

    def order_by(self, *ordering: OrderBy[OwnerT]) -> Self:
        state = _select_order_by(self.state, ordering)
        return cast(Self, SelectValueQuery[OwnerT, T](state))

    @validate_boundary(
        QueryConstructionError, "limit() requires a non-negative integer"
    )
    def limit(self, value: NonNegativeInt) -> Self:
        state = _select_limit(self.state, value)
        return cast(Self, SelectValueQuery[OwnerT, T](state))

    @validate_boundary(
        QueryConstructionError, "offset() requires a non-negative integer"
    )
    def offset(self, value: NonNegativeInt) -> Self:
        state = _select_offset(self.state, value)
        return cast(Self, SelectValueQuery[OwnerT, T](state))


class SelectTupleQuery(Generic[OwnerT, *Ts]):
    """Immutable select query that returns selected column tuples per row."""

    state: _SelectState

    def __init__(self, state: _SelectState | None = None) -> None:
        if state is None:
            state = _empty_select_state()
        self.state = state

    def all(self) -> Self:
        state = _select_all(self.state)
        if state is self.state:
            return self
        return cast(Self, SelectTupleQuery[OwnerT, *Ts](state))

    def where(
        self,
        predicate: Predicate[OwnerT],
        /,
        *predicates: Predicate[OwnerT],
    ) -> Self:
        state = _select_where(self.state, (predicate, *predicates))
        return cast(Self, SelectTupleQuery[OwnerT, *Ts](state))

    def order_by(self, *ordering: OrderBy[OwnerT]) -> Self:
        state = _select_order_by(self.state, ordering)
        return cast(Self, SelectTupleQuery[OwnerT, *Ts](state))

    @validate_boundary(
        QueryConstructionError, "limit() requires a non-negative integer"
    )
    def limit(self, value: NonNegativeInt) -> Self:
        state = _select_limit(self.state, value)
        return cast(Self, SelectTupleQuery[OwnerT, *Ts](state))

    @validate_boundary(
        QueryConstructionError, "offset() requires a non-negative integer"
    )
    def offset(self, value: NonNegativeInt) -> Self:
        state = _select_offset(self.state, value)
        return cast(Self, SelectTupleQuery[OwnerT, *Ts](state))


class InsertQuery(Generic[ModelT]):
    """Immutable insert statement for one pending table model instance."""

    row: ModelT

    def __init__(self, row: ModelT) -> None:
        self.row: ModelT = row


class UpdateQuery(Generic[ModelT]):
    """Immutable update statement for one table model."""

    def all(self) -> Self:
        return self

    def set(
        self,
        assignment: Assignment[ModelT],
        /,
        *assignments: Assignment[ModelT],
    ) -> Self:
        return self

    def where(
        self,
        predicate: Predicate[ModelT],
        /,
        *predicates: Predicate[ModelT],
    ) -> Self:
        return self


class DeleteQuery(Generic[ModelT]):
    """Immutable delete statement for one table model."""

    def all(self) -> Self:
        return self

    def where(
        self,
        predicate: Predicate[ModelT],
        /,
        *predicates: Predicate[ModelT],
    ) -> Self:
        return self


type AnySelectQuery = (
    SelectModelQuery[Any, Any]
    | SelectValueQuery[Any, Any]
    | SelectTupleQuery[Any, *tuple[Any, ...]]
)


def _empty_select_state() -> _SelectState:
    return _SelectState(model=Table[Any], fields=())


def _select_all(state: _SelectState) -> _SelectState:
    if state.predicates:
        raise QueryConstructionError("all() cannot be combined with where()")
    if state.explicit_all:
        return state
    return replace(state, explicit_all=True)


def _select_where(
    state: _SelectState,
    predicates: tuple[Predicate[Any], ...],
) -> _SelectState:
    if state.explicit_all:
        raise QueryConstructionError("where() cannot be combined with all()")
    for predicate in predicates:
        _ensure_predicate_targets_model(predicate, state.model)
    return replace(state, predicates=(*state.predicates, *predicates))


def _select_order_by(
    state: _SelectState,
    orderings: tuple[OrderBy[Any], ...],
) -> _SelectState:
    if not orderings:
        raise QueryConstructionError("order_by() requires at least one ordering")
    for ordering in orderings:
        _ensure_ordering_targets_model(ordering, state.model)
    return replace(state, orderings=(*state.orderings, *orderings))


def _select_limit(state: _SelectState, value: NonNegativeInt) -> _SelectState:
    return replace(state, limit_value=value)


def _select_offset(state: _SelectState, value: NonNegativeInt) -> _SelectState:
    return replace(state, offset_value=value)


def _require_field(value: object) -> Attr[Any, Any, Any, Any, Any]:
    if not isinstance(value, Attr):
        raise QueryConstructionError("select requires a model or field")
    return cast(Attr[Any, Any, Any, Any, Any], value)


def _require_column_name(column: Attr[Any, Any, Any, Any, Any]) -> str:
    if column.name is None:
        raise QueryConstructionError("field is not bound to a model")
    return column.name


def _require_column_model(column: Attr[Any, Any, Any, Any, Any]) -> type[Table[Any]]:
    owner = column.owner
    if owner is None:
        raise QueryConstructionError("field is not bound to a model")
    model = cast(type[Table[Any]], owner)
    try:
        _ = require_model_columns(model)
    except ModelDeclarationError as error:
        raise QueryConstructionError("field is not bound to a table model") from error
    return model


def _ensure_predicate_targets_model(
    predicate: Predicate[Any],
    model: type[Table[Any]],
) -> None:
    if predicate.kind == "":
        raise QueryConstructionError("where predicates must be built from columns")
    if predicate.column is not None:
        column = _require_field(predicate.column)
        if _require_column_model(column) is not model:
            raise QueryConstructionError("joins are not supported in v1")
    for child in predicate.children:
        _ensure_predicate_targets_model(child, model)


def _ensure_ordering_targets_model(
    ordering: OrderBy[Any],
    model: type[Table[Any]],
) -> None:
    if ordering.column is None or ordering.direction not in ("ASC", "DESC"):
        raise QueryConstructionError("orderings must be built from columns")
    column = _require_field(ordering.column)
    if _require_column_model(column) is not model:
        raise QueryConstructionError("joins are not supported in v1")


def _compile_insert_sql(query: InsertQuery[Any]) -> tuple[str, tuple[object, ...]]:
    model_class, row_values = encode_model_row(query.row)
    table_name = require_model_table_name(model_class)
    quoted_table = quote_sqlite_identifier(table_name)
    if not row_values:
        return f"INSERT INTO {quoted_table} DEFAULT VALUES", ()
    names = tuple(row_values)
    quoted_columns = ", ".join(quote_sqlite_identifier(name) for name in names)
    placeholders = ", ".join("?" for _ in names)
    sql = f"INSERT INTO {quoted_table} ({quoted_columns}) VALUES ({placeholders})"
    params = tuple(row_values[name] for name in names)
    return sql, params


def _compile_predicate_sql(
    predicate: Predicate[Any],
    model: type[Table[Any]],
) -> tuple[str, tuple[object, ...]]:
    _ensure_predicate_targets_model(predicate, model)
    if predicate.kind in ("and", "or"):
        if len(predicate.children) != 2:
            raise QueryCompilationError("compound predicate is malformed")
        left_sql, left_params = _compile_predicate_sql(predicate.children[0], model)
        right_sql, right_params = _compile_predicate_sql(predicate.children[1], model)
        operator = "AND" if predicate.kind == "and" else "OR"
        return f"({left_sql}) {operator} ({right_sql})", (*left_params, *right_params)
    if predicate.kind == "not":
        if len(predicate.children) != 1:
            raise QueryCompilationError("negated predicate is malformed")
        child_sql, child_params = _compile_predicate_sql(predicate.children[0], model)
        return f"NOT ({child_sql})", child_params
    column = _require_field(predicate.column)
    column_name = quote_sqlite_identifier(_require_column_name(column))
    if predicate.kind == "eq":
        return f"{column_name} = ?", (column.encode_sqlite(predicate.value),)
    if predicate.kind == "ne":
        return f"{column_name} != ?", (column.encode_sqlite(predicate.value),)
    if predicate.kind == "is_null":
        return f"{column_name} IS NULL", ()
    if predicate.kind == "is_not_null":
        return f"{column_name} IS NOT NULL", ()
    if predicate.kind in ("in", "not_in"):
        if not predicate.values:
            raise QueryCompilationError("IN predicates require at least one value")
        placeholders = ", ".join("?" for _ in predicate.values)
        operator = "IN" if predicate.kind == "in" else "NOT IN"
        params = tuple(column.encode_sqlite(value) for value in predicate.values)
        return f"{column_name} {operator} ({placeholders})", params
    if predicate.kind == "like":
        return f"{column_name} LIKE ?", (column.encode_sqlite(predicate.value),)
    if predicate.kind == "not_like":
        return f"{column_name} NOT LIKE ?", (column.encode_sqlite(predicate.value),)
    raise QueryCompilationError("unknown predicate kind")


def _compile_ordering_sql(
    ordering: OrderBy[Any],
    model: type[Table[Any]],
) -> str:
    _ensure_ordering_targets_model(ordering, model)
    column = _require_field(ordering.column)
    column_name = quote_sqlite_identifier(_require_column_name(column))
    return f"{column_name} {ordering.direction}"


def _compile_select_state(state: _SelectState) -> tuple[str, tuple[object, ...]]:
    if not state.explicit_all and not state.predicates:
        raise QueryCompilationError("select requires all() or where() before execution")
    table_name = require_model_table_name(state.model)
    quoted_columns = ", ".join(
        quote_sqlite_identifier(_require_column_name(column)) for column in state.fields
    )
    sql_parts = [
        f"SELECT {quoted_columns} FROM {quote_sqlite_identifier(table_name)}",
    ]
    params: tuple[object, ...] = ()
    if state.predicates:
        predicate_sql_parts: list[str] = []
        predicate_params: tuple[object, ...] = ()
        for predicate in state.predicates:
            predicate_sql, compiled_params = _compile_predicate_sql(
                predicate,
                state.model,
            )
            predicate_sql_parts.append(f"({predicate_sql})")
            predicate_params = (*predicate_params, *compiled_params)
        sql_parts.append("WHERE " + " AND ".join(predicate_sql_parts))
        params = (*params, *predicate_params)
    if state.orderings:
        order_by = ", ".join(
            _compile_ordering_sql(ordering, state.model) for ordering in state.orderings
        )
        sql_parts.append(f"ORDER BY {order_by}")
    if state.limit_value is not None:
        sql_parts.append("LIMIT ?")
        params = (*params, state.limit_value)
    if state.offset_value is not None:
        if state.limit_value is None:
            sql_parts.append("LIMIT -1")
        sql_parts.append("OFFSET ?")
        params = (*params, state.offset_value)
    return " ".join(sql_parts), params


def compile_select_sql(query: AnySelectQuery) -> tuple[str, tuple[object, ...]]:
    """Compile a select query into parameterized SQLite SQL."""

    return _compile_select_state(query.state)


def compile_write_sql(
    query: InsertQuery[Any] | UpdateQuery[Any] | DeleteQuery[Any],
) -> tuple[str, tuple[object, ...]]:
    """Compile a write query into parameterized SQLite SQL."""

    if isinstance(query, InsertQuery):
        return _compile_insert_sql(query)
    raise QueryCompilationError("only insert execution is implemented yet")


def materialize_select_row(
    query: AnySelectQuery,
    row: Sequence[object],
) -> object:
    """Decode one SQLite result row according to a select query."""

    state = query.state
    if len(row) != len(state.fields):
        raise QueryCompilationError("database row shape did not match select query")
    if state.returns_model:
        values = {
            _require_column_name(column): row[index]
            for index, column in enumerate(state.fields)
        }
        return decode_model_row(state.model, values)
    decoded_values = tuple(
        column.decode_sqlite(row[index]) for index, column in enumerate(state.fields)
    )
    if len(decoded_values) == 1:
        return decoded_values[0]
    return decoded_values


@overload
def select(
    model: _SelectableModelClass[SelectOwnerT, ReadModelT],
    /,
) -> SelectModelQuery[SelectOwnerT, ReadModelT]: ...


@overload
def select(
    field1: Attr[Any, Any, OwnerT, Any, T1],
    /,
) -> SelectValueQuery[OwnerT, T1]: ...


@overload
def select(
    field1: Attr[Any, Any, OwnerT, Any, T1],
    field2: Attr[Any, Any, OwnerT, Any, T2],
    /,
) -> SelectTupleQuery[OwnerT, T1, T2]: ...


@overload
def select(
    field1: Attr[Any, Any, OwnerT, Any, T1],
    field2: Attr[Any, Any, OwnerT, Any, T2],
    field3: Attr[Any, Any, OwnerT, Any, T3],
    /,
) -> SelectTupleQuery[OwnerT, T1, T2, T3]: ...


def select(*args: object) -> object:
    if len(args) == 0:
        raise QueryConstructionError("select requires a model or field")
    if any(isinstance(argument, type) for argument in args):
        if len(args) != 1 or not isinstance(args[0], type):
            raise QueryConstructionError("mixed model and field selection is invalid")
        model = cast(type[Table[Any]], args[0])
        try:
            columns = require_model_columns(model)
        except ModelDeclarationError as error:
            raise QueryConstructionError("select requires a table model") from error
        state = _SelectState(
            model=model,
            fields=tuple(columns.values()),
            returns_model=True,
        )
        return SelectModelQuery[Any, Any](state)
    fields = tuple(_require_field(argument) for argument in args)
    model = _require_column_model(fields[0])
    for field in fields[1:]:
        if _require_column_model(field) is not model:
            raise QueryConstructionError("joins are not supported in v1")
    state = _SelectState(model=model, fields=fields)
    if len(fields) == 1:
        return SelectValueQuery[Any, Any](state)
    return SelectTupleQuery[Any, *tuple[Any, ...]](state)


def insert(row: ModelT, /) -> InsertQuery[ModelT]:
    return InsertQuery(row)


def update(model: type[ModelT], /) -> UpdateQuery[ModelT]:
    return UpdateQuery()


def delete(model: type[ModelT], /) -> DeleteQuery[ModelT]:
    return DeleteQuery()

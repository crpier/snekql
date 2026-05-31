"""Query Builder objects and factory functions."""

from __future__ import annotations

from typing import Any, Generic, Protocol, Self, TypeVar, TypeVarTuple, overload

from snekql.errors import QueryConstructionError
from snekql.expressions import Assignment, OrderBy, Predicate
from snekql.model import Table, encode_model_row, require_model_table_name
from snekql.schema import quote_sqlite_identifier
from snekql.storage import Attr

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


class SelectModelQuery(Generic[SelectOwnerT, ReadModelT]):
    """Immutable select query that returns fetched table model instances."""

    def all(self) -> Self:
        return self

    def where(
        self,
        predicate: Predicate[SelectOwnerT],
        /,
        *predicates: Predicate[SelectOwnerT],
    ) -> Self:
        return self

    def order_by(self, *ordering: OrderBy[SelectOwnerT]) -> Self:
        return self

    def limit(self, value: int) -> Self:
        return self

    def offset(self, value: int) -> Self:
        return self


class SelectValueQuery(Generic[OwnerT, T]):
    """Immutable select query that returns one scalar column value per row."""

    def all(self) -> Self:
        return self

    def where(
        self,
        predicate: Predicate[OwnerT],
        /,
        *predicates: Predicate[OwnerT],
    ) -> Self:
        return self

    def order_by(self, *ordering: OrderBy[OwnerT]) -> Self:
        return self

    def limit(self, value: int) -> Self:
        return self

    def offset(self, value: int) -> Self:
        return self


class SelectTupleQuery(Generic[OwnerT, *Ts]):
    """Immutable select query that returns selected column tuples per row."""

    def all(self) -> Self:
        return self

    def where(
        self,
        predicate: Predicate[OwnerT],
        /,
        *predicates: Predicate[OwnerT],
    ) -> Self:
        return self

    def order_by(self, *ordering: OrderBy[OwnerT]) -> Self:
        return self

    def limit(self, value: int) -> Self:
        return self

    def offset(self, value: int) -> Self:
        return self


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


def compile_insert_sql(query: InsertQuery[Any]) -> tuple[str, tuple[object, ...]]:
    """Compile a pending model insert into SQLite SQL and parameters."""

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
    if len(args) == 1 and isinstance(args[0], type):
        return SelectModelQuery[Any, Any]()
    if len(args) == 1:
        return SelectValueQuery[Any, Any]()
    return SelectTupleQuery[Any]()


def insert(row: ModelT, /) -> InsertQuery[ModelT]:
    return InsertQuery(row)


def update(model: type[ModelT], /) -> UpdateQuery[ModelT]:
    return UpdateQuery()


def delete(model: type[ModelT], /) -> DeleteQuery[ModelT]:
    return DeleteQuery()

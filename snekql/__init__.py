from __future__ import annotations

from typing import (
    Any,
    Callable,
    Generic,
    Literal,
    Never,
    Protocol,
    Self,
    Sequence,
    TypeVar,
    TypeVarTuple,
    cast,
    dataclass_transform,
    overload,
)

StateT = TypeVar("StateT")
ModelT = TypeVar("ModelT", bound="Table[Any]")
ReadModelT = TypeVar("ReadModelT", bound="Table[Any]")
SelectOwnerT = TypeVar("SelectOwnerT", bound="Table[Any]")
OwnerT = TypeVar("OwnerT", bound="Table[Any]")
SelectableOwnerT = TypeVar("SelectableOwnerT", bound="Table[Any]", covariant=True)
SelectableReadT = TypeVar("SelectableReadT", bound="Table[Any]", covariant=True)
WriteOwnerT = TypeVar("WriteOwnerT")
LoadedOwnerT = TypeVar("LoadedOwnerT")
WriteT = TypeVar("WriteT")
ReadValueT = TypeVar("ReadValueT")
T = TypeVar("T")
T1 = TypeVar("T1")
T2 = TypeVar("T2")
T3 = TypeVar("T3")
Ts = TypeVarTuple("Ts")


class Pending:
    pass


class Fetched:
    pass


class Missing:
    pass


MISSING = Missing()


type SchemaPolicy = Literal["strict", "warn"]


class SnekqlError(Exception):
    pass


class ModelError(SnekqlError):
    pass


class ModelDeclarationError(ModelError):
    pass


class ModelValidationError(ModelError):
    pass


class FrozenModelError(ModelError):
    pass


class QueryError(SnekqlError):
    pass


class QueryConstructionError(QueryError):
    pass


class QueryCompilationError(QueryError):
    pass


class DatabaseRuntimeError(SnekqlError):
    pass


class DatabaseClosedError(DatabaseRuntimeError):
    pass


class TransactionClosedError(DatabaseRuntimeError):
    pass


class PoolTimeoutError(DatabaseRuntimeError):
    pass


class DatabaseCloseTimeoutError(DatabaseRuntimeError):
    pass


class DatabaseClosingError(DatabaseRuntimeError):
    pass


class ExecutionError(DatabaseRuntimeError):
    sql: str
    params: tuple[object, ...]


class SchemaError(SnekqlError):
    pass


class SchemaVerificationError(SchemaError):
    pass


class Integer:
    def __new__(
        cls,
        *,
        primary_key: bool = False,
        auto_increment: bool = False,
        nullable: bool | None = None,
        default: object = ...,
        default_factory: Callable[[], object] = ...,
    ) -> Any: ...


class Real:
    def __new__(
        cls,
        *,
        primary_key: bool = False,
        nullable: bool | None = None,
        default: object = ...,
        default_factory: Callable[[], object] = ...,
    ) -> Any: ...


class Text:
    def __new__(
        cls,
        *,
        primary_key: bool = False,
        nullable: bool | None = None,
        default: object = ...,
        default_factory: Callable[[], object] = ...,
    ) -> Any: ...


class Blob:
    def __new__(
        cls,
        *,
        primary_key: bool = False,
        nullable: bool | None = None,
        default: object = ...,
        default_factory: Callable[[], object] = ...,
    ) -> Any: ...


class Json:
    def __new__(
        cls,
        *,
        nullable: bool | None = None,
        default: object = ...,
        default_factory: Callable[[], object] = ...,
    ) -> Any: ...


class Boolean:
    def __new__(
        cls,
        *,
        nullable: bool | None = None,
        default: object = ...,
        default_factory: Callable[[], object] = ...,
    ) -> Any: ...


class DateTime:
    def __new__(
        cls,
        *,
        server_default: object | None = None,
        nullable: bool | None = None,
        default: object = ...,
        default_factory: Callable[[], object] = ...,
    ) -> Any: ...


class CurrentTimestamp:
    pass


class Predicate(Generic[OwnerT]):
    def __and__(self, other: Predicate[OwnerT]) -> Predicate[OwnerT]: ...
    def __or__(self, other: Predicate[OwnerT]) -> Predicate[OwnerT]: ...
    def __invert__(self) -> Predicate[OwnerT]: ...


class OrderBy(Generic[OwnerT]):
    pass


class Assignment(Generic[OwnerT]):
    pass


class Attr(Generic[WriteOwnerT, LoadedOwnerT, OwnerT, WriteT, ReadValueT]):
    @overload
    def __get__(
        self, instance: None, owner: type[Any]
    ) -> Attr[WriteOwnerT, LoadedOwnerT, OwnerT, WriteT, ReadValueT]: ...
    @overload
    def __get__(self, instance: WriteOwnerT, owner: type[Any]) -> WriteT: ...
    @overload
    def __get__(self, instance: LoadedOwnerT, owner: type[Any]) -> ReadValueT: ...
    def __get__(self, instance: object | None, owner: type[Any]) -> object: ...
    def __set__(self, instance: object, value: WriteT) -> None: ...

    def eq(self, value: ReadValueT) -> Predicate[OwnerT]: ...
    def ne(self, value: ReadValueT) -> Predicate[OwnerT]: ...
    def is_null(self) -> Predicate[OwnerT]: ...
    def is_not_null(self) -> Predicate[OwnerT]: ...
    def asc(self) -> OrderBy[OwnerT]: ...
    def desc(self) -> OrderBy[OwnerT]: ...
    def to(self, value: ReadValueT) -> Assignment[OwnerT]: ...


type _Col[WriteModelT: Table[Any], FetchedModelT, T] = Attr[
    WriteModelT,
    FetchedModelT,
    WriteModelT,
    T,
    T,
]

type _GenCol[WriteModelT: Table[Any], FetchedModelT, T] = Attr[
    WriteModelT,
    FetchedModelT,
    WriteModelT,
    T | Missing,
    T,
]

type Col[WriteModelT: Table[Any], FetchedModelT, T] = _Col[
    WriteModelT,
    FetchedModelT,
    T,
]

type GenCol[WriteModelT: Table[Any], FetchedModelT, T] = _GenCol[
    WriteModelT,
    FetchedModelT,
    T,
]


class _SelectableModelClass(Protocol[SelectableOwnerT, SelectableReadT]):
    @classmethod
    def __owner_type__(cls) -> type[SelectableOwnerT]: ...

    @classmethod
    def __read_type__(cls) -> type[SelectableReadT]: ...


class Table(Generic[StateT]):
    @classmethod
    def __owner_type__(cls) -> type[Self]:
        return cast(type[Self], cls)


@dataclass_transform(
    field_specifiers=(Integer, Real, Text, Blob, Json, Boolean, DateTime),
    kw_only_default=True,
)
class ModelMeta(type):
    """Typing/runtime hook for direct public column descriptors.

    Intended runtime behavior:
    - treat public column descriptors like `email: User.Col[str] = Text(...)`
      as both constructor fields and query descriptors
    - use descriptor `__set__` typing for constructor/write values
    - bind public descriptors directly on the model class
    - store values in hidden internal storage keyed by public names
    - keep fetched-state generated values narrowed relative to pending-state values
    """


class Model(Generic[StateT, ReadModelT], Table[StateT], metaclass=ModelMeta):
    type Col[T] = Attr[Self, ReadModelT, Self, T, T]
    type GenCol[T] = Attr[Self, ReadModelT, Self, T | Missing, T]

    @classmethod
    def __read_type__(cls) -> type[ReadModelT]:
        return cast(type[ReadModelT], cls)


class SelectModelQuery(Generic[SelectOwnerT, ReadModelT]):
    def all(self) -> Self: ...
    def where(self, predicate: Predicate[SelectOwnerT], /, *predicates: Predicate[SelectOwnerT]) -> Self: ...
    def order_by(self, *ordering: OrderBy[SelectOwnerT]) -> Self: ...
    def limit(self, value: int) -> Self: ...
    def offset(self, value: int) -> Self: ...


class SelectValueQuery(Generic[OwnerT, T]):
    def all(self) -> Self: ...
    def where(self, predicate: Predicate[OwnerT], /, *predicates: Predicate[OwnerT]) -> Self: ...
    def order_by(self, *ordering: OrderBy[OwnerT]) -> Self: ...
    def limit(self, value: int) -> Self: ...
    def offset(self, value: int) -> Self: ...


class SelectTupleQuery(Generic[OwnerT, *Ts]):
    def all(self) -> Self: ...
    def where(self, predicate: Predicate[OwnerT], /, *predicates: Predicate[OwnerT]) -> Self: ...
    def order_by(self, *ordering: OrderBy[OwnerT]) -> Self: ...
    def limit(self, value: int) -> Self: ...
    def offset(self, value: int) -> Self: ...


class InsertQuery(Generic[ModelT]):
    pass


class UpdateQuery(Generic[ModelT]):
    def all(self) -> Self: ...
    def set(self, assignment: Assignment[ModelT], /, *assignments: Assignment[ModelT]) -> Self: ...
    def where(self, predicate: Predicate[ModelT], /, *predicates: Predicate[ModelT]) -> Self: ...


class DeleteQuery(Generic[ModelT]):
    def all(self) -> Self: ...
    def where(self, predicate: Predicate[ModelT], /, *predicates: Predicate[ModelT]) -> Self: ...


class Transaction:
    async def __aenter__(self) -> Self: ...
    async def __aexit__(self, exc_type: object, exc_value: object, traceback: object) -> None: ...

    @overload
    async def fetch_all(
        self, query: SelectModelQuery[SelectOwnerT, ReadModelT]
    ) -> list[ReadModelT]: ...
    @overload
    async def fetch_all(self, query: SelectValueQuery[OwnerT, T]) -> list[T]: ...
    @overload
    async def fetch_all(
        self, query: SelectTupleQuery[OwnerT, *Ts]
    ) -> list[tuple[*Ts]]: ...
    async def fetch_all(self, query: object) -> object: ...

    @overload
    async def fetch_one(
        self, query: SelectModelQuery[SelectOwnerT, ReadModelT]
    ) -> ReadModelT | None: ...
    @overload
    async def fetch_one(self, query: SelectValueQuery[OwnerT, T]) -> T | None: ...
    @overload
    async def fetch_one(
        self, query: SelectTupleQuery[OwnerT, *Ts]
    ) -> tuple[*Ts] | None: ...
    async def fetch_one(self, query: object) -> object: ...

    async def execute(
        self, query: InsertQuery[Any] | UpdateQuery[Any] | DeleteQuery[Any]
    ) -> None: ...


class Database:
    def __init__(self, _initialized: Never, /) -> None: ...

    @classmethod
    async def initialize(
        cls,
        dsn: str,
        /,
        *,
        models: Sequence[type[Table[Any]]] = (),
        schema_policy: SchemaPolicy = "strict",
        pool_size: int = 5,
        acquire_timeout: float = 30.0,
    ) -> Self: ...

    def transaction(self, *, timeout: float | None = None) -> Transaction: ...
    async def close(self) -> None: ...


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


def select(*args: object) -> object: ...


def insert(row: ModelT, /) -> InsertQuery[ModelT]: ...


def update(model: type[ModelT], /) -> UpdateQuery[ModelT]: ...


def delete(model: type[ModelT], /) -> DeleteQuery[ModelT]: ...

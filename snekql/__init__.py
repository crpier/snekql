"""Public API surface for snekql."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import (
    Any,
    Generic,
    Literal,
    Never,
    Protocol,
    Self,
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
    """Marker state for application-constructed table models.

    >>> state: type[Pending] = Pending
    >>> state.__name__
    'Pending'
    """

    pass


class Fetched:
    """Marker state for table models materialized by the Query Runtime.

    A generated column may be `T | Missing` on `Pending` instances but `T` on
    `Fetched` instances.

    >>> state: type[Fetched] = Fetched
    >>> state.__name__
    'Fetched'
    """

    pass


class Missing:
    """Sentinel type for generated values that are not available yet.

    >>> MISSING is Missing()
    True
    >>> repr(MISSING)
    'MISSING'
    """

    _instance: Self | None = None

    def __new__(cls) -> Self:
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __repr__(self) -> str:
        return "MISSING"


MISSING = Missing()


# Startup schema verification behavior: strict raises on drift, warn logs and
# continues. TypeAliasType currently exposes a read-only generic __doc__.
type SchemaPolicy = Literal["strict", "warn"]


class SnekqlError(Exception):
    """Base class for all intentional package-originated exceptions.

    >>> isinstance(ModelDeclarationError("bad model"), SnekqlError)
    True
    """

    pass


class ModelError(SnekqlError):
    """Base class for table model declaration and validation failures."""

    pass


class ModelDeclarationError(ModelError):
    """Raised when a table model class violates snekql declaration rules."""

    pass


class ModelValidationError(ModelError):
    """Raised when pending or fetched table model values fail validation."""

    pass


class FrozenModelError(ModelError):
    """Raised when code attempts to mutate an immutable table model instance."""

    pass


class QueryError(SnekqlError):
    """Base class for query builder construction and compilation failures."""

    pass


class QueryConstructionError(QueryError):
    """Raised when query builder methods are used in an invalid sequence."""

    pass


class QueryCompilationError(QueryError):
    """Raised when a built query cannot be compiled into valid SQLite SQL."""

    pass


class DatabaseRuntimeError(SnekqlError):
    """Base class for Database and Transaction execution failures."""

    pass


class DatabaseClosedError(DatabaseRuntimeError):
    """Raised when a closed Database is used for new work."""

    pass


class TransactionClosedError(DatabaseRuntimeError):
    """Raised when a Transaction is used after it has closed."""

    pass


class PoolTimeoutError(DatabaseRuntimeError):
    """Raised when acquiring a database connection exceeds the timeout."""

    pass


class DatabaseCloseTimeoutError(DatabaseRuntimeError):
    """Raised when Database.close cannot finish before its timeout."""

    pass


class DatabaseClosingError(DatabaseRuntimeError):
    """Raised when new work starts while Database.close is in progress."""

    pass


class ExecutionError(DatabaseRuntimeError):
    """Database execution failure with query context.

    >>> error = ExecutionError("failed", sql="SELECT ?", params=(1,))
    >>> error.sql
    'SELECT ?'
    """

    sql: str
    params: tuple[object, ...]

    def __init__(
        self,
        message: str,
        *,
        sql: str,
        params: tuple[object, ...],
    ) -> None:
        super().__init__(message)
        self.sql: str = sql
        self.params: tuple[object, ...] = params

    def __str__(self) -> str:
        message = super().__str__()
        return f"{message} sql={self.sql!r} params={self.params!r}"


class SchemaError(SnekqlError):
    """Base class for schema creation and verification failures."""

    pass


class SchemaVerificationError(SchemaError):
    """Raised when an existing database table drifts from model DDL."""

    pass


class Integer:
    """SQLite INTEGER column declaration for table model fields.

    >>> class User[S = Pending](Model[S, "User[Fetched]"]):
    ...     id: User.GenCol[int] = Integer(primary_key=True, default=MISSING)
    """

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
    """SQLite REAL column declaration for float-like model values.

    >>> class Reading[S = Pending](Model[S, "Reading[Fetched]"]):
    ...     value: Reading.Col[float] = Real(nullable=False)
    """

    def __new__(
        cls,
        *,
        primary_key: bool = False,
        nullable: bool | None = None,
        default: object = ...,
        default_factory: Callable[[], object] = ...,
    ) -> Any: ...


class Text:
    """SQLite TEXT column declaration for string model values.

    >>> class User[S = Pending](Model[S, "User[Fetched]"]):
    ...     email: User.Col[str] = Text(nullable=False)
    """

    def __new__(
        cls,
        *,
        primary_key: bool = False,
        nullable: bool | None = None,
        default: object = ...,
        default_factory: Callable[[], object] = ...,
    ) -> Any: ...


class Blob:
    """SQLite BLOB column declaration for bytes model values.

    >>> class File[S = Pending](Model[S, "File[Fetched]"]):
    ...     content: File.Col[bytes] = Blob(nullable=False)
    """

    def __new__(
        cls,
        *,
        primary_key: bool = False,
        nullable: bool | None = None,
        default: object = ...,
        default_factory: Callable[[], object] = ...,
    ) -> Any: ...


class Json:
    """SQLite TEXT-backed JSON column declaration.

    Values are serialized to JSON text before writes and decoded before fetched
    model validation.

    >>> class Event[S = Pending](Model[S, "Event[Fetched]"]):
    ...     payload: Event.Col[dict[str, object]] = Json(nullable=False)
    """

    def __new__(
        cls,
        *,
        nullable: bool | None = None,
        default: object = ...,
        default_factory: Callable[[], object] = ...,
    ) -> Any: ...


class Boolean:
    """SQLite INTEGER-backed boolean column declaration.

    >>> class FeatureFlag[S = Pending](Model[S, "FeatureFlag[Fetched]"]):
    ...     enabled: FeatureFlag.Col[bool] = Boolean(default=False)
    """

    def __new__(
        cls,
        *,
        nullable: bool | None = None,
        default: object = ...,
        default_factory: Callable[[], object] = ...,
    ) -> Any: ...


class DateTime:
    """SQLite TEXT-backed timezone-aware datetime column declaration.

    >>> class Event[S = Pending](Model[S, "Event[Fetched]"]):
    ...     created_at: Event.GenCol[datetime] = DateTime(
    ...         server_default=CurrentTimestamp(),
    ...         default=MISSING,
    ...     )
    """

    def __new__(
        cls,
        *,
        server_default: object | None = None,
        nullable: bool | None = None,
        default: object = ...,
        default_factory: Callable[[], object] = ...,
    ) -> Any: ...


class CurrentTimestamp:
    """Server default marker for database-filled UTC timestamps.

    >>> DateTime(server_default=CurrentTimestamp(), default=MISSING)
    """

    pass


class Predicate(Generic[OwnerT]):
    """Boolean SQL predicate for one table model.

    Predicates are produced by column descriptor methods such as `User.email.eq`.
    They compose with `&`, `|`, and `~` instead of Python comparison operators.
    """

    def __and__(self, other: Predicate[OwnerT]) -> Predicate[OwnerT]: ...
    def __or__(self, other: Predicate[OwnerT]) -> Predicate[OwnerT]: ...
    def __invert__(self) -> Predicate[OwnerT]: ...


class OrderBy(Generic[OwnerT]):
    """SQL ordering expression for one table model.

    `OrderBy` values are produced by column descriptor methods like `.asc()` and
    `.desc()` and consumed by select query builders.
    """

    pass


class Assignment(Generic[OwnerT]):
    """SQL update assignment for one table model.

    `Assignment` values are produced by update-assignable column descriptors via
    `.to(value)` and consumed by `update(Model).set(...)`.
    """

    pass


class Attr(Generic[WriteOwnerT, LoadedOwnerT, OwnerT, WriteT, ReadValueT]):
    """Typed model column descriptor used for fields and query construction.

    The descriptor exposes pending-state write values on application-created
    models, fetched-state read values on runtime materialized models, and query
    helper methods on the model class.
    """
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


# Private normal persisted-column alias used to build the public Col alias.
type _Col[WriteModelT: Table[Any], FetchedModelT, T] = Attr[
    WriteModelT,
    FetchedModelT,
    WriteModelT,
    T,
    T,
]

# Private generated-column alias used to model pending Missing vs fetched T.
type _GenCol[WriteModelT: Table[Any], FetchedModelT, T] = Attr[
    WriteModelT,
    FetchedModelT,
    WriteModelT,
    T | Missing,
    T,
]

# Public normal persisted-column alias for external table model helpers.
type Col[WriteModelT: Table[Any], FetchedModelT, T] = _Col[
    WriteModelT,
    FetchedModelT,
    T,
]

# Public generated/server-filled column alias for external model helpers.
type GenCol[WriteModelT: Table[Any], FetchedModelT, T] = _GenCol[
    WriteModelT,
    FetchedModelT,
    T,
]


class _SelectableModelClass(Protocol[SelectableOwnerT, SelectableReadT]):
    """Structural type for model classes accepted by `select(Model)`.

    The protocol lets pyright connect the writable owner model type with the
    fetched read model type exposed by table model classes.
    """

    @classmethod
    def __owner_type__(cls) -> type[SelectableOwnerT]: ...

    @classmethod
    def __read_type__(cls) -> type[SelectableReadT]: ...


class Table(Generic[StateT]):
    """Base type shared by concrete table models in any lifecycle state.

    Query builders use this shallow base to constrain model-like generic
    parameters without requiring runtime construction behavior yet.
    """

    @classmethod
    def __owner_type__(cls) -> type[Self]:
        return cls


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
    """Base class for declaring table models.

    >>> class User[S = Pending](Model[S, "User[Fetched]"]):
    ...     email: User.Col[str] = Text(nullable=False)
    """

    # Normal persisted-column alias scoped to the declaring model class.
    type Col[T] = Attr[Self, ReadModelT, Self, T, T]
    # Generated/server-filled column alias scoped to the declaring model class.
    type GenCol[T] = Attr[Self, ReadModelT, Self, T | Missing, T]

    @classmethod
    def __read_type__(cls) -> type[ReadModelT]:
        return cast(type[ReadModelT], cls)


class SelectModelQuery(Generic[SelectOwnerT, ReadModelT]):
    """Immutable select query that returns fetched table model instances."""

    def all(self) -> Self: ...
    def where(
        self,
        predicate: Predicate[SelectOwnerT],
        /,
        *predicates: Predicate[SelectOwnerT],
    ) -> Self: ...
    def order_by(self, *ordering: OrderBy[SelectOwnerT]) -> Self: ...
    def limit(self, value: int) -> Self: ...
    def offset(self, value: int) -> Self: ...


class SelectValueQuery(Generic[OwnerT, T]):
    """Immutable select query that returns one scalar column value per row."""

    def all(self) -> Self: ...
    def where(
        self,
        predicate: Predicate[OwnerT],
        /,
        *predicates: Predicate[OwnerT],
    ) -> Self: ...
    def order_by(self, *ordering: OrderBy[OwnerT]) -> Self: ...
    def limit(self, value: int) -> Self: ...
    def offset(self, value: int) -> Self: ...


class SelectTupleQuery(Generic[OwnerT, *Ts]):
    """Immutable select query that returns selected column tuples per row."""

    def all(self) -> Self: ...
    def where(
        self,
        predicate: Predicate[OwnerT],
        /,
        *predicates: Predicate[OwnerT],
    ) -> Self: ...
    def order_by(self, *ordering: OrderBy[OwnerT]) -> Self: ...
    def limit(self, value: int) -> Self: ...
    def offset(self, value: int) -> Self: ...


class InsertQuery(Generic[ModelT]):
    """Immutable insert statement for one pending table model instance."""

    pass


class UpdateQuery(Generic[ModelT]):
    """Immutable update statement for one table model."""

    def all(self) -> Self: ...
    def set(
        self,
        assignment: Assignment[ModelT],
        /,
        *assignments: Assignment[ModelT],
    ) -> Self: ...
    def where(
        self,
        predicate: Predicate[ModelT],
        /,
        *predicates: Predicate[ModelT],
    ) -> Self: ...


class DeleteQuery(Generic[ModelT]):
    """Immutable delete statement for one table model."""

    def all(self) -> Self: ...
    def where(
        self,
        predicate: Predicate[ModelT],
        /,
        *predicates: Predicate[ModelT],
    ) -> Self: ...


class Transaction:
    """Async transaction that executes built snekql queries on one connection.

    >>> async def create_user(transaction: Transaction, user: User[Pending]) -> None:
    ...     await transaction.execute(insert(user))
    """

    async def __aenter__(self) -> Self: ...
    async def __aexit__(
        self,
        exc_type: object,
        exc_value: object,
        traceback: object,
    ) -> None: ...

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
    """Initialized snekql runtime service for SQLite-backed execution.

    `Database.initialize(...)` is the only public construction path. A Database
    owns connectivity, schema startup work, and transaction entry.
    """

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


__all__ = [
    "Assignment",
    "Attr",
    "Blob",
    "Boolean",
    "CurrentTimestamp",
    "Database",
    "DatabaseCloseTimeoutError",
    "DatabaseClosedError",
    "DatabaseClosingError",
    "DatabaseRuntimeError",
    "DateTime",
    "DeleteQuery",
    "ExecutionError",
    "Fetched",
    "FrozenModelError",
    "InsertQuery",
    "Integer",
    "Json",
    "MISSING",
    "Missing",
    "Model",
    "ModelDeclarationError",
    "ModelError",
    "ModelMeta",
    "ModelValidationError",
    "OrderBy",
    "Pending",
    "PoolTimeoutError",
    "Predicate",
    "QueryCompilationError",
    "QueryConstructionError",
    "QueryError",
    "Real",
    "SchemaError",
    "SchemaPolicy",
    "SchemaVerificationError",
    "SelectModelQuery",
    "SelectTupleQuery",
    "SelectValueQuery",
    "SnekqlError",
    "Table",
    "Text",
    "Transaction",
    "TransactionClosedError",
    "UpdateQuery",
    "delete",
    "insert",
    "select",
    "update",
]

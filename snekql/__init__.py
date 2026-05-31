"""Public API surface for snekql."""

from __future__ import annotations

import logging
from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, datetime
from json import JSONDecodeError, dumps, loads
from types import EllipsisType
from aiosqlite import Connection, Error, connect
from typing import (
    Any,
    ClassVar,
    Generic,
    Literal,
    Never,
    Protocol,
    Self,
    TypeVar,
    TypeVarTuple,
    cast,
    get_origin,
    dataclass_transform,
    overload,
)

type SQLiteStorageClass = Literal["INTEGER", "REAL", "TEXT", "BLOB"]

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


_LOGGER = logging.getLogger(__name__)


def _quote_sqlite_identifier(identifier: str) -> str:
    escaped_identifier = identifier.replace('"', '""')
    return f'"{escaped_identifier}"'


def _parse_sqlite_dsn(dsn: str) -> str:
    if not dsn.startswith("sqlite:///"):
        raise DatabaseRuntimeError(
            "dsn must be a URL-style SQLite DSN such as 'sqlite:///app.db'",
        )
    remainder = dsn.removeprefix("sqlite:///")
    if remainder == "":
        raise DatabaseRuntimeError("SQLite DSN must include a database path")
    if remainder == ":memory:":
        return ":memory:"
    if "?" in remainder or "#" in remainder:
        raise DatabaseRuntimeError(
            "SQLite DSN query strings and fragments are not supported",
        )
    if remainder.startswith("/"):
        return remainder
    return remainder


async def _open_sqlite_connection(database_path: str) -> Connection:
    try:
        connection = await connect(database_path, isolation_level=None)
        cursor = await connection.execute("SELECT 1")
        try:
            _ = await cursor.fetchone()
        finally:
            await cursor.close()
        return connection
    except Error as error:
        raise DatabaseRuntimeError("could not initialize SQLite connection") from error


def _require_model_columns(
    model: type[Table[Any]],
) -> dict[str, Attr[Any, Any, Any, Any, Any]]:
    columns = getattr(model, "__snekql_columns__", None)
    if not isinstance(columns, dict):
        raise ModelDeclarationError("schema setup requires snekql table models")
    return cast(dict[str, Attr[Any, Any, Any, Any, Any]], columns)


def _require_model_table_name(model: type[Table[Any]]) -> str:
    table_name = getattr(model, "__tablename__", None)
    if not isinstance(table_name, str):
        raise ModelDeclarationError("schema setup requires snekql table models")
    return table_name


def _compile_column_definition(
    name: str,
    column: Attr[Any, Any, Any, Any, Any],
) -> str:
    parts = [_quote_sqlite_identifier(name), column.sqlite_storage_class]
    if column.primary_key:
        parts.append("PRIMARY KEY")
    if column.auto_increment:
        parts.append("AUTOINCREMENT")
    if column.nullable is False and not column.primary_key:
        parts.append("NOT NULL")
    if isinstance(column.server_default, CurrentTimestamp):
        parts.append("DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))")
    return " ".join(parts)


def _compile_create_table_sql(model: type[Table[Any]]) -> str:
    table_name = _require_model_table_name(model)
    columns = _require_model_columns(model)
    column_sql = ", ".join(
        _compile_column_definition(name, column) for name, column in columns.items()
    )
    return f"CREATE TABLE {_quote_sqlite_identifier(table_name)} ({column_sql}) STRICT"


async def _fetch_existing_create_table_sql(
    connection: Connection,
    table_name: str,
) -> str | None:
    cursor = await connection.execute(
        "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = ?",
        (table_name,),
    )
    try:
        row = await cursor.fetchone()
    finally:
        await cursor.close()
    if row is None:
        return None
    value = row[0]
    if not isinstance(value, str):
        raise SchemaVerificationError(
            f"SQLite metadata for table {table_name!r} did not contain SQL text",
        )
    return value


def _normalize_snekql_create_table_sql(sql: str) -> str:
    lines = [line.strip() for line in sql.strip().rstrip(";").splitlines()]
    normalized_sql = " ".join(line for line in lines if line)
    return normalized_sql.replace("( ", "(").replace(" )", ")").replace(" ,", ",")


async def _verify_or_create_model_table(
    connection: Connection,
    model: type[Table[Any]],
    schema_policy: SchemaPolicy,
) -> None:
    table_name = _require_model_table_name(model)
    expected_sql = _compile_create_table_sql(model)
    existing_sql = await _fetch_existing_create_table_sql(connection, table_name)
    if existing_sql is None:
        _ = await connection.execute(expected_sql)
        return
    if _normalize_snekql_create_table_sql(
        existing_sql,
    ) == _normalize_snekql_create_table_sql(expected_sql):
        return
    message = f"schema drift detected for table {table_name!r}"
    if schema_policy == "strict":
        raise SchemaVerificationError(message)
    _LOGGER.warning(
        "schema drift detected",
        extra={"table_name": table_name},
    )


def _validate_schema_models(models: Sequence[type[Table[Any]]]) -> None:
    table_names: set[str] = set()
    for model in models:
        table_name = _require_model_table_name(model)
        if table_name in table_names:
            raise SchemaError(f"duplicate table name: {table_name!r}")
        table_names.add(table_name)


async def _rollback_schema_setup(connection: Connection) -> None:
    try:
        _ = await connection.execute("ROLLBACK")
    except Error:
        pass


def _validate_schema_policy(schema_policy: SchemaPolicy) -> None:
    if schema_policy not in ("strict", "warn"):
        raise SchemaError("schema_policy must be 'strict' or 'warn'")


async def _initialize_sqlite_schema(
    connection: Connection,
    models: Sequence[type[Table[Any]]],
    schema_policy: SchemaPolicy,
) -> None:
    _validate_schema_policy(schema_policy)
    _validate_schema_models(models)
    if not models:
        return
    try:
        _ = await connection.execute("BEGIN")
        for model in models:
            await _verify_or_create_model_table(connection, model, schema_policy)
        _ = await connection.execute("COMMIT")
    except Error as error:
        await _rollback_schema_setup(connection)
        raise SchemaError("SQLite schema setup failed") from error
    except Exception:
        await _rollback_schema_setup(connection)
        raise


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
        default_factory: Callable[[], object] | EllipsisType = ...,
    ) -> Any:
        return Attr[Any, Any, Any, Any, Any](
            default=default,
            default_factory=default_factory,
            nullable=nullable,
            primary_key=primary_key,
            auto_increment=auto_increment,
            sqlite_storage_class="INTEGER",
            storage_type_name="Integer",
        )


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
        default_factory: Callable[[], object] | EllipsisType = ...,
    ) -> Any:
        return Attr[Any, Any, Any, Any, Any](
            default=default,
            default_factory=default_factory,
            nullable=nullable,
            primary_key=primary_key,
            sqlite_storage_class="REAL",
            storage_type_name="Real",
        )


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
        default_factory: Callable[[], object] | EllipsisType = ...,
    ) -> Any:
        return Attr[Any, Any, Any, Any, Any](
            default=default,
            default_factory=default_factory,
            nullable=nullable,
            primary_key=primary_key,
            sqlite_storage_class="TEXT",
            storage_type_name="Text",
        )


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
        default_factory: Callable[[], object] | EllipsisType = ...,
    ) -> Any:
        return Attr[Any, Any, Any, Any, Any](
            default=default,
            default_factory=default_factory,
            nullable=nullable,
            primary_key=primary_key,
            sqlite_storage_class="BLOB",
            storage_type_name="Blob",
        )


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
        default_factory: Callable[[], object] | EllipsisType = ...,
    ) -> Any:
        return Attr[Any, Any, Any, Any, Any](
            default=default,
            default_factory=default_factory,
            nullable=nullable,
            sqlite_storage_class="TEXT",
            storage_type_name="Json",
        )


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
        default_factory: Callable[[], object] | EllipsisType = ...,
    ) -> Any:
        return Attr[Any, Any, Any, Any, Any](
            default=default,
            default_factory=default_factory,
            nullable=nullable,
            sqlite_storage_class="INTEGER",
            storage_type_name="Boolean",
        )


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
        default_factory: Callable[[], object] | EllipsisType = ...,
    ) -> Any:
        return Attr[Any, Any, Any, Any, Any](
            default=default,
            default_factory=default_factory,
            nullable=nullable,
            server_default=server_default,
            sqlite_storage_class="TEXT",
            storage_type_name="DateTime",
        )


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

    def __and__(self, other: Predicate[OwnerT]) -> Predicate[OwnerT]:
        return Predicate()

    def __or__(self, other: Predicate[OwnerT]) -> Predicate[OwnerT]:
        return Predicate()

    def __invert__(self) -> Predicate[OwnerT]:
        return Predicate()


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

    def __init__(
        self,
        *,
        default: object = ...,
        default_factory: Callable[[], object] | EllipsisType = ...,
        nullable: bool | None = None,
        primary_key: bool = False,
        auto_increment: bool = False,
        server_default: object | None = None,
        sqlite_storage_class: SQLiteStorageClass,
        storage_type_name: str,
    ) -> None:
        self.auto_increment: bool = auto_increment
        self.default: object = default
        self.default_factory: Callable[[], object] | EllipsisType = default_factory
        self.is_generated: bool = False
        self.name: str | None = None
        self.nullable: bool | None = nullable
        self.primary_key: bool = primary_key
        self.server_default: object | None = server_default
        self.sqlite_storage_class: SQLiteStorageClass = sqlite_storage_class
        self.storage_type_name: str = storage_type_name

    def __set_name__(self, owner: type[object], name: str) -> None:
        self.name = name

    @overload
    def __get__(
        self, instance: None, owner: type[Any]
    ) -> Attr[WriteOwnerT, LoadedOwnerT, OwnerT, WriteT, ReadValueT]: ...
    @overload
    def __get__(self, instance: WriteOwnerT, owner: type[Any]) -> WriteT: ...
    @overload
    def __get__(self, instance: LoadedOwnerT, owner: type[Any]) -> ReadValueT: ...
    def __get__(self, instance: object | None, owner: type[Any]) -> object:
        if instance is None:
            return self
        storage = cast(
            dict[str, object],
            object.__getattribute__(instance, "__dict__"),
        )
        return storage[self._require_name()]

    def __set__(self, instance: object, value: WriteT) -> None:
        if getattr(instance, "_snekql_frozen", False):
            raise FrozenModelError("table models are immutable")
        storage = cast(
            dict[str, object],
            object.__getattribute__(instance, "__dict__"),
        )
        storage[self._require_name()] = value

    def build_default(self) -> object:
        if not isinstance(self.default_factory, EllipsisType):
            return self.default_factory()
        return self.default

    def decode_sqlite(self, value: object) -> object:
        """Decode a SQLite value to its logical Python value."""

        try:
            decoded_value = self._decode_sqlite(value)
            return self._coerce_logical_value(decoded_value, fetched=True)
        except SnekqlError:
            raise
        except Exception as error:
            raise ModelValidationError(
                f"invalid database value for {self._require_name()!r}",
            ) from error

    def encode_sqlite(self, value: object) -> object:
        """Encode a logical Python value for SQLite storage."""

        try:
            logical_value = self._coerce_logical_value(value, fetched=False)
            if logical_value is MISSING:
                return MISSING
            return self._encode_sqlite(logical_value)
        except SnekqlError:
            raise
        except Exception as error:
            raise ModelValidationError(
                f"invalid model value for {self._require_name()!r}",
            ) from error

    def validate_model_value(self, value: object) -> object:
        """Validate and normalize a pending model value."""

        try:
            return self._coerce_logical_value(value, fetched=False)
        except SnekqlError:
            raise
        except Exception as error:
            raise ModelValidationError(
                f"invalid model value for {self._require_name()!r}",
            ) from error

    def _require_name(self) -> str:
        if self.name is None:
            raise ModelDeclarationError("column descriptor is not bound")
        return self.name

    def _coerce_logical_value(self, value: object, *, fetched: bool) -> object:
        if value is MISSING:
            if self.is_generated and not fetched:
                return MISSING
            raise ModelValidationError(
                f"missing generated value for {self._require_name()!r}"
            )
        if value is None:
            if self.nullable is False:
                raise ModelValidationError(f"{self._require_name()!r} cannot be null")
            return None
        if self.storage_type_name == "Integer":
            if type(value) is not int:
                raise ModelValidationError(f"{self._require_name()!r} must be an int")
            return value
        if self.storage_type_name == "Real":
            if isinstance(value, bool) or not isinstance(value, int | float):
                raise ModelValidationError(f"{self._require_name()!r} must be a number")
            return float(value)
        if self.storage_type_name == "Text":
            if not isinstance(value, str):
                raise ModelValidationError(f"{self._require_name()!r} must be a str")
            return value
        if self.storage_type_name == "Blob":
            if not isinstance(value, bytes):
                raise ModelValidationError(f"{self._require_name()!r} must be bytes")
            return value
        if self.storage_type_name == "Json":
            try:
                _ = dumps(value, separators=(",", ":"))
            except (TypeError, ValueError) as error:
                raise ModelValidationError(
                    f"{self._require_name()!r} is not JSON serializable",
                ) from error
            return value
        if self.storage_type_name == "Boolean":
            if type(value) is not bool:
                raise ModelValidationError(f"{self._require_name()!r} must be a bool")
            return value
        if self.storage_type_name == "DateTime":
            if not isinstance(value, datetime):
                raise ModelValidationError(
                    f"{self._require_name()!r} must be a datetime",
                )
            return self._normalize_datetime(value)
        raise ModelDeclarationError(
            f"unknown storage type {self.storage_type_name!r}",
        )

    def _decode_sqlite(self, value: object) -> object:
        if value is None:
            return None
        if self.storage_type_name == "Json":
            if not isinstance(value, str):
                raise ModelValidationError(
                    f"{self._require_name()!r} database value must be JSON text",
                )
            try:
                return loads(value)
            except JSONDecodeError as error:
                raise ModelValidationError(
                    f"{self._require_name()!r} database value is not valid JSON",
                ) from error
        if self.storage_type_name == "Boolean":
            if value == 0:
                return False
            if value == 1:
                return True
            raise ModelValidationError(
                f"{self._require_name()!r} database value must be 0 or 1",
            )
        if self.storage_type_name == "DateTime":
            if not isinstance(value, str):
                raise ModelValidationError(
                    f"{self._require_name()!r} database value must be timestamp text",
                )
            return self._decode_datetime_text(value)
        return value

    def _decode_datetime_text(self, value: str) -> datetime:
        if not value.endswith("Z"):
            raise ModelValidationError(
                f"{self._require_name()!r} timestamp must end with Z",
            )
        try:
            parsed = datetime.fromisoformat(f"{value[:-1]}+00:00")
        except ValueError as error:
            raise ModelValidationError(
                f"{self._require_name()!r} timestamp is not valid ISO text",
            ) from error
        return self._normalize_datetime(parsed)

    def _encode_sqlite(self, value: object) -> object:
        if value is None:
            return None
        if self.storage_type_name == "Json":
            try:
                return dumps(value, separators=(",", ":"))
            except (TypeError, ValueError) as error:
                raise ModelValidationError(
                    f"{self._require_name()!r} is not JSON serializable",
                ) from error
        if self.storage_type_name == "Boolean":
            return 1 if value else 0
        if self.storage_type_name == "DateTime":
            timestamp = cast(datetime, value)
            return (
                timestamp.strftime("%Y-%m-%dT%H:%M:%S.")
                + f"{timestamp.microsecond // 1000:03d}Z"
            )
        return value

    def _normalize_datetime(self, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ModelValidationError(
                f"{self._require_name()!r} must be timezone-aware",
            )
        utc_value = value.astimezone(UTC)
        milliseconds = utc_value.microsecond // 1000
        return utc_value.replace(microsecond=milliseconds * 1000)

    def eq(self, value: ReadValueT) -> Predicate[OwnerT]:
        return Predicate()

    def ne(self, value: ReadValueT) -> Predicate[OwnerT]:
        return Predicate()

    def is_null(self) -> Predicate[OwnerT]:
        return Predicate()

    def is_not_null(self) -> Predicate[OwnerT]:
        return Predicate()

    def in_(self, value: ReadValueT, /, *values: ReadValueT) -> Predicate[OwnerT]:
        return Predicate()

    def not_in(
        self,
        value: ReadValueT,
        /,
        *values: ReadValueT,
    ) -> Predicate[OwnerT]:
        return Predicate()

    def like(self, pattern: str) -> Predicate[OwnerT]:
        return Predicate()

    def not_like(self, pattern: str) -> Predicate[OwnerT]:
        return Predicate()

    def asc(self) -> OrderBy[OwnerT]:
        return OrderBy()

    def desc(self) -> OrderBy[OwnerT]:
        return OrderBy()

    def to(self, value: ReadValueT) -> Assignment[OwnerT]:
        return Assignment()


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

    def __new__(
        mcls,
        name: str,
        bases: tuple[type, ...],
        namespace: dict[str, object],
        **kwargs: object,
    ) -> type:
        if name != "Model":
            for base in bases:
                if isinstance(base, ModelMeta):
                    if base.__name__ != "Model":
                        raise ModelDeclarationError(
                            f"cannot subclass concrete model: {base.__name__}",
                        )
                    continue
                if base.__name__ == "Generic":
                    continue
                raise ModelDeclarationError(
                    f"model mixin bases are not supported: {base.__name__}",
                )
        model_class = super().__new__(mcls, name, bases, namespace, **kwargs)
        if name != "Model":
            annotations_object = namespace.get("__annotations__", {})
            if isinstance(annotations_object, dict):
                annotations = cast(dict[str, object], annotations_object)
                for annotated_name in annotations:
                    annotated_value = namespace.get(annotated_name)
                    if isinstance(annotated_value, Attr):
                        continue
                    if annotated_name == "__tablename__":
                        continue
                    if ModelMeta._is_classvar_annotation(annotations[annotated_name]):
                        continue
                    raise ModelDeclarationError(
                        f"unsupported model annotation: {annotated_name!r}",
                    )
            for attribute_name, attribute_value in namespace.items():
                if isinstance(attribute_value, property):
                    raise ModelDeclarationError(
                        f"computed properties are not supported: {attribute_name!r}",
                    )
                if getattr(attribute_value, "__isabstractmethod__", False):
                    raise ModelDeclarationError(
                        f"abstract members are not supported: {attribute_name!r}",
                    )
        annotations_object = namespace.get("__annotations__", {})
        annotations = (
            cast(dict[str, object], annotations_object)
            if isinstance(annotations_object, dict)
            else {}
        )
        columns: dict[str, Attr[Any, Any, Any, Any, Any]] = {}
        for attribute_name, attribute_value in model_class.__dict__.items():
            if isinstance(attribute_value, Attr):
                column = cast(Attr[Any, Any, Any, Any, Any], attribute_value)
                if not ModelMeta._is_sql_identifier(attribute_name):
                    raise ModelDeclarationError(
                        f"invalid column identifier: {attribute_name!r}",
                    )
                column.is_generated = ModelMeta._is_generated_annotation(
                    annotations.get(attribute_name),
                )
                ModelMeta._validate_column_declaration(attribute_name, column)
                columns[attribute_name] = column
        if name != "Model":
            table_name = namespace.get(
                "__tablename__",
                ModelMeta._infer_table_name(name),
            )
            if not isinstance(table_name, str) or not ModelMeta._is_sql_identifier(
                table_name,
            ):
                raise ModelDeclarationError(f"invalid table identifier: {table_name!r}")
            setattr(model_class, "__tablename__", table_name)
        setattr(model_class, "__snekql_columns__", columns)
        return model_class

    @staticmethod
    def _is_generated_annotation(annotation: object) -> bool:
        if annotation is None:
            return False
        return "GenCol[" in str(annotation)

    @staticmethod
    def _validate_column_declaration(
        name: str,
        column: Attr[Any, Any, Any, Any, Any],
    ) -> None:
        if isinstance(column.default, CurrentTimestamp):
            raise ModelDeclarationError(
                f"CurrentTimestamp cannot be a Python default for {name!r}",
            )
        if column.server_default is None:
            return
        if not isinstance(column.server_default, CurrentTimestamp):
            raise ModelDeclarationError(
                f"unsupported server default for {name!r}",
            )
        if column.storage_type_name != "DateTime":
            raise ModelDeclarationError(
                f"CurrentTimestamp requires a DateTime column: {name!r}",
            )
        if not column.is_generated:
            raise ModelDeclarationError(
                f"CurrentTimestamp requires a generated column: {name!r}",
            )
        if column.default is not MISSING:
            raise ModelDeclarationError(
                f"CurrentTimestamp generated columns must default to MISSING: {name!r}",
            )
        if not isinstance(column.default_factory, EllipsisType):
            raise ModelDeclarationError(
                f"CurrentTimestamp generated columns cannot use default_factory: {name!r}",
            )

    @staticmethod
    def _infer_table_name(class_name: str) -> str:
        characters: list[str] = []
        previous_was_lower_or_digit = False
        for character in class_name:
            if character.isupper() and previous_was_lower_or_digit:
                characters.append("_")
            characters.append(character.lower())
            previous_was_lower_or_digit = character.islower() or character.isdigit()
        return "".join(characters)

    @staticmethod
    def _is_classvar_annotation(annotation: object) -> bool:
        if isinstance(annotation, str):
            return annotation.startswith("ClassVar[") or annotation.startswith(
                "typing.ClassVar[",
            )
        return get_origin(annotation) is ClassVar

    @staticmethod
    def _is_sql_identifier(value: str) -> bool:
        if value == "":
            return False
        first_character = value[0]
        if not (first_character.isalpha() or first_character == "_"):
            return False
        return all(character.isalnum() or character == "_" for character in value)


class Model(Generic[StateT, ReadModelT], Table[StateT], metaclass=ModelMeta):
    """Base class for declaring table models.

    >>> class User[S = Pending](Model[S, "User[Fetched]"]):
    ...     email: User.Col[str] = Text(nullable=False)
    """

    __snekql_columns__: ClassVar[dict[str, Attr[Any, Any, Any, Any, Any]]]
    __tablename__: ClassVar[str]

    # Normal persisted-column alias scoped to the declaring model class.
    type Col[T] = Attr[Self, ReadModelT, Self, T, T]
    # Generated/server-filled column alias scoped to the declaring model class.
    type GenCol[T] = Attr[Self, ReadModelT, Self, T | Missing, T]

    def __init__(self, **values: object) -> None:
        remaining_values = dict(values)
        storage = cast(
            dict[str, object],
            object.__getattribute__(self, "__dict__"),
        )
        storage["_snekql_frozen"] = False
        storage["_snekql_state"] = "Pending"
        for name, column in self.__class__.__snekql_columns__.items():
            if name in remaining_values:
                value = remaining_values.pop(name)
            else:
                try:
                    value = column.build_default()
                except SnekqlError:
                    raise
                except Exception as error:
                    raise ModelValidationError(
                        f"default factory failed for {name!r}",
                    ) from error
            if isinstance(value, EllipsisType):
                raise ModelValidationError(f"missing required value for {name!r}")
            setattr(self, name, column.validate_model_value(value))
        if remaining_values:
            names = ", ".join(sorted(remaining_values))
            raise ModelValidationError(f"unknown model values: {names}")
        storage["_snekql_frozen"] = True

    def __setattr__(self, name: str, value: object) -> None:
        if getattr(self, "_snekql_frozen", False):
            raise FrozenModelError("table models are immutable")
        super().__setattr__(name, value)

    def __repr__(self) -> str:
        state = self._snekql_state_name()
        field_reprs: list[str] = []
        for name in self.__class__.__snekql_columns__:
            value = getattr(self, name)
            if value is MISSING:
                continue
            field_reprs.append(f"{name}={value!r}")
        fields = ", ".join(field_reprs)
        return f"{self.__class__.__name__}[{state}]({fields})"

    def __eq__(self, other: object) -> bool:
        if self.__class__ is not other.__class__:
            return False
        other_model = cast(Model[Any, Any], other)
        for name in self.__class__.__snekql_columns__:
            if getattr(self, name) != getattr(other_model, name):
                return False
        return True

    def __hash__(self) -> int:
        raise TypeError(f"unhashable type: {self.__class__.__name__!r}")

    def _snekql_state_name(self) -> str:
        storage = cast(
            dict[str, object],
            object.__getattribute__(self, "__dict__"),
        )
        state = storage.get("_snekql_state", "Pending")
        return cast(str, state)

    def _snekql_to_row(self) -> dict[str, object]:
        """Encode this model's present values for SQLite storage."""

        row: dict[str, object] = {}
        for name, column in self.__class__.__snekql_columns__.items():
            value = getattr(self, name)
            if value is MISSING:
                continue
            row[name] = column.encode_sqlite(value)
        return row

    @classmethod
    def _snekql_from_row(cls, row: Mapping[str, object]) -> Self:
        """Materialize a fetched model from SQLite storage values."""

        remaining_values = dict(row)
        model = object.__new__(cls)
        storage = cast(
            dict[str, object],
            object.__getattribute__(model, "__dict__"),
        )
        storage["_snekql_frozen"] = False
        storage["_snekql_state"] = "Fetched"
        for name, column in cls.__snekql_columns__.items():
            if name not in remaining_values:
                raise ModelValidationError(f"missing database value for {name!r}")
            value = column.decode_sqlite(remaining_values.pop(name))
            setattr(model, name, value)
        if remaining_values:
            names = ", ".join(sorted(remaining_values))
            raise ModelValidationError(f"unknown database values: {names}")
        storage["_snekql_frozen"] = True
        return model

    @classmethod
    def __read_type__(cls) -> type[ReadModelT]:
        return cast(type[ReadModelT], cls)


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

    pass


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

    _acquire_timeout: float
    _closed: bool
    _connection: Connection | None
    _database_path: str
    _pool_size: int

    def __init__(self, _initialized: Never, /) -> None:
        self._acquire_timeout = 0.0
        self._closed = True
        self._connection = None
        self._database_path = ""
        self._pool_size = 0
        raise DatabaseRuntimeError("use Database.initialize(...) to create a Database")

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
    ) -> Self:
        if pool_size < 1:
            raise DatabaseRuntimeError("pool_size must be at least 1")
        if acquire_timeout < 0:
            raise DatabaseRuntimeError("acquire_timeout must be non-negative")
        _validate_schema_policy(schema_policy)
        _validate_schema_models(models)
        database_path = _parse_sqlite_dsn(dsn)
        connection = await _open_sqlite_connection(database_path)
        try:
            await _initialize_sqlite_schema(connection, models, schema_policy)
        except Exception:
            await connection.close()
            raise
        database = cls.__new__(cls)
        database._acquire_timeout = acquire_timeout
        database._closed = False
        database._connection = connection
        database._database_path = database_path
        database._pool_size = pool_size
        return database

    def transaction(self, *, timeout: float | None = None) -> Transaction:
        if self._closed:
            raise DatabaseClosedError("database is closed")
        _ = timeout
        return Transaction()

    async def close(self) -> None:
        if self._closed:
            return
        connection = self._connection
        self._connection = None
        self._closed = True
        if connection is not None:
            await connection.close()


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
    return InsertQuery()


def update(model: type[ModelT], /) -> UpdateQuery[ModelT]:
    return UpdateQuery()


def delete(model: type[ModelT], /) -> DeleteQuery[ModelT]:
    return DeleteQuery()


__all__ = [
    "Assignment",
    "Attr",
    "Blob",
    "Boolean",
    "Col",
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
    "GenCol",
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

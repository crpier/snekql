"""SQLite storage declarations and value codecs for table models."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from json import JSONDecodeError, dumps, loads
from types import EllipsisType
from typing import Any, Generic, Literal, Self, TypeVar, cast, overload

from snekql.errors import (
    FrozenModelError,
    ModelDeclarationError,
    ModelValidationError,
    SnekqlError,
)
from snekql.expressions import Assignment, OrderBy, Predicate

type SQLiteStorageClass = Literal["INTEGER", "REAL", "TEXT", "BLOB"]

WriteOwnerT = TypeVar("WriteOwnerT")
LoadedOwnerT = TypeVar("LoadedOwnerT")
OwnerT = TypeVar("OwnerT")
WriteT = TypeVar("WriteT")
ReadValueT = TypeVar("ReadValueT")


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

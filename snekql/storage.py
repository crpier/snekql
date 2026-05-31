"""SQLite storage declarations and value codecs for table models."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from json import JSONDecodeError, dumps, loads
from types import EllipsisType
from typing import Any, Literal, Self, TypeVar, cast, overload

from snekql.errors import (
    FrozenModelError,
    ModelDeclarationError,
    ModelValidationError,
    QueryConstructionError,
    SnekqlError,
)
from snekql.expressions import Assignment, OrderBy, Predicate

type SQLiteStorageClass = Literal["INTEGER", "REAL", "TEXT", "BLOB"]


@dataclass(frozen=True, kw_only=True)
class _AttrConfig:
    """Constructor bundle for column descriptors.

    Keeping descriptor configuration in one value avoids long internal
    constructors while preserving explicit storage metadata at each call site.
    """

    sqlite_storage_class: SQLiteStorageClass
    storage_type_name: str
    auto_increment: bool = False
    default: object = ...
    default_factory: Callable[[], object] | EllipsisType = ...
    nullable: bool | None = None
    primary_key: bool = False
    server_default: object | None = None


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
            _AttrConfig(
                default=default,
                default_factory=default_factory,
                nullable=nullable,
                primary_key=primary_key,
                auto_increment=auto_increment,
                sqlite_storage_class="INTEGER",
                storage_type_name="Integer",
            ),
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
            _AttrConfig(
                default=default,
                default_factory=default_factory,
                nullable=nullable,
                primary_key=primary_key,
                sqlite_storage_class="REAL",
                storage_type_name="Real",
            ),
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
            _AttrConfig(
                default=default,
                default_factory=default_factory,
                nullable=nullable,
                primary_key=primary_key,
                sqlite_storage_class="TEXT",
                storage_type_name="Text",
            ),
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
            _AttrConfig(
                default=default,
                default_factory=default_factory,
                nullable=nullable,
                primary_key=primary_key,
                sqlite_storage_class="BLOB",
                storage_type_name="Blob",
            ),
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
            _AttrConfig(
                default=default,
                default_factory=default_factory,
                nullable=nullable,
                sqlite_storage_class="TEXT",
                storage_type_name="Json",
            ),
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
            _AttrConfig(
                default=default,
                default_factory=default_factory,
                nullable=nullable,
                sqlite_storage_class="INTEGER",
                storage_type_name="Boolean",
            ),
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
            _AttrConfig(
                default=default,
                default_factory=default_factory,
                nullable=nullable,
                server_default=server_default,
                sqlite_storage_class="TEXT",
                storage_type_name="DateTime",
            ),
        )


class CurrentTimestamp:
    """Server default marker for database-filled UTC timestamps.

    >>> DateTime(server_default=CurrentTimestamp(), default=MISSING)
    """


class Attr[WriteOwnerT, LoadedOwnerT, OwnerT, WriteT, ReadValueT]:
    """Typed model column descriptor used for fields and query construction.

    The descriptor exposes pending-state write values on application-created
    models, fetched-state read values on runtime materialized models, and query
    helper methods on the model class.
    """

    def __init__(self, config: _AttrConfig) -> None:
        self.auto_increment: bool = config.auto_increment
        self.default: object = config.default
        self.default_factory: Callable[[], object] | EllipsisType = (
            config.default_factory
        )
        self.is_generated: bool = False
        self.name: str | None = None
        self.owner: type[object] | None = None
        self.nullable: bool | None = config.nullable
        self.primary_key: bool = config.primary_key
        self.server_default: object | None = config.server_default
        self.sqlite_storage_class: SQLiteStorageClass = config.sqlite_storage_class
        self.storage_type_name: str = config.storage_type_name

    def __set_name__(self, owner: type[object], name: str) -> None:
        self.name = name
        self.owner = owner

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
            "dict[str, object]",
            object.__getattribute__(instance, "__dict__"),
        )
        return storage[self._require_name()]

    def __set__(self, instance: object, value: WriteT) -> None:
        if getattr(instance, "_snekql_frozen", False):
            msg = "table models are immutable"
            raise FrozenModelError(msg)
        storage = cast(
            "dict[str, object]",
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
            msg = f"invalid database value for {self._require_name()!r}"
            raise ModelValidationError(
                msg,
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
            msg = f"invalid model value for {self._require_name()!r}"
            raise ModelValidationError(
                msg,
            ) from error

    def validate_model_value(self, value: object) -> object:
        """Validate and normalize a pending model value."""

        try:
            return self._coerce_logical_value(value, fetched=False)
        except SnekqlError:
            raise
        except Exception as error:
            msg = f"invalid model value for {self._require_name()!r}"
            raise ModelValidationError(
                msg,
            ) from error

    def _require_name(self) -> str:
        if self.name is None:
            msg = "column descriptor is not bound"
            raise ModelDeclarationError(msg)
        return self.name

    def _coerce_logical_value(self, value: object, *, fetched: bool) -> object:
        if value is MISSING:
            return self._coerce_missing_value(fetched=fetched)
        if value is None:
            return self._coerce_null_value()
        coercers: dict[str, Callable[[object], object]] = {
            "Blob": self._coerce_blob_value,
            "Boolean": self._coerce_boolean_value,
            "DateTime": self._coerce_datetime_value,
            "Integer": self._coerce_integer_value,
            "Json": self._coerce_json_value,
            "Real": self._coerce_real_value,
            "Text": self._coerce_text_value,
        }
        try:
            coercer = coercers[self.storage_type_name]
        except KeyError as error:
            msg = f"unknown storage type {self.storage_type_name!r}"
            raise ModelDeclarationError(msg) from error
        return coercer(value)

    def _coerce_missing_value(self, *, fetched: bool) -> Missing:
        if self.is_generated and not fetched:
            return MISSING
        msg = f"missing generated value for {self._require_name()!r}"
        raise ModelValidationError(msg)

    def _coerce_null_value(self) -> None:
        if self.nullable is False:
            msg = f"{self._require_name()!r} cannot be null"
            raise ModelValidationError(msg)

    def _coerce_blob_value(self, value: object) -> bytes:
        if not isinstance(value, bytes):
            msg = f"{self._require_name()!r} must be bytes"
            raise ModelValidationError(msg)
        return value

    def _coerce_boolean_value(self, value: object) -> bool:
        if type(value) is not bool:
            msg = f"{self._require_name()!r} must be a bool"
            raise ModelValidationError(msg)
        return value

    def _coerce_datetime_value(self, value: object) -> datetime:
        if not isinstance(value, datetime):
            msg = f"{self._require_name()!r} must be a datetime"
            raise ModelValidationError(msg)
        return self._normalize_datetime(value)

    def _coerce_integer_value(self, value: object) -> int:
        if type(value) is not int:
            msg = f"{self._require_name()!r} must be an int"
            raise ModelValidationError(msg)
        return value

    def _coerce_json_value(self, value: object) -> object:
        try:
            _ = dumps(value, separators=(",", ":"))
        except (TypeError, ValueError) as error:
            msg = f"{self._require_name()!r} is not JSON serializable"
            raise ModelValidationError(msg) from error
        return value

    def _coerce_real_value(self, value: object) -> float:
        if isinstance(value, bool) or not isinstance(value, int | float):
            msg = f"{self._require_name()!r} must be a number"
            raise ModelValidationError(msg)
        return float(value)

    def _coerce_text_value(self, value: object) -> str:
        if not isinstance(value, str):
            msg = f"{self._require_name()!r} must be a str"
            raise ModelValidationError(msg)
        return value

    def _decode_sqlite(self, value: object) -> object:
        if value is None:
            return None
        if self.storage_type_name == "Json":
            if not isinstance(value, str):
                msg = f"{self._require_name()!r} database value must be JSON text"
                raise ModelValidationError(
                    msg,
                )
            try:
                return loads(value)
            except JSONDecodeError as error:
                msg = f"{self._require_name()!r} database value is not valid JSON"
                raise ModelValidationError(
                    msg,
                ) from error
        if self.storage_type_name == "Boolean":
            if value == 0:
                return False
            if value == 1:
                return True
            msg = f"{self._require_name()!r} database value must be 0 or 1"
            raise ModelValidationError(
                msg,
            )
        if self.storage_type_name == "DateTime":
            if not isinstance(value, str):
                msg = f"{self._require_name()!r} database value must be timestamp text"
                raise ModelValidationError(
                    msg,
                )
            return self._decode_datetime_text(value)
        return value

    def _decode_datetime_text(self, value: str) -> datetime:
        if not value.endswith("Z"):
            msg = f"{self._require_name()!r} timestamp must end with Z"
            raise ModelValidationError(
                msg,
            )
        try:
            parsed = datetime.fromisoformat(f"{value[:-1]}+00:00")
        except ValueError as error:
            msg = f"{self._require_name()!r} timestamp is not valid ISO text"
            raise ModelValidationError(
                msg,
            ) from error
        return self._normalize_datetime(parsed)

    def _encode_sqlite(self, value: object) -> object:
        if value is None:
            return None
        if self.storage_type_name == "Json":
            try:
                return dumps(value, separators=(",", ":"))
            except (TypeError, ValueError) as error:
                msg = f"{self._require_name()!r} is not JSON serializable"
                raise ModelValidationError(
                    msg,
                ) from error
        if self.storage_type_name == "Boolean":
            return 1 if value else 0
        if self.storage_type_name == "DateTime":
            timestamp = cast("datetime", value)
            return (
                timestamp.strftime("%Y-%m-%dT%H:%M:%S.")
                + f"{timestamp.microsecond // 1000:03d}Z"
            )
        return value

    def _normalize_datetime(self, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            msg = f"{self._require_name()!r} must be timezone-aware"
            raise ModelValidationError(
                msg,
            )
        utc_value = value.astimezone(UTC)
        milliseconds = utc_value.microsecond // 1000
        return utc_value.replace(microsecond=milliseconds * 1000)

    def eq(self, value: ReadValueT) -> Predicate[OwnerT]:
        if value is None:
            msg = "eq(None) is invalid; use is_null()"
            raise QueryConstructionError(msg)
        return Predicate(kind="eq", column=self, value=value)

    def ne(self, value: ReadValueT) -> Predicate[OwnerT]:
        if value is None:
            msg = "ne(None) is invalid; use is_not_null()"
            raise QueryConstructionError(msg)
        return Predicate(kind="ne", column=self, value=value)

    def is_null(self) -> Predicate[OwnerT]:
        return Predicate(kind="is_null", column=self)

    def is_not_null(self) -> Predicate[OwnerT]:
        return Predicate(kind="is_not_null", column=self)

    def in_(self, *values: ReadValueT) -> Predicate[OwnerT]:
        if not values:
            msg = "in_() requires at least one value"
            raise QueryConstructionError(msg)
        if any(candidate is None for candidate in values):
            msg = "in_() values cannot be None"
            raise QueryConstructionError(msg)
        return Predicate(kind="in", column=self, values=values)

    def not_in(self, *values: ReadValueT) -> Predicate[OwnerT]:
        if not values:
            msg = "not_in() requires at least one value"
            raise QueryConstructionError(msg)
        if any(candidate is None for candidate in values):
            msg = "not_in() values cannot be None"
            raise QueryConstructionError(msg)
        return Predicate(kind="not_in", column=self, values=values)

    def like(self, pattern: str) -> Predicate[OwnerT]:
        if self.storage_type_name != "Text":
            msg = "like() is only valid for text columns"
            raise QueryConstructionError(msg)
        return Predicate(kind="like", column=self, value=pattern)

    def not_like(self, pattern: str) -> Predicate[OwnerT]:
        if self.storage_type_name != "Text":
            msg = "not_like() is only valid for text columns"
            raise QueryConstructionError(msg)
        return Predicate(kind="not_like", column=self, value=pattern)

    def asc(self) -> OrderBy[OwnerT]:
        return OrderBy(column=self, direction="ASC")

    def desc(self) -> OrderBy[OwnerT]:
        return OrderBy(column=self, direction="DESC")

    def to(self, value: ReadValueT) -> Assignment[OwnerT]:
        return Assignment(column=self, value=value)

"""SQLite storage declarations and value codecs for table models."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from json import JSONDecodeError, loads
from math import isfinite
from types import EllipsisType
from typing import (
    Any,
    Literal,
    Self,
    TypeVar,
    cast,
    get_args,
    get_origin,
    get_type_hints,
    overload,
)

from pydantic import Json as _PydanticJson
from pydantic import TypeAdapter, ValidationError
from pydantic_core import PydanticSerializationError

from snekql.errors import (
    FrozenModelError,
    ModelDeclarationError,
    ModelValidationError,
    QueryConstructionError,
    SnekqlError,
)
from snekql.expressions import (
    Aggregate,
    Assignment,
    Comparable,
    JoinOn,
    OrderBy,
    Predicate,
)

type SQLiteStorageClass = Literal["INTEGER", "REAL", "TEXT", "BLOB"]
type StorageBackend = Literal["mariadb", "sqlite"]

# Foreign-key referential actions. ``SET DEFAULT`` is intentionally omitted: SQLite
# honors it but InnoDB silently ignores it, so a portable model cannot rely on it.
type ReferentialAction = Literal["CASCADE", "RESTRICT", "SET NULL", "NO ACTION"]

# ``pydantic.Json`` is typed as a special form but is a real class at runtime;
# bind the runtime class for ``isinstance`` marker detection.
_JSON_MARKER_TYPE: type = cast("type", _PydanticJson)

# Inclusive bounds of a signed 64-bit integer. SQLite INTEGER and MariaDB BIGINT
# both top out here; values outside the range cannot be persisted, so the codec
# rejects them with a domain error instead of letting the driver overflow.
_INT64_MIN = -(2**63)
_INT64_MAX = 2**63 - 1


@dataclass(frozen=True, kw_only=True)
class _BackendCodec:
    """The small set of wire-format decisions that vary between backends.

    Everything else about value encoding -- Boolean as ``0``/``1``, Json through
    the column's pydantic adapter, scalar pass-through -- is backend-independent
    and lives once on :class:`Attr`. Only these points differ, so they are the
    whole per-backend surface. This stays private: promote it to a public seam
    only when a third backend needs materially different wire semantics.
    """

    datetime_encode_format: str
    datetime_encode_suffix: str
    decode_datetime: Callable[[object, str], datetime]
    json_accepts_bytes: bool
    # Length ceilings for the variable-width text/binary storage families, or
    # ``None`` when the backend imposes no practical limit. Encoding rejects
    # oversized values with a domain error rather than letting the driver
    # silently truncate (MariaDB non-strict mode) or raise a raw error.
    max_text_chars: int | None
    max_blob_bytes: int | None


@dataclass(frozen=True, kw_only=True)
class AttrConfig:
    """Constructor bundle for column descriptors.

    Keeping descriptor configuration in one value avoids long internal
    constructors while preserving explicit storage metadata at each call site.
    """

    sqlite_storage_class: SQLiteStorageClass
    storage_type_name: str
    auto_increment: bool = False
    default: object = ...
    default_factory: Callable[[], object] | EllipsisType = ...
    foreign_key_target: Attr[Any, Any, Any, Any, Any] | None = None
    index: bool = False
    nullable: bool | None = None
    on_delete: ReferentialAction | None = None
    on_update: ReferentialAction | None = None
    primary_key: bool = False
    server_default: object | None = None
    unique: bool = False


WriteOwnerT = TypeVar("WriteOwnerT")
LoadedOwnerT = TypeVar("LoadedOwnerT")
OwnerT = TypeVar("OwnerT")
WriteT = TypeVar("WriteT")
ReadValueT = TypeVar("ReadValueT")


class PendingGeneration:
    """Sentinel type for generated values that are not available yet.

    >>> PENDING_GENERATION is PendingGeneration()
    True
    >>> repr(PENDING_GENERATION)
    'PENDING_GENERATION'
    """

    _instance: Self | None = None

    def __new__(cls) -> Self:
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __repr__(self) -> str:
        return "PENDING_GENERATION"


PENDING_GENERATION = PendingGeneration()


# Startup schema verification behavior: strict raises on drift, warn logs and
# continues. TypeAliasType currently exposes a read-only generic __doc__.
type SchemaPolicy = Literal["strict", "warn"]


def build_attr(config: AttrConfig) -> Any:
    """Build a public column descriptor from normalized storage metadata.

    Storage classes differ mostly by SQLite class and logical type name. Keeping
    descriptor wiring here gives the storage declaration module one place to
    change how declaration metadata becomes query/model behavior.
    """

    return FKAttr[Any, Any, Any, Any, Any, Any](config)


class Integer:
    """SQLite INTEGER storage primitive for table model fields.

    The Python value type is the field annotation, not the constructor: an
    ``Integer()`` column may hold an ``int`` or any pydantic type that encodes to
    an integer (a ``bool`` as ``0``/``1``, a custom epoch ``datetime``).

    >>> class User[S = Pending](Model[S, "User[Fetched]"]):
    ...     id: User.GenCol[int] = Integer(primary_key=True, default=PENDING_GENERATION)
    """

    @overload
    def __new__[T](
        cls,
        *,
        primary_key: bool = False,
        auto_increment: bool = False,
        nullable: bool | None = None,
        unique: bool = False,
        index: bool = False,
        default: PendingGeneration,
    ) -> Attr[Any, Any, Any, T | PendingGeneration, T]: ...

    @overload
    def __new__[T](
        cls,
        *,
        primary_key: bool = False,
        auto_increment: bool = False,
        nullable: bool | None = None,
        unique: bool = False,
        index: bool = False,
        default: type[CurrentTimestamp],
    ) -> Attr[Any, Any, Any, T | PendingGeneration, T]: ...

    @overload
    def __new__[T](
        cls,
        *,
        primary_key: bool = False,
        auto_increment: bool = False,
        nullable: bool | None = None,
        unique: bool = False,
        index: bool = False,
        default: None,
    ) -> Attr[Any, Any, Any, T | None, T | None, object]: ...

    @overload
    def __new__[T](
        cls,
        *,
        primary_key: bool = False,
        auto_increment: bool = False,
        nullable: bool | None = None,
        unique: bool = False,
        index: bool = False,
        default: T,
    ) -> Attr[Any, Any, Any, T, T, object]: ...

    @overload
    def __new__[T](
        cls,
        *,
        primary_key: bool = False,
        auto_increment: bool = False,
        nullable: bool | None = None,
        unique: bool = False,
        index: bool = False,
        default_factory: Callable[[], T],
    ) -> Attr[Any, Any, Any, T, T, object]: ...

    @overload
    def __new__(
        cls,
        *,
        primary_key: bool = False,
        auto_increment: bool = False,
        nullable: bool | None = None,
        unique: bool = False,
        index: bool = False,
        default: object = ...,
        default_factory: Callable[[], object] | EllipsisType = ...,
    ) -> Any: ...

    def __new__(  # noqa: PLR0913
        cls,
        *,
        primary_key: bool = False,
        auto_increment: bool = False,
        nullable: bool | None = None,
        unique: bool = False,
        index: bool = False,
        default: object = ...,
        default_factory: Callable[[], object] | EllipsisType = ...,
    ) -> Any:
        return build_attr(
            AttrConfig(
                auto_increment=auto_increment,
                default=default,
                default_factory=default_factory,
                nullable=nullable,
                primary_key=primary_key,
                index=index,
                unique=unique,
                sqlite_storage_class="INTEGER",
                storage_type_name="Integer",
            ),
        )


class Real:
    """SQLite REAL storage primitive for float-like model values.

    >>> class Reading[S = Pending](Model[S, "Reading[Fetched]"]):
    ...     value: Reading.Col[float] = Real(nullable=False)
    """

    @overload
    def __new__[T](
        cls,
        *,
        primary_key: bool = False,
        nullable: bool | None = None,
        unique: bool = False,
        index: bool = False,
        default: PendingGeneration,
    ) -> Attr[Any, Any, Any, T | PendingGeneration, T]: ...

    @overload
    def __new__[T](
        cls,
        *,
        primary_key: bool = False,
        nullable: bool | None = None,
        unique: bool = False,
        index: bool = False,
        default: type[CurrentTimestamp],
    ) -> Attr[Any, Any, Any, T | PendingGeneration, T]: ...

    @overload
    def __new__[T](
        cls,
        *,
        primary_key: bool = False,
        nullable: bool | None = None,
        unique: bool = False,
        index: bool = False,
        default: None,
    ) -> Attr[Any, Any, Any, T | None, T | None, object]: ...

    @overload
    def __new__[T](
        cls,
        *,
        primary_key: bool = False,
        nullable: bool | None = None,
        unique: bool = False,
        index: bool = False,
        default: T,
    ) -> Attr[Any, Any, Any, T, T, object]: ...

    @overload
    def __new__[T](
        cls,
        *,
        primary_key: bool = False,
        nullable: bool | None = None,
        unique: bool = False,
        index: bool = False,
        default_factory: Callable[[], T],
    ) -> Attr[Any, Any, Any, T, T, object]: ...

    @overload
    def __new__(
        cls,
        *,
        primary_key: bool = False,
        nullable: bool | None = None,
        unique: bool = False,
        index: bool = False,
        default: object = ...,
        default_factory: Callable[[], object] | EllipsisType = ...,
    ) -> Any: ...

    def __new__(  # noqa: PLR0913
        cls,
        *,
        primary_key: bool = False,
        nullable: bool | None = None,
        unique: bool = False,
        index: bool = False,
        default: object = ...,
        default_factory: Callable[[], object] | EllipsisType = ...,
    ) -> Any:
        return build_attr(
            AttrConfig(
                default=default,
                default_factory=default_factory,
                nullable=nullable,
                primary_key=primary_key,
                index=index,
                unique=unique,
                sqlite_storage_class="REAL",
                storage_type_name="Real",
            ),
        )


class Text:
    """SQLite TEXT storage primitive for string-encoded model values.

    The Python value type is the annotation: ``Text()`` may hold a ``str``, a
    ``datetime`` (ISO text), a ``uuid.UUID`` (its string form), or a
    ``pydantic.Json[T]`` payload (serialized JSON text).

    >>> class User[S = Pending](Model[S, "User[Fetched]"]):
    ...     email: User.Col[str] = Text(nullable=False)
    """

    @overload
    def __new__[T](
        cls,
        *,
        primary_key: bool = False,
        nullable: bool | None = None,
        unique: bool = False,
        index: bool = False,
        default: PendingGeneration,
    ) -> Attr[Any, Any, Any, T | PendingGeneration, T]: ...

    @overload
    def __new__[T](
        cls,
        *,
        primary_key: bool = False,
        nullable: bool | None = None,
        unique: bool = False,
        index: bool = False,
        default: type[CurrentTimestamp],
    ) -> Attr[Any, Any, Any, T | PendingGeneration, T]: ...

    @overload
    def __new__[T](
        cls,
        *,
        primary_key: bool = False,
        nullable: bool | None = None,
        unique: bool = False,
        index: bool = False,
        default: None,
    ) -> Attr[Any, Any, Any, T | None, T | None, object]: ...

    @overload
    def __new__[T](
        cls,
        *,
        primary_key: bool = False,
        nullable: bool | None = None,
        unique: bool = False,
        index: bool = False,
        default: T,
    ) -> Attr[Any, Any, Any, T, T, object]: ...

    @overload
    def __new__[T](
        cls,
        *,
        primary_key: bool = False,
        nullable: bool | None = None,
        unique: bool = False,
        index: bool = False,
        default_factory: Callable[[], T],
    ) -> Attr[Any, Any, Any, T, T, object]: ...

    @overload
    def __new__(
        cls,
        *,
        primary_key: bool = False,
        nullable: bool | None = None,
        unique: bool = False,
        index: bool = False,
        default: object = ...,
        default_factory: Callable[[], object] | EllipsisType = ...,
    ) -> Any: ...

    def __new__(  # noqa: PLR0913
        cls,
        *,
        primary_key: bool = False,
        nullable: bool | None = None,
        unique: bool = False,
        index: bool = False,
        default: object = ...,
        default_factory: Callable[[], object] | EllipsisType = ...,
    ) -> Any:
        return build_attr(
            AttrConfig(
                default=default,
                default_factory=default_factory,
                nullable=nullable,
                primary_key=primary_key,
                index=index,
                unique=unique,
                sqlite_storage_class="TEXT",
                storage_type_name="Text",
            ),
        )


class Blob:
    """SQLite BLOB storage primitive for bytes-encoded model values.

    >>> class File[S = Pending](Model[S, "File[Fetched]"]):
    ...     content: File.Col[bytes] = Blob(nullable=False)
    """

    @overload
    def __new__[T](
        cls,
        *,
        primary_key: bool = False,
        nullable: bool | None = None,
        unique: bool = False,
        index: bool = False,
        default: PendingGeneration,
    ) -> Attr[Any, Any, Any, T | PendingGeneration, T]: ...

    @overload
    def __new__[T](
        cls,
        *,
        primary_key: bool = False,
        nullable: bool | None = None,
        unique: bool = False,
        index: bool = False,
        default: type[CurrentTimestamp],
    ) -> Attr[Any, Any, Any, T | PendingGeneration, T]: ...

    @overload
    def __new__[T](
        cls,
        *,
        primary_key: bool = False,
        nullable: bool | None = None,
        unique: bool = False,
        index: bool = False,
        default: None,
    ) -> Attr[Any, Any, Any, T | None, T | None, object]: ...

    @overload
    def __new__[T](
        cls,
        *,
        primary_key: bool = False,
        nullable: bool | None = None,
        unique: bool = False,
        index: bool = False,
        default: T,
    ) -> Attr[Any, Any, Any, T, T, object]: ...

    @overload
    def __new__[T](
        cls,
        *,
        primary_key: bool = False,
        nullable: bool | None = None,
        unique: bool = False,
        index: bool = False,
        default_factory: Callable[[], T],
    ) -> Attr[Any, Any, Any, T, T, object]: ...

    @overload
    def __new__(
        cls,
        *,
        primary_key: bool = False,
        nullable: bool | None = None,
        unique: bool = False,
        index: bool = False,
        default: object = ...,
        default_factory: Callable[[], object] | EllipsisType = ...,
    ) -> Any: ...

    def __new__(  # noqa: PLR0913
        cls,
        *,
        primary_key: bool = False,
        nullable: bool | None = None,
        unique: bool = False,
        index: bool = False,
        default: object = ...,
        default_factory: Callable[[], object] | EllipsisType = ...,
    ) -> Any:
        return build_attr(
            AttrConfig(
                default=default,
                default_factory=default_factory,
                nullable=nullable,
                primary_key=primary_key,
                index=index,
                unique=unique,
                sqlite_storage_class="BLOB",
                storage_type_name="Blob",
            ),
        )


class CurrentTimestamp:
    """Server default marker for database-filled UTC timestamps.

    Used as a bare class object, not an instance: pass ``CurrentTimestamp`` itself
    as a column's ``default``. The database computes the value, so the column must
    be a Generated Column and is omittable at construction until filled.
    Pairs with any column whose logical type decodes the backend's timestamp text;
    on SQLite that is a ``GenCol[datetime]`` stored as ``Text()``.

    >>> Text(default=CurrentTimestamp)

    Also accepted by ``column.to(CurrentTimestamp)`` in an update assignment to
    refresh a column to the server clock on update (rendered inline, no bound
    parameter), the on-update counterpart to filling it on insert.
    """


class ForeignKey:
    """Foreign-key column declaration that names its target column.

    The single way to declare any foreign key: the target column is passed as a
    value (`ForeignKey(User.email)`), and the precise `FKAttr[..., T, T, Target]`
    return cross-checks it against the field's `FKCol[Target, T]` annotation at
    declaration time. Storage is *derived* from the target column rather than
    restated, so an FK to a `TEXT` column is itself `TEXT`. PK targets are named
    explicitly like any other (`ForeignKey(User.id)`).

    Marking two or more foreign keys `primary_key=True` declares a composite
    (multi-column) primary key, the natural shape for a pure join table whose
    identity *is* the referenced column pair.

    >>> class Order[S = Pending](Model[S, "Order[Fetched]"]):
    ...     owner_email: Order.FKCol[User, str] = ForeignKey(
    ...         User.email, nullable=False
    ...     )
    """

    @overload
    def __new__[Target, T](
        cls,
        references: Attr[Any, Any, Target, Any, T],
        *,
        primary_key: bool = False,
        nullable: bool | None = None,
        unique: bool = False,
        index: bool = False,
        on_delete: ReferentialAction | None = None,
        on_update: ReferentialAction | None = None,
        default: T,
    ) -> FKAttr[Any, Any, Any, T, T, Target, object]: ...

    @overload
    def __new__[Target, T](
        cls,
        references: Attr[Any, Any, Target, Any, T],
        *,
        primary_key: bool = False,
        nullable: bool | None = None,
        unique: bool = False,
        index: bool = False,
        on_delete: ReferentialAction | None = None,
        on_update: ReferentialAction | None = None,
        default: None,
    ) -> FKAttr[Any, Any, Any, T | None, T | None, Target, object]: ...

    @overload
    def __new__[Target, T](
        cls,
        references: Attr[Any, Any, Target, Any, T],
        *,
        primary_key: bool = False,
        nullable: bool | None = None,
        unique: bool = False,
        index: bool = False,
        on_delete: ReferentialAction | None = None,
        on_update: ReferentialAction | None = None,
    ) -> FKAttr[Any, Any, Any, T, T, Target]: ...

    def __new__[Target, T](  # noqa: PLR0913
        cls,
        references: Attr[Any, Any, Target, Any, T],
        *,
        primary_key: bool = False,
        nullable: bool | None = None,
        unique: bool = False,
        index: bool = False,
        on_delete: ReferentialAction | None = None,
        on_update: ReferentialAction | None = None,
        default: object = ...,
    ) -> Any:
        target_column = cast("Attr[Any, Any, Any, Any, Any]", references)
        return build_attr(
            AttrConfig(
                default=default,
                foreign_key_target=target_column,
                nullable=nullable,
                on_delete=on_delete,
                on_update=on_update,
                primary_key=primary_key,
                sqlite_storage_class=target_column.sqlite_storage_class,
                storage_type_name=target_column.storage_type_name,
                index=index,
                unique=unique,
            ),
        )


def _resolve_model_hints(owner: type[object]) -> dict[str, Any]:
    """Resolve and cache a model's annotations for per-column validation.

    The logical type a column validates against lives only in its annotation
    (`Col[T]` / `GenCol[T]` / `FKCol[Target, T]`), which carries no runtime
    value. Resolving it needs the names visible where the model was declared --
    the captured declaring-scope locals plus the model's own name for
    self-referential annotations -- so the resolution mirrors foreign-key
    target resolution. Hints are cached on the owning class so each column does
    not re-resolve the whole annotation set.
    """

    cached = cast("dict[str, Any] | None", vars(owner).get("__snekql_hints__"))
    if cached is not None:
        return cached
    captured_localns = cast(
        "dict[str, Any] | None",
        getattr(owner, "__snekql_localns__", None),
    )
    localns: dict[str, Any] = {**(captured_localns or {}), owner.__name__: owner}
    hints = get_type_hints(owner, localns=localns, include_extras=True)
    cast("Any", owner).__snekql_hints__ = hints
    return hints


def _extract_logical_type(annotation: object, name: str) -> object:
    """Pull the validated value type out of a column annotation.

    `Col[T]` and `GenCol[T]` carry the logical type as their only argument;
    `FKCol[Target, T]` carries it second, after the referenced model.
    """

    alias_name = getattr(get_origin(annotation), "__name__", None)
    arguments = get_args(annotation)
    if alias_name in {"Col", "GenCol"} and arguments:
        return arguments[0]
    if alias_name == "FKCol" and len(arguments) >= 2:  # noqa: PLR2004
        return arguments[1]
    msg = f"cannot determine validated type for column {name!r}"
    raise ModelDeclarationError(msg)


def _carries_json_marker(annotation: object) -> bool:
    """Whether a logical annotation is a ``pydantic.Json[T]`` payload.

    ``pydantic.Json[T]`` desugars to ``Annotated[T, pydantic.Json]``; the marker
    is the ``Json`` class sitting in the annotation metadata. Detecting it is how
    a plain ``Text()`` column opts into JSON serialization without a dedicated
    ``Json`` constructor (SQLite has no native JSON storage class).
    """

    metadata = getattr(annotation, "__metadata__", None)
    if not metadata:
        return False
    # ``pydantic.Json[T]`` puts a ``Json()`` instance in the metadata; a bare
    # ``Json`` annotation would put the class itself.
    return any(
        item is _PydanticJson or isinstance(item, _JSON_MARKER_TYPE)
        for item in metadata
    )


def _strip_json_marker(annotation: object) -> object:
    """Drop the ``pydantic.Json`` marker, exposing the inner payload type.

    The marker only selects the JSON wire codec; validation and serialization run
    against the inner ``T`` (a ``dict``, a pydantic model, ...) through the same
    adapter the MariaDB native ``Json`` column already uses.
    """

    if _carries_json_marker(annotation):
        return cast("Any", annotation).__origin__
    return annotation


class Attr[WriteOwnerT, LoadedOwnerT, OwnerT, WriteT, ReadValueT, SetValueT = WriteT](
    Comparable[OwnerT, ReadValueT],
):
    """Typed model column descriptor used for fields and query construction.

    The descriptor exposes pending-state write values on application-created
    models, fetched-state read values on runtime materialized models, and query
    helper methods on the model class.
    """

    def __init__(self, config: AttrConfig) -> None:
        self.auto_increment: bool = config.auto_increment
        self.default: object = config.default
        self.default_factory: Callable[[], object] | EllipsisType = (
            config.default_factory
        )
        self.foreign_key_target: Attr[Any, Any, Any, Any, Any] | None = (
            config.foreign_key_target
        )
        self.foreign_key: bool = config.foreign_key_target is not None
        self.index: bool = config.index
        self.on_delete: ReferentialAction | None = config.on_delete
        self.on_update: ReferentialAction | None = config.on_update
        self.is_generated: bool = False
        self.name: str | None = None
        self.owner: type[object] | None = None
        self.nullable: bool | None = config.nullable
        self.primary_key: bool = config.primary_key
        self.server_default: object | None = config.server_default
        self.sqlite_storage_class: SQLiteStorageClass = config.sqlite_storage_class
        self.storage_type_name: str = config.storage_type_name
        self.unique: bool = config.unique
        self._logical_adapter_cache: TypeAdapter[Any] | None = None
        self._is_json_cache: bool | None = None

    def __set_name__(self, owner: type[object], name: str) -> None:
        self.name = name
        self.owner = owner

    @overload
    def __get__(
        self, instance: None, owner: type[Any]
    ) -> Attr[
        WriteOwnerT,
        LoadedOwnerT,
        OwnerT,
        WriteT,
        ReadValueT,
        SetValueT,
    ]: ...
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

    def __set__(self, instance: object, value: SetValueT) -> None:
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

    def decode(
        self,
        value: object,
        *,
        backend: StorageBackend,
        validate: bool = True,
    ) -> object:
        """Decode a database value through this column's backend storage codec.

        JSON columns and the MariaDB native ``Boolean`` / ``DateTime`` types keep
        their dedicated wire codecs; every other column delegates the
        wire-to-logical conversion to pydantic. Fetch decoding is **lax** -- the
        driver hands back a primitive (`str`/`int`) that must coerce up to the
        logical type (`str -> datetime`, `1 -> bool`, `str -> UUID`), which strict
        validation rejects. ``validate=False`` is the raw escape hatch.
        """

        codec = _BACKEND_CODECS[backend]
        try:
            if self._is_json_column():
                return self._decode_json(value, codec=codec, validate=validate)
            if self.storage_type_name == "Boolean":
                decoded: object = None if value is None else self._decode_boolean(value)
            elif self.storage_type_name == "DateTime":
                decoded = (
                    None
                    if value is None
                    else codec.decode_datetime(value, self._require_name())
                )
            else:
                if value is None:
                    if validate:
                        self._coerce_null_value()
                    return None
                if not validate:
                    return value
                return self._decode_primitive(value)
            if not validate:
                return decoded
            return self._validate_logical_value(decoded, fetched=True)
        except SnekqlError:
            raise
        except Exception as error:
            msg = f"invalid database value for {self._require_name()!r}"
            raise ModelValidationError(
                msg,
            ) from error

    def encode(self, value: object, *, backend: StorageBackend) -> object:
        """Encode a logical Python value through this column's backend codec.

        Encoding performs only Layer 1 wire conversion (including the UTC and
        millisecond canonicalization for timestamps); logical type validation
        happens when the Pending Model is constructed, not here.
        """

        try:
            if value is PENDING_GENERATION:
                return PENDING_GENERATION
            return self._encode_value(value, codec=_BACKEND_CODECS[backend])
        except SnekqlError:
            raise
        except Exception as error:
            msg = f"invalid model value for {self._require_name()!r}"
            raise ModelValidationError(
                msg,
            ) from error

    def validate_model_value(self, value: object) -> object:
        """Validate a pending model value against its declared logical type."""

        try:
            return self._validate_logical_value(value, fetched=False)
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

    def _validate_logical_value(self, value: object, *, fetched: bool) -> object:
        if value is PENDING_GENERATION:
            return self._coerce_pending_generation(fetched=fetched)
        if value is None:
            return self._coerce_null_value()
        try:
            return self._logical_adapter().validate_python(value, strict=True)
        except ValidationError as error:
            msg = f"{self._require_name()!r} failed type validation: {error}"
            raise ModelValidationError(msg) from error

    def _logical_adapter(self) -> TypeAdapter[Any]:
        cached = self._logical_adapter_cache
        if cached is not None:
            return cached
        name = self._require_name()
        owner = self.owner
        if owner is None:
            msg = "column descriptor is not bound"
            raise ModelDeclarationError(msg)
        annotation = _resolve_model_hints(owner).get(name)
        # The pydantic ``Json`` marker only selects the JSON wire codec; the
        # adapter validates and serializes the inner payload type, the same way
        # the MariaDB native ``Json`` column (a plain ``Col[T]`` annotation) does.
        validated_type = _strip_json_marker(_extract_logical_type(annotation, name))
        adapter: TypeAdapter[Any] = TypeAdapter(validated_type)
        self._logical_adapter_cache = adapter
        return adapter

    def _is_json_column(self) -> bool:
        """Whether this column uses the JSON wire codec.

        True for the MariaDB native ``Json`` storage type and for any column
        whose annotation carries the ``pydantic.Json`` marker (how a SQLite
        ``Text()`` column opts into JSON without a native JSON storage class).
        """

        cached = self._is_json_cache
        if cached is not None:
            return cached
        if self.storage_type_name == "Json":
            self._is_json_cache = True
            return True
        owner = self.owner
        if owner is None:
            return False
        annotation = _resolve_model_hints(owner).get(self._require_name())
        try:
            logical = _extract_logical_type(annotation, self._require_name())
        except ModelDeclarationError:
            logical = None
        result = _carries_json_marker(logical)
        self._is_json_cache = result
        return result

    def _coerce_pending_generation(self, *, fetched: bool) -> PendingGeneration:
        if self.is_generated and not fetched:
            return PENDING_GENERATION
        msg = f"pending generated value for {self._require_name()!r}"
        raise ModelValidationError(msg)

    def _coerce_null_value(self) -> None:
        if self.nullable is False:
            msg = f"{self._require_name()!r} cannot be null"
            raise ModelValidationError(msg)

    def _decode_json(
        self,
        value: object,
        *,
        codec: _BackendCodec,
        validate: bool,
    ) -> object:
        """Decode a Json column value, symmetric with :meth:`_encode_json`.

        With ``validate`` the wire text is parsed *and* validated by the column's
        logical adapter in one pass (``validate_json``), so rich annotated types
        round-trip. With ``validate`` disabled the escape hatch keeps its meaning
        -- a raw ``json.loads`` value, no type coercion.
        """

        if value is None:
            if validate:
                self._coerce_null_value()
            return None
        text = self._json_text(value, json_accepts_bytes=codec.json_accepts_bytes)
        if not validate:
            try:
                return loads(text)
            except JSONDecodeError as error:
                msg = f"{self._require_name()!r} database value is not valid JSON"
                raise ModelValidationError(msg) from error
        try:
            return self._logical_adapter().validate_json(text)
        except ValidationError as error:
            msg = f"{self._require_name()!r} failed type validation: {error}"
            raise ModelValidationError(msg) from error

    def _json_text(self, value: object, *, json_accepts_bytes: bool) -> str:
        """Extract raw JSON text from a backend value, before parsing.

        SQLite returns JSON columns as ``str``; the MariaDB driver may hand them
        back as ``bytes``. Backends that tolerate ``bytes`` decode it to text.
        """

        if json_accepts_bytes and isinstance(value, bytes | bytearray):
            return value.decode()
        if isinstance(value, str):
            return value
        msg = f"{self._require_name()!r} database value must be JSON text"
        raise ModelValidationError(msg)

    def _decode_primitive(self, value: object) -> object:
        """Lax-decode a primitive-storage value into its logical type via pydantic.

        The driver returns a storage primitive (`str`/`int`/`float`/`bytes`); lax
        validation coerces it up to the annotated type (`str -> datetime`,
        `str -> UUID`, `1 -> bool`). BLOB values may arrive as ``memoryview`` /
        ``bytearray`` and are normalized to ``bytes`` first.
        """

        if self.sqlite_storage_class == "BLOB" and isinstance(
            value, memoryview | bytearray
        ):
            value = bytes(cast("Any", value))
        try:
            return self._logical_adapter().validate_python(value)
        except ValidationError as error:
            msg = f"{self._require_name()!r} failed type validation: {error}"
            raise ModelValidationError(msg) from error

    def _decode_boolean(self, value: object) -> bool:
        if value == 0:
            return False
        if value == 1:
            return True
        msg = f"{self._require_name()!r} database value must be 0 or 1"
        raise ModelValidationError(msg)

    def _encode_value(self, value: object, *, codec: _BackendCodec) -> object:
        """Wire-encode a logical value (Layer 1) for a backend.

        Json and Boolean encoding are backend-independent; only the ``DateTime``
        text format and trailing suffix vary, supplied by ``codec``.
        """

        if value is None:
            return None
        if self._is_json_column():
            return self._encode_json(value)
        if self.storage_type_name == "Boolean":
            return 1 if value else 0
        if self.storage_type_name == "DateTime":
            timestamp = cast("datetime", value).astimezone(UTC)
            return (
                timestamp.strftime(codec.datetime_encode_format)
                + f"{timestamp.microsecond // 1000:03d}"
                + codec.datetime_encode_suffix
            )
        return self._encode_primitive(value, codec=codec)

    def _encode_primitive(self, value: object, *, codec: _BackendCodec) -> object:
        """Wire-encode a primitive-storage value through pydantic serialization.

        ``mode="json"`` turns datetimes/UUIDs into bare strings and passes
        ints/floats/bools through; BLOB storage uses ``mode="python"`` because
        json-mode would base64- or utf-8-mangle raw bytes.
        """

        adapter = self._logical_adapter()
        if self.sqlite_storage_class == "BLOB":
            encoded = adapter.dump_python(value, mode="python")
            if (
                codec.max_blob_bytes is not None
                and isinstance(encoded, bytes | bytearray)
                and len(encoded) > codec.max_blob_bytes
            ):
                msg = (
                    f"{self._require_name()!r} binary value exceeds the "
                    f"{codec.max_blob_bytes}-byte limit for this backend"
                )
                raise ModelValidationError(msg)
            return encoded
        # pydantic serializes a datetime's UTC offset only to whole-minute
        # resolution; a sub-minute offset (historical LMT zones, e.g. +03:06:52)
        # would be truncated and silently shift the stored instant. Refuse it
        # rather than corrupt it -- whole-minute offsets and naive values pass.
        if isinstance(value, datetime):
            offset = value.utcoffset()
            if offset is not None and offset % timedelta(minutes=1):
                msg = (
                    f"{self._require_name()!r} datetime has a sub-minute UTC "
                    f"offset ({offset}) that ISO-text serialization cannot store "
                    f"without shifting the instant"
                )
                raise ModelValidationError(msg)
        encoded = adapter.dump_python(value, mode="json")
        # Reject values no backend can store losslessly before they reach the
        # driver: non-finite floats (``nan`` silently becomes ``NULL`` in SQLite
        # and MariaDB DOUBLE refuses them outright) and integers outside the
        # signed 64-bit range (the SQLite driver raises a raw ``OverflowError``).
        if isinstance(encoded, float) and not isfinite(encoded):
            msg = f"{self._require_name()!r} non-finite float values cannot be stored"
            raise ModelValidationError(msg)
        if (
            self.storage_type_name == "Integer"
            and type(encoded) is int
            and not (_INT64_MIN <= encoded <= _INT64_MAX)
        ):
            msg = f"{self._require_name()!r} integer value exceeds the 64-bit range"
            raise ModelValidationError(msg)
        # TEXT-family columns (Text) may overflow a backend's variable-width
        # ceiling; reject before truncation. Uuid/DateTime also encode to text
        # but are fixed-width, so only the Text family is checked.
        if (
            self.storage_type_name == "Text"
            and codec.max_text_chars is not None
            and isinstance(encoded, str)
            and len(encoded) > codec.max_text_chars
        ):
            msg = (
                f"{self._require_name()!r} text value exceeds the "
                f"{codec.max_text_chars}-character limit for this backend"
            )
            raise ModelValidationError(msg)
        return encoded

    def _encode_json(self, value: object) -> str:
        """Serialize a Json column value through its logical pydantic adapter.

        Using the same ``TypeAdapter(T)`` that drives validation makes the codec
        symmetric: any annotation pydantic can validate it can also serialize
        (``datetime``, pydantic models, ``list[Model]``, ...), and native
        ``dict``/``list``/primitive payloads still emit the compact, byte-stable
        text the stdlib ``json`` writer produced before.
        """

        try:
            return self._logical_adapter().dump_json(value).decode()
        except PydanticSerializationError as error:
            msg = f"{self._require_name()!r} is not JSON serializable"
            raise ModelValidationError(msg) from error

    def like(self, pattern: str) -> Predicate[OwnerT]:
        if not self._is_str_logical():
            msg = "like() is only valid for text columns"
            raise QueryConstructionError(msg)
        return Predicate(kind="like", column=self, value=pattern)

    def not_like(self, pattern: str) -> Predicate[OwnerT]:
        if not self._is_str_logical():
            msg = "not_like() is only valid for text columns"
            raise QueryConstructionError(msg)
        return Predicate(kind="not_like", column=self, value=pattern)

    def _is_str_logical(self) -> bool:
        """Whether the column's logical type is ``str`` (gates ``like``).

        Keyed on the logical type rather than TEXT storage, so a
        ``Col[uuid.UUID] = Text()`` or ``Col[datetime] = Text()`` column does not
        expose string pattern matching.
        """

        owner = self.owner
        if owner is None:
            return False
        annotation = _resolve_model_hints(owner).get(self._require_name())
        try:
            logical = _strip_json_marker(
                _extract_logical_type(annotation, self._require_name())
            )
        except ModelDeclarationError:
            return False
        metadata = getattr(logical, "__metadata__", None)
        if metadata is not None:
            logical = cast("Any", logical).__origin__
        non_none = [arg for arg in get_args(logical) if arg is not type(None)]
        if len(non_none) == 1:
            logical = non_none[0]
        return isinstance(logical, type) and issubclass(logical, str)

    def count(self) -> Aggregate[OwnerT, int]:
        """Aggregate this column as ``COUNT(col)`` (counts non-NULL values)."""

        return Aggregate(func="COUNT", column=self, owner=self.owner)

    def sum(self) -> Aggregate[OwnerT, ReadValueT | None]:
        """Aggregate this column as ``SUM(col)`` (``None`` over an empty set)."""

        return Aggregate(func="SUM", column=self, owner=self.owner)

    def avg(self) -> Aggregate[OwnerT, float | None]:
        """Aggregate this column as ``AVG(col)`` (``float``, ``None`` if empty)."""

        return Aggregate(func="AVG", column=self, owner=self.owner)

    def min(self) -> Aggregate[OwnerT, ReadValueT | None]:
        """Aggregate this column as ``MIN(col)`` (``None`` over an empty set)."""

        return Aggregate(func="MIN", column=self, owner=self.owner)

    def max(self) -> Aggregate[OwnerT, ReadValueT | None]:
        """Aggregate this column as ``MAX(col)`` (``None`` over an empty set)."""

        return Aggregate(func="MAX", column=self, owner=self.owner)

    def asc(self) -> OrderBy[OwnerT]:
        return OrderBy(column=self, direction="ASC")

    def desc(self) -> OrderBy[OwnerT]:
        return OrderBy(column=self, direction="DESC")

    @overload
    def to(self, value: type[CurrentTimestamp]) -> Assignment[OwnerT]: ...
    @overload
    def to(self, value: ReadValueT) -> Assignment[OwnerT]: ...
    def to(self, value: ReadValueT | type[CurrentTimestamp]) -> Assignment[OwnerT]:
        """Assign a Python value, or ``CurrentTimestamp`` for the server clock.

        Passing ``CurrentTimestamp`` renders the backend's current-timestamp SQL
        inline in the ``UPDATE`` (no bound parameter), so a column refreshes to
        the database clock on each update the way ``server_default`` fills it on
        insert. SQLite has no native ``ON UPDATE``; this keeps the refresh
        explicit at the call site and identical across backends.
        """

        return Assignment(column=self, value=value)

    def __column_value_type__(self) -> ReadValueT:
        """Typing-only witness of this column's read value type.

        Lets a column satisfy the ``_ColumnRef`` protocol the comparison surface
        uses to type ``column.eq_col(other_column)`` without importing storage
        into the expressions layer. Never called at runtime.
        """

        raise NotImplementedError


class FKAttr[
    WriteOwnerT,
    LoadedOwnerT,
    OwnerT,
    WriteT,
    ReadValueT,
    TargetOwnerT,
    SetValueT = WriteT,
](
    Attr[WriteOwnerT, LoadedOwnerT, OwnerT, WriteT, ReadValueT, SetValueT],
):
    """Foreign-key column descriptor that declares the model it references.

    `references` only accepts a column of the referenced model whose read type
    matches this column's, so a join condition is provably between related
    tables of compatible key type. Every runtime column is an `FKAttr`; only
    columns annotated as `Model.FKCol[Target, T]` expose `references` to the
    type checker, which is what makes `.references` on a plain column a typing
    error while still resolving at runtime.
    """

    # Class access must keep the FKAttr type (not widen to Attr) so `references`
    # stays visible; the value overloads mirror the base descriptor protocol.
    @overload
    def __get__(self, instance: None, owner: type[Any]) -> Self: ...
    @overload
    def __get__(self, instance: WriteOwnerT, owner: type[Any]) -> WriteT: ...
    @overload
    def __get__(self, instance: LoadedOwnerT, owner: type[Any]) -> ReadValueT: ...
    def __get__(self, instance: object | None, owner: type[Any]) -> object:
        return cast("object", super().__get__(cast("Any", instance), owner))

    def references(
        self,
        other: Attr[Any, Any, TargetOwnerT, Any, ReadValueT],
    ) -> JoinOn[OwnerT, TargetOwnerT]:
        """Build a join condition between this FK column and its target."""

        return JoinOn(left_column=self, right_column=other)


def _decode_sqlite_datetime(value: object, name: str) -> datetime:
    """SQLite stores timestamps as ISO ``...Z`` text; non-text is a bug."""

    if not isinstance(value, str):
        msg = f"{name!r} database value must be timestamp text"
        raise ModelValidationError(msg)
    if not value.endswith("Z"):
        msg = f"{name!r} timestamp must end with Z"
        raise ModelValidationError(msg)
    try:
        return datetime.fromisoformat(f"{value[:-1]}+00:00")
    except ValueError as error:
        msg = f"{name!r} timestamp is not valid ISO text"
        raise ModelValidationError(msg) from error


def _decode_mariadb_datetime(value: object, name: str) -> datetime:
    """The MariaDB driver returns DATETIME columns as ``datetime`` (or text)."""

    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value
    if not isinstance(value, str):
        msg = f"{name!r} database value must be a datetime"
        raise ModelValidationError(msg)
    try:
        parsed = datetime.fromisoformat(value.replace(" ", "T"))
    except ValueError as error:
        msg = f"{name!r} timestamp is not valid MariaDB text"
        raise ModelValidationError(msg) from error
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed


_SQLITE_CODEC = _BackendCodec(
    datetime_encode_format="%Y-%m-%dT%H:%M:%S.",
    datetime_encode_suffix="Z",
    decode_datetime=_decode_sqlite_datetime,
    json_accepts_bytes=False,
    # SQLite TEXT/BLOB share a single ~1 GB limit far above any practical row;
    # treat them as unbounded here.
    max_text_chars=None,
    max_blob_bytes=None,
)
_MARIADB_CODEC = _BackendCodec(
    datetime_encode_format="%Y-%m-%d %H:%M:%S.",
    datetime_encode_suffix="",
    decode_datetime=_decode_mariadb_datetime,
    json_accepts_bytes=True,
    # Text maps to VARCHAR(255) (255 characters) and Blob to BLOB (65535 bytes);
    # JSON is LONGTEXT-backed and effectively unbounded.
    max_text_chars=255,
    max_blob_bytes=65535,
)
_BACKEND_CODECS: dict[StorageBackend, _BackendCodec] = {
    "sqlite": _SQLITE_CODEC,
    "mariadb": _MARIADB_CODEC,
}

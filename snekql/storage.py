"""SQLite storage declarations and value codecs for table models."""

from __future__ import annotations

import sys
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from json import JSONDecodeError, loads
from types import EllipsisType, UnionType
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

from pydantic import AwareDatetime, TypeAdapter, ValidationError
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
    nullable: bool | None = None
    primary_key: bool = False
    server_default: object | None = None
    unique: bool = False


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


def build_attr(config: AttrConfig) -> Any:
    """Build a public column descriptor from normalized storage metadata.

    Storage classes differ mostly by SQLite class and logical type name. Keeping
    descriptor wiring here gives the storage declaration module one place to
    change how declaration metadata becomes query/model behavior.
    """

    return FKAttr[Any, Any, Any, Any, Any, Any](config)


class Integer:
    """SQLite INTEGER column declaration for table model fields.

    >>> class User[S = Pending](Model[S, "User[Fetched]"]):
    ...     id: User.GenCol[int] = Integer(primary_key=True, default=MISSING)
    """

    def __new__(  # noqa: PLR0913
        cls,
        *,
        primary_key: bool = False,
        auto_increment: bool = False,
        nullable: bool | None = None,
        unique: bool = False,
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
                unique=unique,
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
        unique: bool = False,
        default: object = ...,
        default_factory: Callable[[], object] | EllipsisType = ...,
    ) -> Any:
        return build_attr(
            AttrConfig(
                default=default,
                default_factory=default_factory,
                nullable=nullable,
                primary_key=primary_key,
                unique=unique,
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
        unique: bool = False,
        default: object = ...,
        default_factory: Callable[[], object] | EllipsisType = ...,
    ) -> Any:
        return build_attr(
            AttrConfig(
                default=default,
                default_factory=default_factory,
                nullable=nullable,
                primary_key=primary_key,
                unique=unique,
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
        unique: bool = False,
        default: object = ...,
        default_factory: Callable[[], object] | EllipsisType = ...,
    ) -> Any:
        return build_attr(
            AttrConfig(
                default=default,
                default_factory=default_factory,
                nullable=nullable,
                primary_key=primary_key,
                unique=unique,
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
        unique: bool = False,
        default: object = ...,
        default_factory: Callable[[], object] | EllipsisType = ...,
    ) -> Any:
        return build_attr(
            AttrConfig(
                default=default,
                default_factory=default_factory,
                nullable=nullable,
                unique=unique,
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
        unique: bool = False,
        default: object = ...,
        default_factory: Callable[[], object] | EllipsisType = ...,
    ) -> Any:
        return build_attr(
            AttrConfig(
                default=default,
                default_factory=default_factory,
                nullable=nullable,
                unique=unique,
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
        unique: bool = False,
        default: object = ...,
        default_factory: Callable[[], object] | EllipsisType = ...,
    ) -> Any:
        return build_attr(
            AttrConfig(
                default=default,
                default_factory=default_factory,
                nullable=nullable,
                server_default=server_default,
                unique=unique,
                sqlite_storage_class="TEXT",
                storage_type_name="DateTime",
            ),
        )


class CurrentTimestamp:
    """Server default marker for database-filled UTC timestamps.

    >>> DateTime(server_default=CurrentTimestamp(), default=MISSING)
    """


class ForeignKey:
    """Foreign-key column declaration that names its target column.

    The single way to declare any foreign key: the target column is passed as a
    value (`ForeignKey(User.email)`), and the precise `FKAttr[..., T, T, Target]`
    return cross-checks it against the field's `FKCol[Target, T]` annotation at
    declaration time. Storage is *derived* from the target column rather than
    restated, so an FK to a `TEXT` column is itself `TEXT`. PK targets are named
    explicitly like any other (`ForeignKey(User.id)`).

    >>> class Order[S = Pending](Model[S, "Order[Fetched]"]):
    ...     owner_email: Order.FKCol[User, str] = ForeignKey(
    ...         User.email, nullable=False
    ...     )
    """

    def __new__[Target, T](
        cls,
        references: Attr[Any, Any, Target, Any, T],
        *,
        nullable: bool | None = None,
        unique: bool = False,
        default: object = ...,
    ) -> FKAttr[Any, Any, Any, T, T, Target]:
        target_column = cast("Attr[Any, Any, Any, Any, Any]", references)
        return build_attr(
            AttrConfig(
                default=default,
                foreign_key_target=target_column,
                nullable=nullable,
                sqlite_storage_class=target_column.sqlite_storage_class,
                storage_type_name=target_column.storage_type_name,
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


# Storage types whose logical type is a single, unambiguous Python base. Json
# (any JSON-serializable value) and other multi-type storage are deliberately
# absent: they have no single base to compare an annotation against.
_STORAGE_LOGICAL_TYPE: dict[str, type] = {
    "Integer": int,
    "Real": float,
    "Text": str,
    "Blob": bytes,
    "Boolean": bool,
    "DateTime": datetime,
}


def check_column_storage_compatibility(
    owner: type,
    columns: dict[str, Attr[Any, Any, Any, Any, Any]],
    raw_annotations: dict[str, object],
) -> None:
    """Reject columns whose logical annotation cannot match their storage.

    A column has two independent sources of truth: the field annotation drives
    pydantic validation, and the storage descriptor drives encode/decode.
    Nothing else forces them to agree, so a mismatch like ``Col[int] = Boolean()``
    silently corrupts data (``5`` stored as ``1``). This declaration-time guard
    catches the unambiguous scalar mismatches.

    The check is **best-effort**: storage types with no single logical base
    (``Json``), annotations that do not reduce to one base type (unions of two
    non-``None`` members, enums, pydantic models), and annotations that cannot
    be resolved yet (forward references defined later in the module) are all let
    through. Every checked base is a builtin that always resolves, so nothing in
    scope is ever skipped for being unresolvable.
    """

    for name, column in columns.items():
        expected = _STORAGE_LOGICAL_TYPE.get(column.storage_type_name)
        if expected is None:
            continue
        annotation = _resolve_annotation(owner, raw_annotations.get(name))
        if annotation is None:
            continue
        logical = _logical_base_type(annotation, name)
        if logical is None:
            continue
        if logical is not expected:
            msg = (
                f"column {name!r} annotated {logical.__name__!r} is incompatible "
                f"with {column.storage_type_name} storage "
                f"(expected {expected.__name__!r})"
            )
            raise ModelDeclarationError(msg)


def _resolve_annotation(owner: type, raw: object) -> object:
    """Resolve one column annotation in isolation, or ``None`` if it cannot be.

    Annotations are strings under ``from __future__ import annotations``.
    Resolving each column on its own -- rather than batch ``get_type_hints`` --
    keeps one unresolvable forward reference from blocking the check on its
    resolvable siblings.
    """

    if raw is None:
        return None
    if not isinstance(raw, str):
        return raw
    module = sys.modules.get(owner.__module__)
    globalns = getattr(module, "__dict__", {})
    captured = cast("dict[str, Any] | None", getattr(owner, "__snekql_localns__", None))
    localns: dict[str, Any] = {**(captured or {}), owner.__name__: owner}
    try:
        return eval(raw, dict(globalns), localns)  # noqa: S307
    except Exception:  # best-effort: any resolution failure means "skip".
        return None


def _logical_base_type(annotation: object, name: str) -> type | None:
    """Reduce a column annotation to its single Python base type, if it has one.

    Strips the column alias (``Col``/``GenCol``/``FKCol``), then ``Annotated``
    metadata, then an optional ``| None``. Anything that does not bottom out in
    a single concrete class -- a multi-member union, a parametrized generic, a
    type variable -- returns ``None`` and is left for the caller to skip.
    """

    try:
        logical = _extract_logical_type(annotation, name)
    except ModelDeclarationError:
        return None
    logical = _strip_annotated(logical)
    logical = _strip_optional(logical)
    if isinstance(logical, type):
        return logical
    return None


def _strip_annotated(annotation: object) -> object:
    metadata = getattr(annotation, "__metadata__", None)
    if metadata is not None:
        return cast("Any", annotation).__origin__
    return annotation


def _strip_optional(annotation: object) -> object:
    # Only PEP 604 ``X | None`` unions are unwrapped, matching house style; an
    # old-style ``Optional[X]`` simply falls through as "not a single base type"
    # and is left for the caller to skip rather than risk a false positive.
    if get_origin(annotation) is UnionType:
        non_none = [arg for arg in get_args(annotation) if arg is not type(None)]
        if len(non_none) == 1:
            return non_none[0]
    return annotation


class Attr[WriteOwnerT, LoadedOwnerT, OwnerT, WriteT, ReadValueT](
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

    def decode(
        self,
        value: object,
        *,
        backend: StorageBackend,
        validate: bool = True,
    ) -> object:
        """Decode a database value through this column's backend storage codec.

        Layer 1 wire decoding (`0/1` -> bool, JSON text -> value, timestamp text
        -> aware datetime) always runs. Layer 2 logical validation against the
        column's declared type runs unless ``validate`` is disabled.
        """

        try:
            if self.storage_type_name == "Json":
                return self._decode_json(value, backend=backend, validate=validate)
            if backend == "mariadb":
                decoded_value = self._decode_mariadb(value)
            else:
                decoded_value = self._decode_sqlite(value)
            if not validate:
                return decoded_value
            return self._validate_logical_value(decoded_value, fetched=True)
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
            if value is MISSING:
                return MISSING
            if backend == "mariadb":
                return self._encode_mariadb(value)
            return self._encode_sqlite(value)
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
        if value is MISSING:
            return self._coerce_missing_value(fetched=fetched)
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
        if self.storage_type_name == "DateTime":
            validated_type: object = AwareDatetime
        else:
            owner = self.owner
            if owner is None:
                msg = "column descriptor is not bound"
                raise ModelDeclarationError(msg)
            annotation = _resolve_model_hints(owner).get(name)
            validated_type = _extract_logical_type(annotation, name)
        adapter: TypeAdapter[Any] = TypeAdapter(validated_type)
        self._logical_adapter_cache = adapter
        return adapter

    def _coerce_missing_value(self, *, fetched: bool) -> Missing:
        if self.is_generated and not fetched:
            return MISSING
        msg = f"missing generated value for {self._require_name()!r}"
        raise ModelValidationError(msg)

    def _coerce_null_value(self) -> None:
        if self.nullable is False:
            msg = f"{self._require_name()!r} cannot be null"
            raise ModelValidationError(msg)

    def _decode_json(
        self,
        value: object,
        *,
        backend: StorageBackend,
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
        text = self._json_text(value, backend=backend)
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

    def _json_text(self, value: object, *, backend: StorageBackend) -> str:
        """Extract raw JSON text from a backend value, before parsing."""

        if backend == "mariadb":
            if not isinstance(value, str | bytes | bytearray):
                msg = f"{self._require_name()!r} database value must be JSON text"
                raise ModelValidationError(msg)
            if isinstance(value, bytes | bytearray):
                return value.decode()
            return value
        if not isinstance(value, str):
            msg = f"{self._require_name()!r} database value must be JSON text"
            raise ModelValidationError(msg)
        return value

    def _decode_sqlite(self, value: object) -> object:
        if value is None:
            return None
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

    def _decode_mariadb(self, value: object) -> object:
        if value is None:
            return None
        decoders: dict[str, Callable[[object], object]] = {
            "Boolean": self._decode_mariadb_boolean,
            "DateTime": self._decode_mariadb_datetime,
        }
        decoder = decoders.get(self.storage_type_name)
        if decoder is None:
            return value
        return decoder(value)

    def _decode_mariadb_boolean(self, value: object) -> bool:
        if value == 0:
            return False
        if value == 1:
            return True
        msg = f"{self._require_name()!r} database value must be 0 or 1"
        raise ModelValidationError(msg)

    def _decode_mariadb_datetime(self, value: object) -> datetime:
        if isinstance(value, datetime):
            if value.tzinfo is None:
                return value.replace(tzinfo=UTC)
            return value
        if isinstance(value, str):
            return self._decode_mariadb_datetime_text(value)
        msg = f"{self._require_name()!r} database value must be a datetime"
        raise ModelValidationError(msg)

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
        return parsed

    def _decode_mariadb_datetime_text(self, value: str) -> datetime:
        try:
            parsed = datetime.fromisoformat(value.replace(" ", "T"))
        except ValueError as error:
            msg = f"{self._require_name()!r} timestamp is not valid MariaDB text"
            raise ModelValidationError(msg) from error
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=UTC)
        return parsed

    def _encode_sqlite(self, value: object) -> object:
        if value is None:
            return None
        if self.storage_type_name == "Json":
            return self._encode_json(value)
        if self.storage_type_name == "Boolean":
            return 1 if value else 0
        if self.storage_type_name == "DateTime":
            timestamp = cast("datetime", value).astimezone(UTC)
            return (
                timestamp.strftime("%Y-%m-%dT%H:%M:%S.")
                + f"{timestamp.microsecond // 1000:03d}Z"
            )
        return value

    def _encode_mariadb(self, value: object) -> object:
        if value is None:
            return None
        if self.storage_type_name == "Json":
            return self._encode_json(value)
        if self.storage_type_name == "Boolean":
            return 1 if value else 0
        if self.storage_type_name == "DateTime":
            timestamp = cast("datetime", value).astimezone(UTC)
            return (
                timestamp.strftime("%Y-%m-%d %H:%M:%S.")
                + f"{timestamp.microsecond // 1000:03d}"
            )
        return value

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
        if self.storage_type_name != "Text":
            msg = "like() is only valid for text columns"
            raise QueryConstructionError(msg)
        return Predicate(kind="like", column=self, value=pattern)

    def not_like(self, pattern: str) -> Predicate[OwnerT]:
        if self.storage_type_name != "Text":
            msg = "not_like() is only valid for text columns"
            raise QueryConstructionError(msg)
        return Predicate(kind="not_like", column=self, value=pattern)

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

    def to(self, value: ReadValueT) -> Assignment[OwnerT]:
        return Assignment(column=self, value=value)

    def __column_value_type__(self) -> ReadValueT:
        """Typing-only witness of this column's read value type.

        Lets a column satisfy the ``_ColumnRef`` protocol the comparison surface
        uses to type ``column.eq_col(other_column)`` without importing storage
        into the expressions layer. Never called at runtime.
        """

        raise NotImplementedError


class FKAttr[WriteOwnerT, LoadedOwnerT, OwnerT, WriteT, ReadValueT, TargetOwnerT](
    Attr[WriteOwnerT, LoadedOwnerT, OwnerT, WriteT, ReadValueT],
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

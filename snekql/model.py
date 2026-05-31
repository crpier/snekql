"""Table model declaration and materialization behavior."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from types import EllipsisType
from typing import (
    Any,
    ClassVar,
    Generic,
    Self,
    TypeVar,
    cast,
    dataclass_transform,
    get_origin,
)

from snekql.errors import (
    FrozenModelError,
    ModelDeclarationError,
    ModelValidationError,
    SnekqlError,
)
from snekql.storage import (
    MISSING,
    Attr,
    Blob,
    Boolean,
    CurrentTimestamp,
    DateTime,
    Integer,
    Json,
    Missing,
    Real,
    Text,
)

StateT = TypeVar("StateT")
ReadModelT = TypeVar("ReadModelT", bound="Table[Any]")
T = TypeVar("T")


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


class Table(Generic[StateT]):
    """Base type shared by concrete table models in any lifecycle state.

    Query builders use this shallow base to constrain model-like generic
    parameters without requiring runtime construction behavior yet.
    """

    @classmethod
    def __owner_type__(cls) -> type[Self]:
        return cls


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


def require_model_columns(
    model: type[Table[Any]],
) -> dict[str, Attr[Any, Any, Any, Any, Any]]:
    """Return frozen snekql column metadata for a table model."""

    columns = getattr(model, "__snekql_columns__", None)
    if not isinstance(columns, dict):
        raise ModelDeclarationError("schema setup requires snekql table models")
    return cast(dict[str, Attr[Any, Any, Any, Any, Any]], columns)


def require_model_table_name(model: type[Table[Any]]) -> str:
    """Return the resolved SQLite table name for a table model."""

    table_name = getattr(model, "__tablename__", None)
    if not isinstance(table_name, str):
        raise ModelDeclarationError("schema setup requires snekql table models")
    return table_name


def decode_model_row(
    model: type[Table[Any]],
    row: Mapping[str, object],
) -> Table[Any]:
    """Decode SQLite row values into a fetched table model instance."""

    from_row = cast(
        Callable[[Mapping[str, object]], Table[Any]],
        getattr(model, "_snekql_from_row"),
    )
    return from_row(row)


def encode_model_row(row: object) -> tuple[type[Table[Any]], dict[str, object]]:
    """Encode a pending model into table metadata and SQLite row values."""

    if not isinstance(row, Model):
        from snekql.errors import QueryConstructionError

        raise QueryConstructionError("insert requires a snekql model instance")
    model_row = cast(Model[Any, Any], row)
    model_class = cast(type[Table[Any]], model_row.__class__)
    model_to_row = cast(
        Callable[[], dict[str, object]],
        getattr(cast(object, model_row), "_snekql_to_row"),
    )
    return model_class, model_to_row()

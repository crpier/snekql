"""Table model declaration and materialization behavior."""

from __future__ import annotations

import inspect
from types import EllipsisType
from typing import (
    Any,
    ClassVar,
    Literal,
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
from snekql.indexes import NormalizedIndex, require_index_declaration
from snekql.storage import (
    MISSING,
    Attr,
    Blob,
    Boolean,
    CurrentTimestamp,
    DateTime,
    FKAttr,
    ForeignKey,
    Integer,
    Json,
    Missing,
    Real,
    StorageBackend,
    Text,
)

type BackendFamily = StorageBackend

StateT = TypeVar("StateT")
ReadModelT = TypeVar("ReadModelT", bound="Table[Any]")
T = TypeVar("T")


class Pending:
    """Marker state for application-constructed table models.

    >>> state: type[Pending] = Pending
    >>> state.__name__
    'Pending'
    """


class Fetched:
    """Marker state for table models materialized by the Query Runtime.

    A generated column may be `T | Missing` on `Pending` instances but `T` on
    `Fetched` instances.

    >>> state: type[Fetched] = Fetched
    >>> state.__name__
    'Fetched'
    """


class Table[StateT]:
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

# Private foreign-key column alias used to build the public FKCol alias. The
# trailing Target records the referenced model so `references` can require a
# matching target column.
type _FKCol[WriteModelT: Table[Any], FetchedModelT, T, Target] = FKAttr[
    WriteModelT,
    FetchedModelT,
    WriteModelT,
    T,
    T,
    Target,
]

# Public foreign-key column alias for external table model helpers.
type FKCol[WriteModelT: Table[Any], FetchedModelT, T, Target] = _FKCol[
    WriteModelT,
    FetchedModelT,
    T,
    Target,
]


@dataclass_transform(
    field_specifiers=(Integer, Real, Text, Blob, Json, Boolean, DateTime, ForeignKey),
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
        is_model_base = name == "Model"
        if not is_model_base:
            ModelMeta._validate_model_bases(bases)
            ModelMeta._validate_model_namespace(namespace)
        model_class = super().__new__(mcls, name, bases, namespace, **kwargs)
        annotations = ModelMeta._namespace_annotations(namespace)
        columns = ModelMeta._bind_columns(model_class, annotations)
        model_metadata = cast("Any", model_class)
        if not is_model_base:
            model_metadata.__tablename__ = ModelMeta._resolve_table_name(
                name,
                namespace,
            )
        model_metadata.__snekql_backend__ = ModelMeta._resolve_backend_family(
            bases,
            namespace,
        )
        model_metadata.__snekql_columns__ = columns
        model_metadata.__snekql_localns__ = ModelMeta._capture_declaring_localns(
            is_model_base=is_model_base,
        )
        if is_model_base:
            model_metadata.__snekql_indexes__ = ()
        else:
            model_metadata.__snekql_indexes__ = ModelMeta._bind_indexes(
                model_class,
                namespace,
                columns,
            )
        return model_class

    @staticmethod
    def _capture_declaring_localns(*, is_model_base: bool) -> dict[str, Any] | None:
        """Snapshot the defining scope's locals for later annotation resolution.

        The types a model validates against and its foreign-key targets are
        declared only in column annotations (`Col[T]` / `FKCol[Target, T]`),
        which carry no runtime value. Resolving them with `get_type_hints` needs
        the names visible where the model was declared -- including
        function-local types that module globals do not see -- so every concrete
        model snapshots its declaring scope.
        """

        if is_model_base:
            return None
        # Walk past this helper, __new__, and any PEP 695 type-parameter scopes
        # (a generic `class Order[S]` inserts a synthetic frame carrying
        # ``.type_params``) to reach the scope where the model was declared.
        current = inspect.currentframe()
        frame = current.f_back.f_back if current and current.f_back else None
        while frame is not None:
            if ".type_params" not in frame.f_locals:
                return dict(frame.f_locals)
            frame = frame.f_back
        return None

    @staticmethod
    def _validate_model_bases(bases: tuple[type, ...]) -> None:
        """Reject inheritance forms that would blur v1 table model semantics."""

        for base in bases:
            if isinstance(base, ModelMeta):
                if base.__name__ != "Model":
                    msg = f"cannot subclass concrete model: {base.__name__}"
                    raise ModelDeclarationError(msg)
                continue
            if base.__name__ == "Generic":
                continue
            msg = f"model mixin bases are not supported: {base.__name__}"
            raise ModelDeclarationError(msg)

    @staticmethod
    def _validate_model_namespace(namespace: dict[str, object]) -> None:
        """Validate class-body contents before freezing snekql metadata."""

        annotations = ModelMeta._namespace_annotations(namespace)
        for annotated_name, annotation in annotations.items():
            annotated_value = namespace.get(annotated_name)
            if isinstance(annotated_value, Attr):
                continue
            if annotated_name in {"__tablename__", "__indexes__"}:
                continue
            if ModelMeta._is_classvar_annotation(annotation):
                continue
            msg = f"unsupported model annotation: {annotated_name!r}"
            raise ModelDeclarationError(msg)
        for attribute_name, attribute_value in namespace.items():
            if isinstance(attribute_value, property):
                msg = f"computed properties are not supported: {attribute_name!r}"
                raise ModelDeclarationError(msg)
            if getattr(attribute_value, "__isabstractmethod__", False):
                msg = f"abstract members are not supported: {attribute_name!r}"
                raise ModelDeclarationError(msg)
            if attribute_name == "__indexes__" and not isinstance(
                attribute_value,
                list,
            ):
                msg = "__indexes__ must be a list"
                raise ModelDeclarationError(msg)

    @staticmethod
    def _namespace_annotations(namespace: dict[str, object]) -> dict[str, object]:
        annotations_object = namespace.get("__annotations__", {})
        if not isinstance(annotations_object, dict):
            return {}
        return cast("dict[str, object]", annotations_object)

    @staticmethod
    def _bind_columns(
        model_class: type,
        annotations: dict[str, object],
    ) -> dict[str, Attr[Any, Any, Any, Any, Any]]:
        columns: dict[str, Attr[Any, Any, Any, Any, Any]] = {}
        for attribute_name, attribute_value in model_class.__dict__.items():
            if not isinstance(attribute_value, Attr):
                continue
            column = cast("Attr[Any, Any, Any, Any, Any]", attribute_value)
            if not ModelMeta._is_sql_identifier(attribute_name):
                msg = f"invalid column identifier: {attribute_name!r}"
                raise ModelDeclarationError(msg)
            column.is_generated = ModelMeta._is_generated_annotation(
                annotations.get(attribute_name),
            )
            ModelMeta._validate_column_declaration(attribute_name, column)
            columns[attribute_name] = column
        return columns

    @staticmethod
    def _bind_indexes(
        model_class: type,
        namespace: dict[str, object],
        columns: dict[str, Attr[Any, Any, Any, Any, Any]],
    ) -> tuple[NormalizedIndex, ...]:
        indexes_object = namespace.get("__indexes__", [])
        if not isinstance(indexes_object, list):
            msg = "__indexes__ must be a list"
            raise ModelDeclarationError(msg)
        index_declarations = cast("list[object]", indexes_object)
        column_names_by_id = {id(column): name for name, column in columns.items()}
        table_name = cast("str", cast("Any", model_class).__tablename__)
        indexes: list[NormalizedIndex] = [
            NormalizedIndex(
                column_names=(column_name,),
                name=f"ux_{table_name}_{column_name}",
                unique=True,
            )
            for column_name, column in columns.items()
            if column.unique
        ]
        table_indexes: list[NormalizedIndex] = []
        for index_object in index_declarations:
            index = require_index_declaration(index_object)
            column_names: list[str] = []
            for column in index.columns:
                if column.owner is not model_class:
                    msg = "index columns must belong to the declaring model"
                    raise ModelDeclarationError(msg)
                try:
                    column_names.append(column_names_by_id[id(column)])
                except KeyError as error:
                    msg = "index columns must be declared model columns"
                    raise ModelDeclarationError(msg) from error
            index_name = index.name
            if index_name is None:
                prefix = "ux" if index.unique else "ix"
                index_name = f"{prefix}_{table_name}_{'_'.join(column_names)}"
            elif not ModelMeta._is_sql_identifier(index_name):
                msg = f"invalid index identifier: {index_name!r}"
                raise ModelDeclarationError(msg)
            normalized_index = NormalizedIndex(
                column_names=tuple(column_names),
                name=index_name,
                unique=index.unique,
            )
            indexes.append(normalized_index)
            table_indexes.append(normalized_index)
        ModelMeta._validate_index_set(indexes)
        return tuple(table_indexes)

    @staticmethod
    def _validate_index_set(indexes: list[NormalizedIndex]) -> None:
        names: set[str] = set()
        column_lists: set[tuple[str, ...]] = set()
        for index in indexes:
            if index.name in names:
                msg = f"duplicate index name: {index.name!r}"
                raise ModelDeclarationError(msg)
            names.add(index.name)
            if index.column_names in column_lists:
                msg = f"duplicate index column list: {index.column_names!r}"
                raise ModelDeclarationError(msg)
            column_lists.add(index.column_names)

    @staticmethod
    def _resolve_backend_family(
        bases: tuple[type, ...],
        namespace: dict[str, object],
    ) -> BackendFamily:
        configured_backend = namespace.get("__snekql_backend__")
        if configured_backend in {"mariadb", "sqlite"}:
            return cast("BackendFamily", configured_backend)
        for base in bases:
            inherited_backend = getattr(base, "__snekql_backend__", None)
            if inherited_backend in {"mariadb", "sqlite"}:
                return cast("BackendFamily", inherited_backend)
        return "sqlite"

    @staticmethod
    def _resolve_table_name(name: str, namespace: dict[str, object]) -> str:
        table_name = namespace.get("__tablename__", ModelMeta._infer_table_name(name))
        if not isinstance(table_name, str) or not ModelMeta._is_sql_identifier(
            table_name,
        ):
            msg = f"invalid table identifier: {table_name!r}"
            raise ModelDeclarationError(msg)
        return table_name

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
            msg = f"CurrentTimestamp cannot be a Python default for {name!r}"
            raise ModelDeclarationError(
                msg,
            )
        if column.unique and column.primary_key:
            msg = f"primary-key columns cannot be unique: {name!r}"
            raise ModelDeclarationError(msg)
        if column.auto_increment and (
            not column.primary_key or column.storage_type_name != "Integer"
        ):
            msg = f"auto-increment requires an integer primary-key column: {name!r}"
            raise ModelDeclarationError(msg)
        if column.server_default is None:
            return
        if not isinstance(column.server_default, CurrentTimestamp):
            msg = f"unsupported server default for {name!r}"
            raise ModelDeclarationError(
                msg,
            )
        if column.storage_type_name != "DateTime":
            msg = f"CurrentTimestamp requires a DateTime column: {name!r}"
            raise ModelDeclarationError(
                msg,
            )
        if not column.is_generated:
            msg = f"CurrentTimestamp requires a generated column: {name!r}"
            raise ModelDeclarationError(
                msg,
            )
        if column.default is not MISSING:
            msg = (
                f"CurrentTimestamp generated columns must default to MISSING: {name!r}"
            )
            raise ModelDeclarationError(
                msg,
            )
        if not isinstance(column.default_factory, EllipsisType):
            msg = f"CurrentTimestamp generated columns cannot use default_factory: {name!r}"
            raise ModelDeclarationError(
                msg,
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
            return annotation.startswith(("ClassVar[", "typing.ClassVar["))
        return get_origin(annotation) is ClassVar

    @staticmethod
    def _is_sql_identifier(value: str) -> bool:
        if value == "":
            return False
        first_character = value[0]
        if not (first_character.isalpha() or first_character == "_"):
            return False
        return all(character.isalnum() or character == "_" for character in value)


class Model[StateT, ReadModelT: "Table[Any]"](Table[StateT], metaclass=ModelMeta):
    """Base class for declaring table models.

    >>> class User[S = Pending](Model[S, "User[Fetched]"]):
    ...     email: User.Col[str] = Text(nullable=False)
    """

    __snekql_backend__: ClassVar[Literal["sqlite"]] = "sqlite"
    __snekql_columns__: ClassVar[dict[str, Attr[Any, Any, Any, Any, Any]]]
    __snekql_localns__: ClassVar[dict[str, Any] | None]
    __snekql_indexes__: ClassVar[tuple[NormalizedIndex, ...]]
    __tablename__: ClassVar[str]

    # Normal persisted-column alias scoped to the declaring model class.
    type Col[T] = Attr[Self, ReadModelT, Self, T, T]
    # Generated/server-filled column alias scoped to the declaring model class.
    type GenCol[T] = Attr[Self, ReadModelT, Self, T | Missing, T]
    # Foreign-key column alias; Target is the *Pending* owner of the referenced
    # model (`Order.FKCol[User, int]`). PEP 696 resolves the bare `User` to
    # `User[Pending]`, so no `[Pending]` suffix is required.
    type FKCol[Target, T] = FKAttr[Self, ReadModelT, Self, T, T, Target]

    def __init__(self, **values: object) -> None:
        self._snekql_populate(values, validate=True)

    @classmethod
    def construct(cls, **values: object) -> Self:
        """Build a Pending Model without running logical type validation.

        The escape hatch for values already known to satisfy their declared
        types -- materialized rows re-constructed by hand, trusted bulk loads --
        where the per-column pydantic check is redundant. Defaults, the
        missing/unknown structural checks, and freezing still apply; only the
        logical type validation is skipped. Construction itself has no clean slot
        for such a flag, so the unvalidated path is a classmethod.
        """

        instance = cls.__new__(cls)
        instance._snekql_populate(values, validate=False)  # noqa: SLF001
        return instance

    def _snekql_populate(
        self,
        values: dict[str, object],
        *,
        validate: bool,
    ) -> None:
        remaining_values = dict(values)
        storage = cast(
            "dict[str, object]",
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
                    msg = f"default factory failed for {name!r}"
                    raise ModelValidationError(
                        msg,
                    ) from error
            if isinstance(value, EllipsisType):
                msg = f"missing required value for {name!r}"
                raise ModelValidationError(msg)
            setattr(
                self, name, column.validate_model_value(value) if validate else value
            )
        if remaining_values:
            names = ", ".join(sorted(remaining_values))
            msg = f"unknown model values: {names}"
            raise ModelValidationError(msg)
        storage["_snekql_frozen"] = True

    def __setattr__(self, name: str, value: object) -> None:
        if getattr(self, "_snekql_frozen", False):
            msg = "table models are immutable"
            raise FrozenModelError(msg)
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
        other_model = cast("Model[Any, Any]", other)
        for name in self.__class__.__snekql_columns__:
            if getattr(self, name) != getattr(other_model, name):
                return False
        return True

    def __hash__(self) -> int:
        msg = f"unhashable type: {self.__class__.__name__!r}"
        raise TypeError(msg)

    def _snekql_state_name(self) -> str:
        storage = cast(
            "dict[str, object]",
            object.__getattribute__(self, "__dict__"),
        )
        state = storage.get("_snekql_state", "Pending")
        return cast("str", state)

    @classmethod
    def __read_type__(cls) -> type[ReadModelT]:
        return cast("type[ReadModelT]", cls)


def require_model_columns(
    model: type[Table[Any]],
) -> dict[str, Attr[Any, Any, Any, Any, Any]]:
    """Return frozen snekql column metadata for a table model."""

    columns = getattr(model, "__snekql_columns__", None)
    if not isinstance(columns, dict):
        msg = "schema setup requires snekql table models"
        raise ModelDeclarationError(msg)
    return cast("dict[str, Attr[Any, Any, Any, Any, Any]]", columns)


def require_model_table_name(model: type[Table[Any]]) -> str:
    """Return the resolved SQLite table name for a table model."""

    table_name = getattr(model, "__tablename__", None)
    if not isinstance(table_name, str):
        msg = "schema setup requires snekql table models"
        raise ModelDeclarationError(msg)
    return table_name


def require_model_backend(model: type[Table[Any]]) -> BackendFamily:
    """Return the backend family declared by a table model."""

    backend = getattr(model, "__snekql_backend__", None)
    if backend not in {"mariadb", "sqlite"}:
        msg = "schema setup requires snekql table models"
        raise ModelDeclarationError(msg)
    return cast("BackendFamily", backend)

"""Throwaway dual declarations lowered to native storage metadata and runtime.

`stored(sqlite.Text(), default=...)` is an adapter spelling, not a proposed
replacement for the backend's Column Type constructors. Native Attr objects
are copied before binding; no handwritten parallel storage model is maintained.
"""

from annotationlib import Format, get_annotations
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass, replace
from functools import reduce
from operator import or_
from types import MappingProxyType, UnionType
from typing import (
    Any,
    ClassVar,
    Generic,
    Literal,
    TypeVar,
    cast,
    dataclass_transform,
    get_args,
    get_origin,
    overload,
)

from snekql import mariadb, sqlite
from snekql.errors import ModelDeclarationError, ModelValidationError, SnekqlError
from snekql.query import _select_join
from snekql.storage import Attr

from scratchpad.dual_features.models import ReadRow
from scratchpad.dual_features.records import (
    OMIT,
    Assignment,
    Omitted,
)
from scratchpad.dual_features.records import Record as OriginalRecord

Owner = TypeVar("Owner")
Value = TypeVar("Value")
Target = TypeVar("Target", bound=ReadRow)

# Capture exactly constructor metadata; never copy owner/name or adapter caches.
_STORAGE_FACTS = (
    "storage_class",
    "storage_type_name",
    "auto_increment",
    "decimal_precision",
    "decimal_scale",
    "text_length",
    "text_collation",
    "index",
    "keyable",
    "primary_key",
    "unique",
)


@dataclass(frozen=True)
class Declaration:
    """Immutable column declaration before its logical annotation is bound."""

    storage: tuple[tuple[str, object], ...]
    attribute_type: Any = Attr
    default: object = ...
    default_factory: Any = ...
    nullable: bool | None = None
    target: Callable[[], Column[Any, Any]] | None = None
    enforced: bool = True
    primary_key: bool = False
    unique: bool = False
    index: bool = False
    on_update: str | None = None
    on_delete: str | None = None

    def native(self) -> Any:
        return self.attribute_type(
            **dict[str, Any](self.storage),
            default=sqlite.PENDING_GENERATION if self.default is OMIT else self.default,
            default_factory=self.default_factory,
            nullable=self.nullable,
        )


@dataclass(frozen=True)
class Column(Generic[Owner, Value]):
    """A model/name key; finalized native metadata supplies storage and codecs."""

    owner: type[Owner]
    name: str

    @property
    def native(self) -> Any:
        binding = getattr(self.owner, "binding", None)
        if binding is None or not issubclass(self.owner, ReadRow):
            raise ModelDeclarationError("SQL columns require finalized Fetched Models")
        return getattr(binding, self.name)

    def to(self, value: Value | type[sqlite.CurrentTimestamp]) -> Assignment[Owner]:
        return Assignment(self.name, self.owner, value)

    def eq(self, value: Value) -> Condition[Owner]:
        return Condition(self.native.eq(value))


class FieldDefinition[Value]:
    """Immutable declaration metadata, independent of a query expression interface."""

    def __init__(self, declaration: Declaration) -> None:
        object.__setattr__(self, "declaration", declaration)
        object.__setattr__(self, "name", "")

    declaration: Declaration
    name: str

    def __setattr__(self, name: str, value: object) -> None:
        raise sqlite.FrozenModelError("Field declaration metadata is immutable")

    def __set_name__(self, owner: type[object], name: str) -> None:
        del owner
        if self.name and self.name != name:
            raise ModelDeclarationError("A descriptor cannot declare two fields")
        object.__setattr__(self, "name", name)

    @contextmanager
    def native_binding(self, owner: type[object], column: Any) -> Iterator[Any]:
        """Allow query-aware descriptors to supply the canonical native column."""
        del owner
        yield column

    def instance_value(self, instance: OriginalRecord) -> Value:
        return cast("Value", instance.values[self.name])

    def __set__(self, instance: object, value: Value) -> None:
        raise ModelValidationError("Model values are immutable")


class Field[Value](FieldDefinition[Value]):
    """Legacy query columns on classes; logical values on instances."""

    @overload
    def __get__[Owner](
        self, instance: None, owner: type[Owner]
    ) -> Column[Owner, Value]: ...
    @overload
    def __get__(self, instance: object, owner: type[object]) -> Value: ...
    def __get__[Owner](
        self, instance: object, owner: type[Owner]
    ) -> Column[Owner, Value] | Value:
        if instance is None:
            return Column(owner, self.name)
        if not isinstance(instance, OriginalRecord):
            raise ModelDeclarationError("Field requires a model instance")
        return self.instance_value(instance)


class ForeignDefinition:
    """Marker for a declaration whose annotation retains a foreign target."""


class ForeignField[Target: ReadRow, Value](Field[Value], ForeignDefinition):
    """Refinement keeps this descriptor subtype, including its target identity."""

    @overload
    def __get__[Owner](
        self, instance: None, owner: type[Owner]
    ) -> ForeignColumn[Owner, Target, Value]: ...
    @overload
    def __get__(self, instance: object, owner: type[object]) -> Value: ...
    def __get__[Owner](
        self, instance: object, owner: type[Owner]
    ) -> ForeignColumn[Owner, Target, Value] | Value:
        if instance is None:
            return ForeignColumn(owner, self.name)
        return super().__get__(instance, owner)


@dataclass(frozen=True)
class ForeignColumn(Column[Owner, Value], Generic[Owner, Target, Value]):
    """Typed relationship target independent of input/fetched lifecycle."""

    @overload
    def references[NonNull](
        self: ForeignColumn[Owner, Target, NonNull | None],
        target: Column[Target, NonNull],
    ) -> Condition[Owner | Target]: ...
    @overload
    def references(
        self, target: Column[Target, Value]
    ) -> Condition[Owner | Target]: ...
    def references(self, target: Any) -> Condition[Owner | Target]:
        expected = _require_fetched(self.owner).resolved_targets[self.name]
        if target.owner is not expected.owner or target.name != expected.name:
            raise ModelDeclarationError(
                "references() must use the exact declared target column"
            )
        return cast(
            "Condition[Owner | Target]", Condition(self.native.eq_col(target.native))
        )


@overload
def foreign[Target: ReadRow, Value](
    target: Column[Target, Value] | Callable[[], Column[Target, Value]],
    *,
    default: sqlite.LiteralDefault[None],
    on_update: str | None = None,
    on_delete: str | None = None,
    enforced: bool = True,
    primary_key: bool = False,
    unique: bool = False,
    index: bool = False,
    storage: Any = None,
) -> ForeignField[Target, Value | Omitted | None]: ...
@overload
def foreign[Target: ReadRow, Value](
    target: Column[Target, Value] | Callable[[], Column[Target, Value]],
    *,
    default: sqlite.LiteralDefault[Value],
    on_update: str | None = None,
    on_delete: str | None = None,
    enforced: bool = True,
    primary_key: bool = False,
    unique: bool = False,
    index: bool = False,
    storage: Any = None,
) -> ForeignField[Target, Value | Omitted]: ...
@overload
def foreign[Target: ReadRow, Value](
    target: Column[Target, Value] | Callable[[], Column[Target, Value]],
    *,
    default: None,
    on_update: str | None = None,
    on_delete: str | None = None,
    enforced: bool = True,
    primary_key: bool = False,
    unique: bool = False,
    index: bool = False,
    storage: Any = None,
) -> ForeignField[Target, Value | None]: ...
@overload
def foreign[Target: ReadRow, Value](
    target: Column[Target, Value] | Callable[[], Column[Target, Value]],
    *,
    default: Omitted | type[sqlite.CurrentTimestamp],
    on_update: str | None = None,
    on_delete: str | None = None,
    enforced: bool = True,
    primary_key: bool = False,
    unique: bool = False,
    index: bool = False,
    storage: Any = None,
) -> ForeignField[Target, Value | Omitted]: ...
@overload
def foreign[Target: ReadRow, Value](
    target: Column[Target, Value] | Callable[[], Column[Target, Value]],
    *,
    default: Value = ...,
    on_update: str | None = None,
    on_delete: str | None = None,
    enforced: bool = True,
    primary_key: bool = False,
    unique: bool = False,
    index: bool = False,
    storage: Any = None,
) -> ForeignField[Target, Value]: ...
def foreign(
    target: Any,
    *,
    default: Any = ...,
    on_update: str | None = None,
    on_delete: str | None = None,
    enforced: bool = True,
    primary_key: bool = False,
    unique: bool = False,
    index: bool = False,
    storage: Any = None,
) -> Any:
    """Derive storage from an exact column, or declare a typed-only reference."""
    if enforced and storage is not None:
        raise ModelDeclarationError(
            "Physical foreign keys derive storage; only typed-only references accept storage"
        )
    resolver = target if callable(target) else lambda: target
    template = stored(storage).declaration if storage is not None else Declaration(())
    return ForeignField(
        replace(
            template,
            default=default,
            target=resolver,
            on_update=on_update,
            on_delete=on_delete,
            enforced=enforced,
            primary_key=primary_key,
            unique=unique,
            index=index,
        )
    )


@dataclass(frozen=True)
class Refinement:
    """Remove Omitted, preserving the entire inherited declaration."""


def required() -> Any:
    """Refine a generated input field without constructing new storage metadata."""
    return Refinement()


def stored(native: Any, *, default: Any = ..., default_factory: Any = ...) -> Any:
    """Capture a native Column Type; the outer default is visible to dataclass_transform."""
    if not isinstance(native, Attr) or native.owner is not None:
        raise ModelDeclarationError("stored requires a fresh Column Type declaration")
    if native.foreign_key_target is not None:
        raise ModelDeclarationError("Use foreign() to retain relationship identity")
    if native.default is not ... or native.default_factory is not ...:
        raise ModelDeclarationError(
            "Put constructor defaults on stored(), where ty sees them"
        )
    return Field(
        Declaration(
            tuple((name, getattr(native, name)) for name in _STORAGE_FACTS),
            attribute_type=type(native),
            default=default,
            default_factory=default_factory,
            nullable=native.nullable_declared,
        )
    )


def _logical(annotation: object) -> object:
    return get_args(annotation)[-1]


def _without_omitted(annotation: Any) -> Any:
    if get_origin(annotation) is not UnionType:
        return annotation
    members = [member for member in get_args(annotation) if member is not Omitted]
    return reduce(or_, members)


class RecordMeta(type):
    """Prevent declaration replacement after this study's explicit finalization step."""

    def __setattr__(cls, name: str, value: object) -> None:
        if vars(cls).get("_finalized", False) and (
            name in getattr(cls, "fields", {})
            or name
            in {
                "fields",
                "logical",
                "refined",
                "binding",
                "table_name",
                "__indexes__",
                "__foreign_keys__",
                "__checks__",
                "__annotations__",
                "_finalized",
                "resolved_targets",
                "_dependencies",
            }
        ):
            raise sqlite.FrozenModelError("Finalized dual model metadata is immutable")
        super().__setattr__(name, value)

    def __delattr__(cls, name: str) -> None:
        if vars(cls).get("_finalized", False):
            raise sqlite.FrozenModelError("Finalized dual model metadata is immutable")
        super().__delattr__(name)


@dataclass_transform(
    field_specifiers=(stored, required, foreign),
    frozen_default=True,
    kw_only_default=True,
)
class Record(OriginalRecord, metaclass=RecordMeta):
    """Dual declaration root. Schema finalization precedes model construction."""

    fields: ClassVar[Mapping[str, FieldDefinition[Any]]] = MappingProxyType({})
    logical: ClassVar[Mapping[str, Any]] = MappingProxyType({})
    refined: ClassVar[frozenset[str]] = frozenset()
    binding: ClassVar[Any] = None
    _finalized: ClassVar[bool] = False
    _dependencies: ClassVar[tuple[type[Record], ...]] = ()
    resolved_targets: ClassVar[Mapping[str, Column[Any, Any]]] = MappingProxyType({})
    table_name: ClassVar[str]

    def __init_subclass__(cls) -> None:
        fields: dict[str, FieldDefinition[Any]] = {}
        logical: dict[str, Any] = {}
        refined: set[str] = set()
        for base in reversed(cls.__mro__[1:]):
            if issubclass(base, Record):
                fields.update(base.fields)
                logical.update(base.logical)
                refined.update(base.refined)
        for name, annotation in get_annotations(cls, format=Format.FORWARDREF).items():
            origin = get_origin(annotation)
            if not isinstance(origin, type) or not issubclass(origin, FieldDefinition):
                continue
            descriptor = vars(cls).get(name)
            if issubclass(cls, ReadRow) and not isinstance(descriptor, Refinement):
                raise ModelDeclarationError(
                    "Fetched models refine constructor shape, not storage; declare fields on the input"
                )
            if isinstance(descriptor, Refinement):
                if name not in fields or _logical(annotation) != _without_omitted(
                    logical[name]
                ):
                    raise ModelDeclarationError(
                        "Refinement must preserve the logical type and remove only Omitted"
                    )
                descriptor = type(fields[name])(fields[name].declaration)
                descriptor.__set_name__(cls, name)
                setattr(cls, name, descriptor)
                refined.add(name)
            if not isinstance(descriptor, FieldDefinition):
                raise ModelDeclarationError(
                    "Every new or refined field needs an explicit descriptor"
                )
            declaration = descriptor.declaration
            generated = (
                declaration.default is OMIT
                or declaration.default is sqlite.CurrentTimestamp
                or isinstance(declaration.default, sqlite.LiteralDefault)
            )
            if (
                not issubclass(cls, ReadRow)
                and generated
                and Omitted not in get_args(_logical(annotation))
            ):
                raise ModelDeclarationError("Generated input fields must admit Omitted")
            fields[name] = descriptor
            logical[name] = _logical(annotation)
        cls.fields = MappingProxyType(fields)
        cls.logical = MappingProxyType(logical)
        cls.refined = frozenset(refined)
        cls.binding = None

    @classmethod
    def _prepare(
        cls, provided: Mapping[str, object], *, for_insert: bool = False
    ) -> dict[str, object]:
        if cls.binding is None:
            raise ModelDeclarationError(
                "Finalize the model pair with Schema before construction"
            )
        if provided.keys() - cls.fields.keys():
            raise ModelValidationError("Unknown model fields")
        prepared: dict[str, object] = {}
        for name in cls.fields:
            column = cls.binding.__snekql_columns__[name]
            if name in provided:
                value = provided[name]
            elif name in cls.refined and not for_insert:
                raise ModelValidationError(f"Missing fetched field {name!r}")
            else:
                try:
                    value = column.build_default()
                except SnekqlError:
                    raise
                except Exception as error:
                    raise ModelValidationError(
                        f"Default factory failed for {name!r}"
                    ) from error
            if value is OMIT or value is sqlite.PENDING_GENERATION:
                if not column.is_generated or (
                    issubclass(cls, ReadRow) and not for_insert
                ):
                    raise ModelValidationError(
                        "Omitted is only valid on generated input fields"
                    )
                if not for_insert:
                    prepared[name] = OMIT
                continue
            if value is ...:
                raise ModelValidationError(f"Missing required field {name!r}")
            prepared[name] = column.validate_model_value(value)
        return prepared


@dataclass(frozen=True)
class Insert[Row: Record]:
    """Validated input values; only a Transaction executes this command."""

    row_type: type[Row]
    values: Mapping[str, object]


class BoundInsert[**Parameters, Input: Record, Row: Record]:
    def __init__(self, factory: Callable[Parameters, Input], row: type[Row]) -> None:
        self.factory: Callable[Parameters, Input] = factory
        self.row: type[Row] = row

    def __call__(
        self, *args: Parameters.args, **kwargs: Parameters.kwargs
    ) -> Insert[Row]:
        source = self.factory(*args, **kwargs)
        return Insert(
            self.row,
            MappingProxyType(self.row._prepare(source.values, for_insert=True)),
        )


class InsertUsing[**Parameters, Input: Record]:
    def __init__(self, factory: Callable[Parameters, Input]) -> None:
        self.input_factory: Callable[Parameters, Input] = factory

    def __get__[Row: Record](
        self, instance: object, owner: type[Row]
    ) -> BoundInsert[Parameters, Input, Row]:
        del instance
        return BoundInsert(self.input_factory, owner)


def insert_using[**Parameters, Input: Record](
    factory: Callable[Parameters, Input],
) -> InsertUsing[Parameters, Input]:
    """Capture the input signature while class access supplies the Fetched Model type."""
    return InsertUsing(factory)


@dataclass(frozen=True)
class Check:
    """Bounded metadata adapter, not a replacement for main's CHECK grammar."""

    column: Any
    operation: str
    value: object
    name: str = ""

    def expression(self, row: type[Record], native: Any) -> Any:
        if self.operation not in {"gt", "gte", "lt", "lte", "eq", "ne"}:
            raise ModelDeclarationError("Unsupported research CHECK operation")
        return getattr(getattr(native, _local_name(row, self.column)), self.operation)(
            self.value
        )


@dataclass(frozen=True, init=False)
class Index:
    columns: tuple[Any, ...]
    unique: bool
    name: str | None
    prefix_lengths: tuple[int | None, ...] | None
    where: Check | None

    def __init__(
        self,
        *columns: Any,
        unique: bool = False,
        name: str | None = None,
        prefix_lengths: tuple[int | None, ...] | None = None,
        where: Check | None = None,
    ) -> None:
        object.__setattr__(self, "columns", columns)
        object.__setattr__(self, "unique", unique)
        object.__setattr__(self, "name", name)
        object.__setattr__(self, "prefix_lengths", prefix_lengths)
        object.__setattr__(self, "where", where)


@dataclass(frozen=True, init=False)
class ForeignKeyConstraint:
    columns: tuple[Any, ...]
    references: Any
    on_update: str | None
    on_delete: str | None

    def __init__(
        self,
        *columns: Any,
        references: Any,
        on_update: str | None = None,
        on_delete: str | None = None,
    ) -> None:
        object.__setattr__(self, "columns", columns)
        object.__setattr__(self, "references", references)
        object.__setattr__(self, "on_update", on_update)
        object.__setattr__(self, "on_delete", on_delete)


def _column_reference(column: Any) -> Any:
    """Read declaration identity without forcing a native query column to bind."""
    reference = getattr(type(column), "__declaration_reference__", None)
    return reference(column) if callable(reference) else column


def _local_name(row: type[Record], column: Any) -> str:
    column = _column_reference(column)
    if isinstance(column, Column):
        if column.owner is not row:
            raise ModelDeclarationError("Constraint column belongs to another model")
        return column.name
    if isinstance(column, FieldDefinition) and any(
        vars(base).get(column.name) is column for base in row.__mro__
    ):
        return column.name
    raise ModelDeclarationError(
        "Constraint must name an actual inherited or local field"
    )


class Schema:
    """Finalize a closed set of dual models through native ModelMeta exactly once."""

    def __init__(
        self, *rows: type[Record], backend: Literal["sqlite", "mariadb"] = "sqlite"
    ) -> None:
        if backend not in {"sqlite", "mariadb"}:
            raise ModelDeclarationError("Unknown Backend Family")
        self.backend: str = backend
        self.namespace: Any = sqlite if backend == "sqlite" else mariadb
        self.models: dict[type[Record], Any] = {}
        self._building: set[type[Record]] = set()
        self._targets: dict[type[Record], dict[str, Column[Any, Any]]] = {}
        self._dependencies: dict[type[Record], list[type[Record]]] = {}
        for row in rows:
            self._build(row)
        # Validate the complete native schema before publishing any bindings.
        self.scaffold()
        for row, native in self.models.items():
            if not vars(row).get("_finalized", False):
                row.binding = native
                row.resolved_targets = MappingProxyType(self._targets[row])
                row._dependencies = tuple(self._dependencies[row])
                row._finalized = True
            for base in row.__mro__[1:]:
                if (
                    issubclass(base, Record)
                    and base.fields
                    and not issubclass(base, ReadRow)
                    and base.binding is None
                ):
                    base.binding = native
                    base._finalized = True

    def _build(self, row: type[Record]) -> Any:
        if not issubclass(row, ReadRow):
            raise ModelDeclarationError(
                "Schema requires Fetched Models, not input classes"
            )
        for base in row.__mro__:
            constructor = vars(base).get("create")
            if isinstance(constructor, InsertUsing):
                source = constructor.input_factory
                if (
                    not isinstance(source, type)
                    or not issubclass(row, source)
                    or set(getattr(source, "fields", {})) != set(row.fields)
                ):
                    raise ModelDeclarationError(
                        "create must bind the matching complete input constructor"
                    )
                break
        if row in self.models:
            return self.models[row]
        if vars(row).get("_finalized", False):
            if row.binding.__snekql_backend__ != self.backend:
                raise ModelDeclarationError(
                    "A finalized pair belongs to one Backend Family"
                )
            for dependency in row._dependencies:
                self._build(dependency)
            self.models[row] = row.binding
            return row.binding
        if row in self._building:
            raise ModelDeclarationError(
                "Mutual table dependency needs a two-phase native finalizer; unsupported here"
            )
        self._building.add(row)
        self._targets[row] = {}
        self._dependencies[row] = []
        columns: dict[str, Any] = {}
        resolving: set[str] = set()
        constraints: list[Any] = []

        def build_column(name: str) -> Any:
            if name in columns:
                return columns[name]
            if name in resolving:
                raise ModelDeclarationError(
                    "Foreign storage derivation has no concrete root"
                )
            resolving.add(name)
            declaration = row.fields[name].declaration
            if declaration.target is None:
                native = declaration.native()
            else:
                target = declaration.target()
                if not isinstance(target, Column) or not issubclass(
                    target.owner, Record
                ):
                    raise ModelDeclarationError(
                        "Foreign target must be a dual-class column"
                    )
                owner = target.owner
                if owner is not row and owner not in self._dependencies[row]:
                    self._dependencies[row].append(owner)
                self._targets[row][name] = target
                annotation = next(
                    get_annotations(base, format=Format.FORWARDREF)[name]
                    for base in row.__mro__
                    if name in get_annotations(base, format=Format.FORWARDREF)
                )
                arguments = get_args(annotation)
                if (
                    get_origin(annotation) is not ForeignField
                    or arguments[0] is not owner
                ):
                    raise ModelDeclarationError(
                        "Foreign annotation and exact target model disagree"
                    )
                if target.name not in owner.fields:
                    raise ModelDeclarationError(
                        "Foreign target must name a declared field"
                    )
                target_native = (
                    build_column(target.name)
                    if owner is row
                    else getattr(self._build(owner), target.name)
                )
                default = (
                    sqlite.PENDING_GENERATION
                    if declaration.default is OMIT
                    else declaration.default
                )
                if declaration.enforced:
                    native = self.namespace.ForeignKey(
                        target_native,
                        default=default,
                        nullable=declaration.nullable,
                        primary_key=declaration.primary_key,
                        unique=declaration.unique,
                        index=declaration.index,
                    )
                    # Main has separate GenCol/FKCol annotation paths. Table constraints
                    # preserve both generation and physical relationships without lying
                    # to either path or changing finalized native metadata.
                    native.foreign_key_target = None
                    # Native ForeignKey currently omits these storage parameters.
                    native.decimal_precision = target_native.decimal_precision
                    native.decimal_scale = target_native.decimal_scale
                    constraints.append(
                        self.namespace.ForeignKeyConstraint(
                            native,
                            references=(target_native,),
                            on_update=declaration.on_update,
                            on_delete=declaration.on_delete,
                        )
                    )
                else:
                    if not declaration.storage:
                        raise ModelDeclarationError(
                            "Typed-only references require explicit local storage"
                        )
                    native = declaration.native()
                    native.primary_key = native.primary_key or declaration.primary_key
                    native.unique = native.unique or declaration.unique
                    native.index = native.index or declaration.index
            columns[name] = native
            resolving.remove(name)
            return native

        for name in row.fields:
            build_column(name)
        columns = {name: columns[name] for name in row.fields}

        def indexes(native: Any) -> list[Any]:
            return [
                self.namespace.Index(
                    *(columns[_local_name(row, member)] for member in index.columns),
                    unique=index.unique,
                    name=index.name,
                    prefix_lengths=index.prefix_lengths,
                    where=None
                    if index.where is None
                    else index.where.expression(row, native),
                )
                for index in getattr(row, "__indexes__", ())
            ]

        def checks(native: Any) -> list[Any]:
            return [
                self.namespace.CheckConstraint(
                    check.expression(row, native), name=check.name
                )
                for check in getattr(row, "__checks__", ())
            ]

        for constraint in getattr(row, "__foreign_keys__", ()):
            targets = (
                constraint.references()
                if callable(constraint.references)
                else constraint.references
            )
            for target in targets:
                if (
                    target.owner is not row
                    and target.owner not in self._dependencies[row]
                ):
                    self._dependencies[row].append(target.owner)
            references = tuple(
                columns[target.name]
                if target.owner is row
                else getattr(self._build(target.owner), target.name)
                for target in targets
            )
            constraints.append(
                self.namespace.ForeignKeyConstraint(
                    *(
                        columns[_local_name(row, member)]
                        for member in constraint.columns
                    ),
                    references=references,
                    on_update=constraint.on_update,
                    on_delete=constraint.on_delete,
                )
            )
        annotations: dict[str, Any] = {}
        for name, logical in row.logical.items():
            if Omitted in get_args(logical):
                raise ModelDeclarationError("Fetched fields must remove Omitted")
            declaration = row.fields[name].declaration
            generated = (
                declaration.default is OMIT
                or declaration.default is sqlite.CurrentTimestamp
                or isinstance(declaration.default, sqlite.LiteralDefault)
            )
            annotations[name] = (
                self.namespace.GenCol[logical]
                if generated
                else self.namespace.Col[logical]
            )
        native = type(
            f"{row.__name__}Storage",
            (self.namespace.Model,),
            {
                "__module__": __name__,
                "__tablename__": row.table_name,
                "__annotations__": annotations,
                "__snekql_hints__": annotations,
                "__foreign_keys__": constraints,
                "__indexes__": classmethod(indexes),
                "__checks__": classmethod(checks),
                **columns,
            },
        )
        self.models[row] = native
        self._building.remove(row)
        return native

    def native(self, row: type[Record]) -> Any:
        """Erased native bridge for research controls, not a typed application facade."""
        return self.models[row]

    def scaffold(self) -> str:
        """Dev-time scaffold text; callers still own their migration declarations."""
        return cast("str", self.namespace.scaffold(list(self.models.values())))


Scope_co = TypeVar("Scope_co", covariant=True)
State = TypeVar("State")
Result = TypeVar("Result")


class Unscoped:
    """A SELECT has not declared row scope."""


class Ready:
    """A SELECT has explicit row scope."""


@dataclass(frozen=True)
class Condition(Generic[Scope_co]):
    native: Any

    def __and__[Other](self, other: Condition[Other]) -> Condition[Scope_co | Other]:
        return cast(
            "Condition[Scope_co | Other]", Condition(self.native & other.native)
        )


@dataclass(frozen=True)
class Query(Generic[Owner, State, Result]):
    """A bounded query adapter; native compilation and materialization stay authoritative."""

    native: Any
    decode: Callable[[Any], Result]

    def join[Other: ReadRow](
        self, other: type[Other], *, on: Condition[Owner | Other]
    ) -> Query[Owner | Other, State, Result]:
        native = type(self.native)(
            _select_join(
                self.native.state,
                _require_fetched(other).binding,
                on.native,
                "INNER",
                project=True,
            )
        )
        return cast("Query[Owner | Other, State, Result]", Query(native, self.decode))

    def all(self) -> Query[Owner, Ready, Result]:
        return Query(self.native.all(), self.decode)

    def where(self, condition: Condition[Owner]) -> Query[Owner, Ready, Result]:
        return Query(self.native.where(condition.native), self.decode)

    def compile(self: Query[Owner, Ready, Result]) -> Any:
        return self.native.compile()


def _materialize[Row: Record](row: type[Row], native: Any) -> Row:
    return row(**{name: getattr(native, name) for name in row.fields})


@overload
def select[Row: ReadRow](row: type[Row]) -> Query[Row, Unscoped, Row]: ...
@overload
def select[Row: ReadRow, Value](
    row: Column[Row, Value],
) -> Query[Row, Unscoped, Value]: ...
def select(row: Any) -> Any:
    if isinstance(row, Column):
        return Query(sqlite.select(row.native), lambda value: value)
    row = _require_fetched(row)
    names = tuple(row.fields)
    native = sqlite.select(*(getattr(row.binding, name) for name in names))

    def decode(values: Any) -> Any:
        slots = values if len(names) > 1 else (values,)
        return row(**dict(zip(names, slots, strict=True)))

    return Query(native, decode)


class Transaction:
    """Use an active native SQLite transaction; this adapter owns no connection lifecycle."""

    def __init__(self, native: sqlite.Transaction, schema: Schema) -> None:
        self.native: sqlite.Transaction = native
        self.schema: Schema = schema

    @overload
    async def execute[Row: Record](self, command: Insert[Row]) -> Row: ...
    @overload
    async def execute[Row: ReadRow](self, command: WriteCount[Row, Ready]) -> int: ...
    async def execute(self, command: Any) -> Any:
        if isinstance(command, WriteCount):
            return await self.native.execute(command.native)
        row = _require_fetched(command.row_type)
        native = self.schema.native(row)
        values = native(**command.values)
        fetched = await self.native.execute(sqlite.insert(values).returning())
        return _materialize(row, fetched)

    async def fetch_all[Row: ReadRow, Result](
        self, query: Query[Row, Ready, Result]
    ) -> list[Result]:
        native: Any = self.native
        return [query.decode(row) for row in await native.fetch_all(query.native)]


@dataclass(frozen=True)
class WriteCount(Generic[Owner, State]):
    native: Any

    def where(self, condition: Condition[Owner]) -> WriteCount[Owner, Ready]:
        return WriteCount(self.native.where(condition.native))

    def all(self) -> WriteCount[Owner, Ready]:
        return WriteCount(self.native.all())


@dataclass(frozen=True)
class Update(Generic[Owner]):
    row: type[Owner]

    def set(
        self, first: Assignment[Owner], *rest: Assignment[Owner]
    ) -> WriteCount[Owner, Unscoped]:
        native = _require_fetched(self.row).binding
        assignments = (first, *rest)
        if any(assignment.owner is not self.row for assignment in assignments):
            raise ModelDeclarationError("Assignment belongs to another model")
        return WriteCount(
            sqlite.update(native).set(
                *(
                    getattr(native, assignment.name).to(assignment.value)
                    for assignment in assignments
                )
            )
        )


def update[Row: ReadRow](row: type[Row]) -> Update[Row]:
    return Update(row)


def _require_fetched(owner: type[object]) -> type[Record]:
    if (
        not isinstance(owner, type)
        or not issubclass(owner, Record)
        or not issubclass(owner, ReadRow)
        or owner.binding is None
    ):
        raise ModelDeclarationError("SQL requires a finalized Fetched Model")
    return owner

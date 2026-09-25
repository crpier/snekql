"""Throwaway comparison of declaration contracts and graph finalization.

Input validation does not need a table binding or foreign target resolution.
The native runtime still owns encoding and materialization.
"""

from annotationlib import Format, get_annotations
from collections.abc import Mapping
from contextlib import ExitStack
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, ClassVar, Literal, cast, get_args, get_origin, overload

from pydantic import TypeAdapter
from snekql import mariadb, sqlite
from snekql._declaration_binding import _OnceBinding
from snekql.errors import ModelDeclarationError, ModelValidationError, SnekqlError
from snekql.model import ModelMeta
from snekql.storage import (
    _annotation_admits_none,
    _annotation_core_types,
    _strip_json_marker,
)

from scratchpad.dual_storage.interface import (
    OMIT,
    Check,
    Column,
    Field,
    ForeignDefinition,
    ForeignField,
    ForeignKeyConstraint,
    Index,
    Insert,
    InsertUsing,
    Omitted,
    Query,
    ReadRow,
    Ready,
    WriteCount,
    _column_reference,
    _local_name,
    _materialize,
    _without_omitted,
    foreign,
    insert_using,
    required,
    select,
    stored,
    update,
)
from scratchpad.dual_storage.interface import (
    Record as StorageRecord,
)
from scratchpad.dual_storage.interface import (
    RecordMeta as StorageRecordMeta,
)

__all__ = [
    "OMIT",
    "Check",
    "Column",
    "Field",
    "ForeignField",
    "ForeignKeyConstraint",
    "Index",
    "Insert",
    "Omitted",
    "Query",
    "ReadRow",
    "Ready",
    "Record",
    "Schema",
    "Transaction",
    "foreign",
    "insert_using",
    "required",
    "select",
    "stored",
    "update",
]


class RecordMeta(StorageRecordMeta):
    """Read-only declaration facts with a separately memoized native binding."""

    def __getattribute__(cls, name: str) -> object:  # noqa: N805
        if name in {"binding", "resolved_targets"}:
            definition = type.__getattribute__(cls, "__dict__").get("_definition")
            if isinstance(definition, Definition):
                return (
                    definition.state.get().native
                    if name == "binding"
                    else definition.state.get().targets
                )
            return None
        return super().__getattribute__(name)

    def __setattr__(cls, name: str, value: object) -> None:  # noqa: N805
        if vars(cls).get("_finalized", False) and name in {
            "_definition",
            "backend",
            "create",
        }:
            raise sqlite.FrozenModelError(
                "Declaration facts cannot change after class creation"
            )
        super().__setattr__(name, value)


class Record(StorageRecord, metaclass=RecordMeta):
    """Validate input values against their own declaration, without a table registry."""

    backend: ClassVar[Literal["sqlite", "mariadb"]] = "sqlite"
    _definition: ClassVar[Definition | None] = None

    def __init_subclass__(
        cls, *, backend: Literal["sqlite", "mariadb"] | None = None
    ) -> None:
        super().__init_subclass__()
        if backend is not None:
            cls.backend = backend
        if cls.backend not in {"sqlite", "mariadb"}:
            raise ModelDeclarationError("Unknown Backend Family")
        for name, descriptor in cls.fields.items():
            declaration = descriptor.declaration
            logical = _strip_json_marker(_without_omitted(cls.logical[name]))
            admits_none = _annotation_admits_none(logical)
            if declaration.nullable is not None and declaration.nullable != admits_none:
                raise ModelDeclarationError(
                    f"Nullable assertion disagrees with {name!r}"
                )
            physical = dict(declaration.storage)
            if admits_none and (declaration.primary_key or physical.get("primary_key")):
                raise ModelDeclarationError("Primary keys cannot include None")
        cls._definition = Definition(cls) if issubclass(cls, ReadRow) else None
        cls._finalized = True

    @classmethod
    def _prepare(
        cls, provided: Mapping[str, object], *, for_insert: bool = False
    ) -> dict[str, object]:
        if provided.keys() - cls.fields.keys():
            raise ModelValidationError("Unknown model fields")
        prepared: dict[str, object] = {}
        for name, descriptor in cls.fields.items():
            declaration = descriptor.declaration
            generated = (
                declaration.default is OMIT
                or declaration.default is sqlite.CurrentTimestamp
                or isinstance(declaration.default, sqlite.LiteralDefault)
            )
            if name in provided:
                value = provided[name]
            elif name in cls.refined and not for_insert:
                raise ModelValidationError(f"Missing fetched field {name!r}")
            else:
                try:
                    value = (
                        declaration.default_factory()
                        if declaration.default_factory is not ...
                        else OMIT
                        if generated
                        else declaration.default
                    )
                except SnekqlError:
                    raise
                except Exception as error:
                    raise ModelValidationError(
                        f"Default factory failed for {name!r}"
                    ) from error
            if value is OMIT:
                if not generated or (issubclass(cls, ReadRow) and not for_insert):
                    raise ModelValidationError(
                        "Omitted is only valid on generated input fields"
                    )
                if not for_insert:
                    prepared[name] = OMIT
                continue
            if value is ...:
                raise ModelValidationError(f"Missing required field {name!r}")
            logical = _strip_json_marker(_without_omitted(cls.logical[name]))
            # Preserve native NULL handling, which bypasses logical validators.
            if value is None:
                if not _annotation_admits_none(logical):
                    raise ModelValidationError(f"{name!r} cannot be null")
                prepared[name] = None
                continue
            # Match native bool-as-int handling, which follows Python's subtype rule.
            if type(value) is bool and _annotation_core_types(logical) == [int]:
                value = int(value)
            try:
                prepared[name] = TypeAdapter(logical).validate_python(
                    value, strict=True
                )
            except SnekqlError:
                raise
            except Exception as error:
                raise ModelValidationError(
                    f"Invalid model value for {name!r}"
                ) from error
        return prepared


@dataclass(frozen=True)
class Compiled:
    """Published together only after every native model and constraint validates."""

    native: Any
    graph: Mapping[type[Record], Any]
    targets: Mapping[str, Column[Any, Any]]


class Binding:
    """Mutable once-only state is separate from the immutable declaration."""

    def __init__(self, definition: Definition) -> None:
        self.value: Compiled | None = None
        self.failure: Exception | None = None
        self.once: _OnceBinding[Compiled] = _OnceBinding(
            definition.row.__qualname__,
            lambda: self.value or _compile_graph(definition),
        )

    def get(self) -> Compiled:
        # The builder always returns Compiled; native _OnceBinding's None is for reentry.
        try:
            return cast("Compiled", self.once.get())
        except Exception as error:
            self.failure = error
            raise


@dataclass(frozen=True, eq=False)
class Definition:
    """One table definition, shared by every schema that includes its Fetched Model."""

    row: type[Record]
    state: Binding = field(init=False)
    targets: Mapping[str, _OnceBinding[Any]] = field(init=False)
    composites: tuple[tuple[Any, _OnceBinding[Any]], ...] = field(init=False)
    indexes: tuple[Any, ...] = field(init=False)
    checks: tuple[Any, ...] = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "state", Binding(self))
        object.__setattr__(
            self,
            "targets",
            MappingProxyType(
                {
                    name: _OnceBinding(
                        f"{self.row.__name__}.{name}", descriptor.declaration.target
                    )
                    for name, descriptor in self.row.fields.items()
                    if descriptor.declaration.target is not None
                }
            ),
        )
        object.__setattr__(
            self,
            "composites",
            tuple(
                (
                    constraint,
                    _OnceBinding(
                        "composite target",
                        constraint.references
                        if callable(constraint.references)
                        else lambda constraint=constraint: constraint.references,
                    ),
                )
                for constraint in getattr(self.row, "__foreign_keys__", ())
            ),
        )
        object.__setattr__(self, "indexes", tuple(getattr(self.row, "__indexes__", ())))
        object.__setattr__(self, "checks", tuple(getattr(self.row, "__checks__", ())))


def _definition(row: Any) -> Definition:
    if (
        not isinstance(row, type)
        or not issubclass(row, Record)
        or not issubclass(row, ReadRow)
        or row._definition is None
    ):
        raise ModelDeclarationError(
            "A Fetched Model from this declaration family is required"
        )
    return row._definition


def _compile_graph(root: Definition) -> Compiled:
    # A descriptor's native construction lease ends on success and every failure.
    with ExitStack() as bindings:
        return _compile_graph_bound(root, bindings)


def _compile_graph_bound(root: Definition, bindings: ExitStack) -> Compiled:
    """Resolve column storage before binding table constraints, then publish atomically.

    Table cycles are legal when their columns ultimately derive storage from a
    concrete declaration. A column-storage cycle has no such root and fails.
    Native ModelMeta still checks every physical constraint. Private native
    classes remain unpublished until that second phase and scaffold validation finish.
    """
    definitions: dict[type[Record], Definition] = {}
    targets: dict[type[Record], dict[str, Column[Any, Any]]] = {}
    composites: dict[type[Record], list[tuple[Any, tuple[Column[Any, Any], ...]]]] = {}
    namespace: Any = sqlite if root.row.backend == "sqlite" else mariadb

    def visit(definition: Definition) -> None:
        row = definition.row
        if definition.state.failure is not None:
            raise ModelDeclarationError(
                "Cannot consume a failed definition"
            ) from definition.state.failure
        if row in definitions:
            return
        if row.backend != root.row.backend:
            raise ModelDeclarationError("Foreign graph crosses Backend Families")
        definitions[row] = definition
        targets[row] = {}
        composites[row] = []
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
        for name, once in definition.targets.items():
            target = once.get()
            if not isinstance(target, Column):
                raise ModelDeclarationError("Foreign target must be a column")
            target_definition = _definition(target.owner)
            if target.name not in target_definition.row.fields:
                raise ModelDeclarationError("Foreign target column does not exist")
            annotation = next(
                get_annotations(base, format=Format.FORWARDREF)[name]
                for base in row.__mro__
                if name in get_annotations(base, format=Format.FORWARDREF)
            )
            origin = get_origin(annotation)
            if (
                not isinstance(origin, type)
                or not issubclass(origin, ForeignDefinition)
                or get_args(annotation)[-2] is not target.owner
            ):
                raise ModelDeclarationError("Foreign annotation and target disagree")
            targets[row][name] = target
            visit(target_definition)
        for constraint, once in definition.composites:
            members = tuple(
                _column_reference(member) for member in cast("Any", once.get())
            )
            if not members or any(not isinstance(member, Column) for member in members):
                raise ModelDeclarationError("Composite references must name columns")
            composites[row].append((constraint, members))
            for member in members:
                visit(_definition(member.owner))

    visit(root)
    columns: dict[tuple[type[Record], str], Any] = {}
    resolving: set[tuple[type[Record], str]] = set()

    def column(row: type[Record], name: str) -> Any:
        key = (row, name)
        if key in columns:
            return columns[key]
        if key in resolving:
            raise ModelDeclarationError(
                "Foreign storage derivation has no concrete root"
            )
        if name not in row.fields:
            raise ModelDeclarationError("Foreign target column does not exist")
        published = definitions[row].state.value
        if published is not None:
            columns[key] = getattr(published.native, name)
            return columns[key]
        resolving.add(key)
        declaration = row.fields[name].declaration
        if declaration.target is not None and declaration.enforced:
            target = targets[row][name]
            target_column = column(target.owner, target.name)
            native = namespace.ForeignKey(
                target_column,
                default=sqlite.PENDING_GENERATION
                if declaration.default is OMIT
                else declaration.default,
                nullable=declaration.nullable,
                primary_key=declaration.primary_key,
                unique=declaration.unique,
                index=declaration.index,
            )
            native.foreign_key_target = None
            native.decimal_precision = target_column.decimal_precision
            native.decimal_scale = target_column.decimal_scale
        else:
            if not declaration.storage:
                raise ModelDeclarationError(
                    "Typed-only references require explicit local storage"
                )
            native = declaration.native()
            native.primary_key = native.primary_key or declaration.primary_key
            native.unique = native.unique or declaration.unique
            native.index = native.index or declaration.index
        native = bindings.enter_context(row.fields[name].native_binding(row, native))
        columns[key] = native
        resolving.remove(key)
        return native

    models: dict[type[Record], Any] = {}
    for row, definition in definitions.items():
        published = definition.state.value
        if published is not None:
            models[row] = published.native
            continue
        attributes = {name: column(row, name) for name in row.fields}
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
                namespace.GenCol[logical] if generated else namespace.Col[logical]
            )

        def indexes(native: Any, definition: Definition = definition) -> list[Any]:
            return [
                namespace.Index(
                    *(
                        getattr(native, _local_name(definition.row, member))
                        for member in index.columns
                    ),
                    unique=index.unique,
                    name=index.name,
                    prefix_lengths=index.prefix_lengths,
                    where=None
                    if index.where is None
                    else index.where.expression(definition.row, native),
                )
                for index in definition.indexes
            ]

        def checks(native: Any, definition: Definition = definition) -> list[Any]:
            return [
                namespace.CheckConstraint(
                    check.expression(definition.row, native), name=check.name
                )
                for check in definition.checks
            ]

        models[row] = type(
            f"{row.__name__}Storage",
            (namespace.Model,),
            {
                "__module__": __name__,
                "__tablename__": row.table_name,
                "__annotations__": annotations,
                "__snekql_hints__": annotations,
                "__indexes__": classmethod(indexes),
                "__checks__": classmethod(checks),
                **attributes,
            },
        )
    for row, definition in definitions.items():
        if definition.state.value is not None:
            continue
        constraints: list[Any] = []
        for name, target in targets[row].items():
            declaration = row.fields[name].declaration
            if declaration.enforced:
                constraints.append(
                    namespace.ForeignKeyConstraint(
                        column(row, name),
                        references=(column(target.owner, target.name),),
                        on_update=declaration.on_update,
                        on_delete=declaration.on_delete,
                    )
                )
        for constraint, members in composites[row]:
            constraints.append(
                namespace.ForeignKeyConstraint(
                    *(
                        column(row, _local_name(row, member))
                        for member in constraint.columns
                    ),
                    references=tuple(
                        column(member.owner, member.name) for member in members
                    ),
                    on_update=constraint.on_update,
                    on_delete=constraint.on_delete,
                )
            )
        native = models[row]
        native.__snekql_foreign_keys__ = ModelMeta._bind_foreign_keys(
            native, {"__foreign_keys__": constraints}, native.__snekql_columns__
        )
    namespace.scaffold(list(models.values()))

    def closure(row: type[Record]) -> Mapping[type[Record], Any]:
        selected: dict[type[Record], Any] = {}
        seen: set[type[Record]] = set()

        def collect(current: type[Record]) -> None:
            if current in seen:
                return
            seen.add(current)
            for target in targets[current].values():
                collect(target.owner)
            for _, members in composites[current]:
                for member in members:
                    collect(member.owner)
            selected[current] = models[current]

        collect(row)
        return MappingProxyType(selected)

    if any(definition.state.failure is not None for definition in definitions.values()):
        raise ModelDeclarationError("Reentrant metadata use poisoned the graph")
    for row, definition in definitions.items():
        if definition.state.value is None:
            definition.state.value = Compiled(
                models[row], closure(row), MappingProxyType(targets[row])
            )
    return cast("Compiled", root.state.value)


class Schema:
    """A read-only selection of finalized definitions; it does not configure model classes."""

    def __init__(self, *rows: type[Record]) -> None:
        models: dict[type[Record], Any] = {}
        definitions = tuple(_definition(row) for row in rows)
        families = {definition.row.backend for definition in definitions}
        if len(families) != 1:
            raise ModelDeclarationError("Schema needs one nonempty Backend Family")
        namespace: Any = sqlite if families == {"sqlite"} else mariadb
        for definition in definitions:
            models.update(definition.state.get().graph)
        namespace.scaffold(list(models.values()))
        self.namespace: Any
        self.models: Mapping[type[Record], Any]
        object.__setattr__(self, "namespace", namespace)
        object.__setattr__(self, "models", MappingProxyType(models))

    def __setattr__(self, name: str, value: object) -> None:
        raise sqlite.FrozenModelError("Schema selections are immutable")

    def __delattr__(self, name: str) -> None:
        raise sqlite.FrozenModelError("Schema selections are immutable")

    def native(self, row: type[Record]) -> Any:
        """Erased native bridge, retained only for adapter and backend controls."""
        return self.models[row]

    def scaffold(self) -> str:
        return cast("str", self.namespace.scaffold(list(self.models.values())))


class Transaction:
    """Execute SQLite queries using the same native transaction as the storage study."""

    def __init__(self, native: sqlite.Transaction, schema: Schema) -> None:
        self.native: sqlite.Transaction = native
        self.schema: Schema = schema

    @overload
    async def execute[Row: StorageRecord](self, command: Insert[Row]) -> Row: ...
    @overload
    async def execute[Row: ReadRow](self, command: WriteCount[Row, Ready]) -> int: ...
    async def execute(self, command: Any) -> Any:
        if isinstance(command, WriteCount):
            return await self.native.execute(command.native)
        native = self.schema.native(command.row_type)
        fetched = await self.native.execute(
            sqlite.insert(native(**command.values)).returning()
        )
        return _materialize(command.row_type, fetched)

    async def fetch_all[Row: ReadRow, Result](
        self, query: Query[Row, Ready, Result]
    ) -> list[Result]:
        native: Any = self.native
        return [query.decode(row) for row in await native.fetch_all(query.native)]

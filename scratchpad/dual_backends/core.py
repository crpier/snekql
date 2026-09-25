"""Throwaway backend-owned descriptors over the shared dual declaration finalizer."""

from annotationlib import Format, get_annotations
from collections.abc import Callable, Mapping
from dataclasses import dataclass, fields, replace
from types import MappingProxyType
from typing import Any, Generic, Literal, Protocol, TypeVar, cast, get_origin, overload

from snekql import mariadb, sqlite
from snekql._compiled import CompiledQuery
from snekql.query import _select_join

from scratchpad.dual_finalization.interface import Record, Schema
from scratchpad.dual_storage.interface import (
    Assignment as OriginalAssignment,
)
from scratchpad.dual_storage.interface import (
    Column as OriginalColumn,
)
from scratchpad.dual_storage.interface import (
    Condition as OriginalCondition,
)
from scratchpad.dual_storage.interface import (
    Declaration,
    ReadRow,
    Ready,
    Unscoped,
    stored,
)
from scratchpad.dual_storage.interface import (
    Field as OriginalField,
)
from scratchpad.dual_storage.interface import (
    ForeignColumn as OriginalForeignColumn,
)
from scratchpad.dual_storage.interface import (
    ForeignField as OriginalForeignField,
)
from scratchpad.dual_storage.interface import (
    foreign as original_foreign,
)

Family = TypeVar("Family")
Owner = TypeVar("Owner")
Value = TypeVar("Value")


@dataclass(frozen=True)
class BackendDeclaration(Declaration):
    family: Literal["sqlite", "mariadb"] = "sqlite"


def capture(
    family: Literal["sqlite", "mariadb"],
    native: Any,
    *,
    default: Any = ...,
    default_factory: Any = ...,
) -> BackendDeclaration:
    original = stored(
        native, default=default, default_factory=default_factory
    ).declaration
    return BackendDeclaration(
        **{
            member.name: getattr(original, member.name)
            for member in fields(Declaration)
        },
        family=family,
    )


@dataclass(frozen=True)
class Column(OriginalColumn[Owner, Value], Generic[Family, Owner, Value]):
    family: Family

    def eq(self, value: Value) -> Condition[Family, Owner]:
        return Condition(self.native.eq(value), self.family)

    def to(
        self, value: Value | type[sqlite.CurrentTimestamp]
    ) -> ConflictAssignment[Family, Owner]:
        return ConflictAssignment(self.name, self.owner, value, self.family)

    def to_inserted(self) -> ConflictAssignment[Family, Owner]:
        """Use this column's attempted insert value in a conflict update."""
        return ConflictAssignment(
            self.name, self.owner, None, self.family, attempted=True
        )

    def __selection__(self) -> Selection[Family, Owner, Value]:
        return Selection(self.family, self.owner, self.native)


class Field(OriginalField[Value], Generic[Family, Value]):
    @overload
    def __get__[Access](
        self, instance: None, owner: type[Access]
    ) -> Column[Family, Access, Value]: ...
    @overload
    def __get__(self, instance: object, owner: type[object]) -> Value: ...
    def __get__[Access](
        self, instance: object, owner: type[Access]
    ) -> Column[Family, Access, Value] | Value:
        if instance is None:
            declaration = cast("BackendDeclaration", self.declaration)
            return Column(owner, self.name, cast("Family", declaration.family))
        return super().__get__(instance, owner)


class Input(Generic[Family], Record):
    """The namespace fixes the backend; no lifecycle parameter appears on application rows."""

    def __init_subclass__(
        cls, *, backend: Literal["sqlite", "mariadb"] | None = None
    ) -> None:
        super().__init_subclass__(backend=backend)
        for name, descriptor in cls.fields.items():
            declaration = descriptor.declaration
            if (
                not isinstance(declaration, BackendDeclaration)
                or declaration.family != cls.backend
            ):
                raise sqlite.ModelDeclarationError(
                    "Column declaration crosses Backend Families"
                )
            for base in cls.__mro__:
                annotation = get_annotations(base, format=Format.FORWARDREF).get(name)
                if annotation is not None:
                    if (
                        getattr(get_origin(annotation), "__family__", None)
                        != cls.backend
                    ):
                        raise sqlite.ModelDeclarationError(
                            "Column annotation crosses Backend Families"
                        )
                    break
        if issubclass(cls, ReadRow):
            method = getattr(cls, "__table_source__", None)
            if not callable(method):
                raise sqlite.ModelDeclarationError(
                    "Fetched marker must supply a source witness"
                )
            # Namespace markers implement this fixed zero-argument classmethod.
            source = cast("Callable[[], Source[Any, Any]]", method)()
            if (
                not isinstance(source, Source)
                or source.family != cls.backend
                or source.model is not cls
            ):
                raise sqlite.ModelDeclarationError(
                    "Fetched marker belongs to another Backend Family"
                )


@dataclass(frozen=True)
class Source(Generic[Family, Owner]):
    family: Family
    model: type[Owner]

    @property
    def native(self) -> Any:
        if (
            not isinstance(self.model, type)
            or not issubclass(self.model, Record)
            or not issubclass(self.model, ReadRow)
            or self.model.backend != self.family
        ):
            raise sqlite.ModelDeclarationError(
                "Source requires a Fetched Model from its Backend Family"
            )
        return self.model.binding


class Table(Protocol[Family, Owner]):
    @classmethod
    def __table_source__(cls) -> Source[Family, Owner]: ...


Scope_co = TypeVar("Scope_co", covariant=True)
State = TypeVar("State")
Result = TypeVar("Result")


@dataclass(frozen=True)
class Condition(OriginalCondition[Scope_co], Generic[Family, Scope_co]):
    family: Family

    def __and__[Other](
        self, other: OriginalCondition[Other]
    ) -> Condition[Family, Scope_co | Other]:
        if not isinstance(other, Condition) or self.family != other.family:
            raise sqlite.QueryConstructionError("Predicate Backend Families differ")
        return cast(
            "Condition[Family, Scope_co | Other]",
            Condition(self.native & other.native, self.family),
        )


@dataclass(frozen=True)
class Selection(Generic[Family, Owner, Value]):
    family: Family
    owner: type[Owner]
    native: Any


class Selectable(Protocol[Family, Owner, Value]):
    def __selection__(self) -> Selection[Family, Owner, Value]: ...


@dataclass(frozen=True)
class Scalar(Generic[Family, Owner, Value]):
    selection: Selection[Family, Owner, Value]

    def __selection__(self) -> Selection[Family, Owner, Value]:
        return self.selection

    def eq(self, value: Value) -> Condition[Family, Owner]:
        return Condition(self.selection.native.eq(value), self.selection.family)


@dataclass(frozen=True)
class JsonColumn(Column[Family, Owner, Value], Generic[Family, Owner, Value]):
    def json_extract_int(self, path: str) -> Scalar[Family, Owner, int | None]:
        return Scalar(
            Selection(self.family, self.owner, self.native.json_extract_int(path))
        )


class JsonField(Field[Family, Value], Generic[Family, Value]):
    @overload
    def __get__[Access](
        self, instance: None, owner: type[Access]
    ) -> JsonColumn[Family, Access, Value]: ...
    @overload
    def __get__(self, instance: object, owner: type[object]) -> Value: ...
    def __get__[Access](
        self, instance: object, owner: type[Access]
    ) -> JsonColumn[Family, Access, Value] | Value:
        if instance is None:
            declaration = cast("BackendDeclaration", self.declaration)
            return JsonColumn(owner, self.name, cast("Family", declaration.family))
        return super().__get__(instance, owner)


@dataclass(frozen=True)
class Query(Generic[Family, Owner, State, Result]):
    family: Family
    native: Any
    decode: Callable[[Any], Result]

    def all(self) -> Query[Family, Owner, Ready, Result]:
        return Query(self.family, self.native.all(), self.decode)

    def where(
        self, condition: Condition[Family, Owner]
    ) -> Query[Family, Owner, Ready, Result]:
        if self.family != condition.family:
            raise sqlite.QueryConstructionError(
                "Predicate belongs to another Backend Family"
            )
        return Query(self.family, self.native.where(condition.native), self.decode)

    def join[Other](
        self, other: type[Table[Family, Other]], *, on: Condition[Family, Owner | Other]
    ) -> Query[Family, Owner | Other, State, Result]:
        source = other.__table_source__()
        if self.family != source.family or self.family != on.family:
            raise sqlite.QueryConstructionError("Join crosses Backend Families")
        native = type(self.native)(
            _select_join(
                self.native.state, source.native, on.native, "INNER", project=True
            )
        )
        return cast(
            "Query[Family, Owner | Other, State, Result]",
            Query(self.family, native, self.decode),
        )

    def __plan__(self: Query[Family, Owner, Ready, Result]) -> Plan[Family, Result]:
        return Plan(self.family, self.native, self.decode)

    def compile(self: Query[Family, Owner, Ready, Result]) -> CompiledQuery:
        return cast("CompiledQuery", self.native.compile())


class Namespace(Generic[Family]):
    def __init__(self, family: Family, native: Any) -> None:
        self.family: Family = family
        self.native: Any = native

    def scaffold(self, *sources: type[Table[Family, Any]]) -> str:
        rows: list[Any] = []
        for source in sources:
            if (
                not isinstance(source, type)
                or not issubclass(source, Record)
                or not issubclass(source, ReadRow)
            ):
                raise sqlite.ModelDeclarationError(
                    "Scaffold requires Fetched Model classes"
                )
            table = source.__table_source__()
            if table.family != self.family:
                raise sqlite.ModelDeclarationError("Scaffold crosses Backend Families")
            rows.append(table.model)
        return Schema(*rows).scaffold()

    def insert_using[**Parameters](
        self, factory: Callable[Parameters, Input[Family]]
    ) -> InsertUsing[Family, Parameters]:
        return InsertUsing(self.family, factory)

    @overload
    def select[Row](
        self, source: type[Table[Family, Row]]
    ) -> Query[Family, Row, Unscoped, Row]: ...
    @overload
    def select[Row: ReadRow, Value](
        self, source: Selectable[Family, Row, Value]
    ) -> Query[Family, Row, Unscoped, Value]: ...
    def select(self, source: Any) -> Any:
        if isinstance(source, type):
            if not issubclass(source, Record) or not issubclass(source, ReadRow):
                raise sqlite.ModelDeclarationError("Select a Fetched Model class")
            table = source.__table_source__()
            if table.family != self.family:
                raise sqlite.QueryConstructionError("SELECT crosses Backend Families")
            model = table.native
            names = tuple(source.fields)

            def decode(value: Any) -> Any:
                values = value if len(names) > 1 else (value,)
                return source(**dict(zip(names, values, strict=True)))

            # Explicit projections retain their shape when native joins add sources.
            return Query(
                self.family,
                self.native.select(*(getattr(model, name) for name in names)),
                decode,
            )
        if isinstance(source, Record):
            raise sqlite.QueryConstructionError("Select a model class, not a value")
        selection = source.__selection__()
        if selection.family != self.family:
            raise sqlite.QueryConstructionError("Projection crosses Backend Families")
        return Query(
            self.family, self.native.select(selection.native), lambda value: value
        )


Target = TypeVar("Target", bound=ReadRow)


@dataclass(frozen=True)
class ForeignColumn(
    OriginalForeignColumn[Owner, Target, Value],
    Column[Family, Owner, Value],
    Generic[Family, Owner, Target, Value],
):
    @overload
    def references[NonNull](
        self: ForeignColumn[Family, Owner, Target, NonNull | None],
        target: OriginalColumn[Target, NonNull],
    ) -> Condition[Family, Owner | Target]: ...
    @overload
    def references(
        self, target: OriginalColumn[Target, Value]
    ) -> Condition[Family, Owner | Target]: ...
    def references(self, target: Any) -> Condition[Family, Owner | Target]:
        native = super().references(target)
        return cast(
            "Condition[Family, Owner | Target]", Condition(native.native, self.family)
        )


class ForeignField(OriginalForeignField[Target, Value], Generic[Family, Target, Value]):
    @overload
    def __get__[Access](
        self, instance: None, owner: type[Access]
    ) -> ForeignColumn[Family, Access, Target, Value]: ...
    @overload
    def __get__(self, instance: object, owner: type[object]) -> Value: ...
    def __get__[Access](
        self, instance: object, owner: type[Access]
    ) -> ForeignColumn[Family, Access, Target, Value] | Value:
        if instance is None:
            declaration = cast("BackendDeclaration", self.declaration)
            return ForeignColumn(owner, self.name, cast("Family", declaration.family))
        return super().__get__(instance, owner)


def foreign_declaration(
    family: Literal["sqlite", "mariadb"],
    target: Any,
    *,
    default: Any = ...,
    on_update: Any = None,
    on_delete: Any = None,
    primary_key: bool = False,
) -> BackendDeclaration:
    def resolve() -> Any:
        column = target() if callable(target) else target
        if not isinstance(column, Column) or column.family != family:
            raise sqlite.ModelDeclarationError(
                "Foreign target crosses Backend Families"
            )
        return column

    original = original_foreign(
        resolve,
        default=default,
        on_update=on_update,
        on_delete=on_delete,
        primary_key=primary_key,
    ).declaration
    return BackendDeclaration(
        **{
            member.name: getattr(original, member.name)
            for member in fields(Declaration)
        },
        family=family,
    )


@dataclass(frozen=True)
class ConflictAssignment(OriginalAssignment[Owner], Generic[Family, Owner]):
    family: Family
    attempted: bool = False

    def lower(self, model: Any) -> Any:
        column = getattr(model, self.name)
        return column.to_inserted() if self.attempted else column.to(self.value)


@dataclass(frozen=True, init=False)
class DoUpdate(Generic[Family, Owner]):
    assignments: tuple[ConflictAssignment[Family, Owner], ...]

    def __init__(
        self,
        first: ConflictAssignment[Family, Owner],
        /,
        *rest: ConflictAssignment[Family, Owner],
    ) -> None:
        assignments = (first, *rest)
        if any(
            not isinstance(assignment, ConflictAssignment) for assignment in assignments
        ):
            raise sqlite.QueryConstructionError(
                "Conflict updates require column assignments"
            )
        if any(
            assignment.family != first.family or assignment.owner is not first.owner
            for assignment in rest
        ):
            raise sqlite.QueryConstructionError(
                "Conflict assignments must share a model and Backend Family"
            )
        object.__setattr__(self, "assignments", assignments)


@dataclass(frozen=True)
class Conflict(Generic[Family, Owner]):
    targets: tuple[Column[Family, Owner, Any], ...]
    action: DoUpdate[Family, Owner] | type[sqlite.DoNothing]


@dataclass(frozen=True)
class Returning(Generic[Family, Owner]):
    command: Insert[Family, Owner]

    def compile(self) -> CompiledQuery:
        return cast("CompiledQuery", self.command._query().returning().compile())


@dataclass(frozen=True)
class Insert(Generic[Family, Owner]):
    source: Source[Family, Owner]
    values: Mapping[str, object]
    conflict: Conflict[Family, Owner] | None = None

    @overload
    def on_conflict(
        self,
        first: Column[Family, Owner, Any],
        /,
        *rest: Column[Family, Owner, Any],
        action: DoUpdate[Family, Owner],
    ) -> Insert[Family, Owner]: ...
    @overload
    def on_conflict(
        self,
        first: Column[Family, Owner, Any],
        /,
        *rest: Column[Family, Owner, Any],
        action: type[sqlite.DoNothing],
    ) -> IgnoredInsert[Family, Owner]: ...
    def on_conflict(
        self,
        first: Column[Family, Owner, Any],
        /,
        *rest: Column[Family, Owner, Any],
        action: DoUpdate[Family, Owner] | type[sqlite.DoNothing],
    ) -> Insert[Family, Owner] | IgnoredInsert[Family, Owner]:
        targets = (first, *rest)
        if any(
            not isinstance(target, Column)
            or target.owner is not self.source.model
            or target.family != self.source.family
            for target in targets
        ):
            raise sqlite.QueryConstructionError(
                "Conflict targets must belong to the inserted model and Backend Family"
            )
        if action is sqlite.DoNothing:
            return IgnoredInsert(replace(self, conflict=Conflict(targets, action)))
        if not isinstance(action, DoUpdate):
            raise sqlite.QueryConstructionError(
                "Conflict action must be DoUpdate or DoNothing"
            )
        if any(
            assignment.owner is not self.source.model
            or assignment.family != self.source.family
            for assignment in action.assignments
        ):
            raise sqlite.QueryConstructionError(
                "Conflict assignments must belong to the inserted model and Backend Family"
            )
        return replace(self, conflict=Conflict(targets, action))

    def returning(self) -> Returning[Family, Owner]:
        return Returning(self)

    def compile(self) -> CompiledQuery:
        return cast("CompiledQuery", self._query().compile())

    def _query(self) -> Any:
        """Lower through native constructors so conflict SQL and codecs remain native."""
        namespace: Any = sqlite if self.source.family == "sqlite" else mariadb
        model = self.source.native
        query = namespace.insert(model(**self.values))
        if self.conflict is not None:
            conflict = self.conflict
            action = (
                namespace.DoUpdate(
                    *(
                        assignment.lower(model)
                        for assignment in conflict.action.assignments
                    )
                )
                if isinstance(conflict.action, DoUpdate)
                else namespace.DoNothing
            )
            query = query.on_conflict(
                *(getattr(model, target.name) for target in conflict.targets),
                action=action,
            )
        return query


@dataclass(frozen=True)
class IgnoredInsert(Generic[Family, Owner]):
    """No returning() promise: a skipped insert produces no row."""

    _command: Insert[Family, Owner]

    def compile(self) -> CompiledQuery:
        return self._command.compile()


class BoundInsert[Family, **Parameters, Row]:
    def __init__(
        self,
        family: Family,
        factory: Callable[Parameters, Input[Family]],
        row: type[Table[Family, Row]],
    ) -> None:
        self.family: Family = family
        self.factory: Callable[Parameters, Input[Family]] = factory
        self.row: type[Table[Family, Row]] = row

    def __call__(
        self, *args: Parameters.args, **kwargs: Parameters.kwargs
    ) -> Insert[Family, Row]:
        source = self.row.__table_source__()
        if source.family != self.family:
            raise sqlite.ModelDeclarationError(
                "Insert factory belongs to another Backend Family"
            )
        pending = self.factory(*args, **kwargs)
        model: Any = source.model
        if (
            not isinstance(pending, Record)
            or pending.backend != self.family
            or not issubclass(model, type(pending))
            or set(pending.fields) != set(model.fields)
        ):
            raise sqlite.ModelDeclarationError(
                "Insert factory must use the matching complete input contract"
            )
        return Insert(
            source, MappingProxyType(model._prepare(pending.values, for_insert=True))
        )


class InsertUsing[Family, **Parameters]:
    def __init__(
        self, family: Family, factory: Callable[Parameters, Input[Family]]
    ) -> None:
        self.family: Family = family
        self.factory: Callable[Parameters, Input[Family]] = factory

    def __get__[Row](
        self, instance: object, owner: type[Table[Family, Row]]
    ) -> BoundInsert[Family, Parameters, Row]:
        del instance
        return BoundInsert(self.family, self.factory, owner)


class Transaction(Generic[Family]):
    def __init__(self, family: Family, native: Any, namespace: Any) -> None:
        if native.runtime.backend_family != family:
            raise sqlite.QueryConstructionError(
                "Transaction belongs to another Backend Family"
            )
        self.family: Family = family
        self.native: Any = native
        self.namespace: Any = namespace

    @overload
    async def execute[Row](
        self, command: Insert[Family, Row] | IgnoredInsert[Family, Row]
    ) -> None: ...
    @overload
    async def execute[Row](self, command: Returning[Family, Row]) -> Row: ...
    async def execute(self, command: Any) -> Any:
        returning = isinstance(command, Returning)
        insertion = (
            command.command
            if returning
            else command._command
            if isinstance(command, IgnoredInsert)
            else command
        )
        if insertion.source.family != self.family:
            raise sqlite.QueryConstructionError("Write crosses Backend Families")
        query = insertion._query()
        if not returning:
            await self.native.execute(query)
            return None
        row = await self.native.execute(query.returning())
        output = insertion.source.model
        return output(**{name: getattr(row, name) for name in output.fields})

    async def fetch_all[Result](self, query: Select[Family, Result]) -> list[Result]:
        plan = query.__plan__()
        if plan.family != self.family:
            raise sqlite.QueryConstructionError("Read crosses Backend Families")
        return [plan.decode(row) for row in await self.native.fetch_all(plan.native)]


@dataclass(frozen=True)
class Plan(Generic[Family, Result]):
    family: Family
    native: Any
    decode: Callable[[Any], Result]


class Select(Protocol[Family, Result]):
    """Result-only, ready helper contract. Scope-changing query methods are not exposed."""

    def __plan__(self) -> Plan[Family, Result]: ...

    def compile(self) -> CompiledQuery: ...

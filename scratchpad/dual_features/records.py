"""Throwaway model definitions with a minimal SQLite INSERT RETURNING runtime.

Not a production model implementation. The query follow-up adds field-local
FK declarations and deferred targets. Complete schemas, backend families and
migrations remain outside this experiment.
"""

# Invariant column/assignment owners prevent inference from widening ownership.
# ruff: noqa: UP046

from annotationlib import Format, get_annotations
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from types import MappingProxyType, UnionType
from typing import (
    TYPE_CHECKING,
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

from aiosqlite import Connection
from pydantic import ConfigDict, TypeAdapter, ValidationError

if TYPE_CHECKING:
    from scratchpad.dual_features.models import ReadRow
    from scratchpad.dual_features.runtime import Expression, Predicate
    from scratchpad.dual_queries.interface import Comparable, Comparison, Item
    from scratchpad.dual_queries.relationships import Referenced, ReferenceTarget


_Owner = TypeVar("_Owner")
_Value = TypeVar("_Value")
_Target = TypeVar("_Target", bound="ReadRow")
type ReferentialAction = Literal[
    "CASCADE", "RESTRICT", "NO ACTION", "SET NULL", "SET DEFAULT"
]


class ModelError(Exception):
    """The prototype cannot construct a valid input or read row."""


class Omitted:
    """An input value that the database must supply, never SQL NULL."""


OMIT = Omitted()


class _Missing:
    """No constructor default was declared."""


_MISSING = _Missing()


@dataclass(frozen=True)
class Assignment(Generic[_Owner]):
    name: str
    owner: type[_Owner]
    value: object


@dataclass(frozen=True)
class Column(Generic[_Owner, _Value]):
    name: str
    owner: type[_Owner]

    def __reference__[Read: ReadRow](
        self: Column[Read, _Value],
    ) -> ReferenceTarget[Read, Read, _Value]:
        """Keep the original model/column behind a direct reference target."""
        from scratchpad.dual_queries.relationships import ReferenceTarget

        expression = self.__scalar__()
        return ReferenceTarget(self, expression, expression.decode)

    def to(self, value: _Value) -> Assignment[_Owner]:
        return Assignment(self.name, self.owner, value)

    def eq[Read: ReadRow](self: Column[Read, _Value], value: _Value) -> Predicate[Read]:
        """Compare a read-model column directly, e.g. Account.name.eq('Ada')."""
        return self.__scalar__().eq(value)

    def __comparison__[Read: ReadRow](
        self: Column[Read, _Value],
    ) -> Comparison[Read, _Value]:
        """Keep scope invariant while allowing read-only nullable comparisons."""
        from scratchpad.dual_queries.interface import Comparison

        expression = self.__scalar__()
        return Comparison(expression, expression.decode)

    def eq_col[Read: ReadRow, Other](
        self: Column[Read, _Value], other: Comparable[Other, _Value | None]
    ) -> Predicate[Read | Other]:
        """Compare compatible logical domains and retain both source identities."""
        from scratchpad.dual_features.runtime import Predicate

        left, right = self.__scalar__(), other.__comparison__().expression
        return Predicate[Read | Other](
            f"{left.sql} = {right.sql}", left.owners | right.owners
        )

    def like[Read: ReadRow](
        self: Column[Read, str] | Column[Read, str | None], pattern: str
    ) -> Predicate[Read]:
        """Match text with ordinary SQL NULL behavior."""
        return self.__scalar__().like(pattern)

    def __selection__[Read: ReadRow](self: Column[Read, _Value]) -> Item[Read, _Value]:
        """Preserve the read owner and logical value at the query interface."""
        from scratchpad.dual_features.runtime import (
            Selection,
            source,
        )
        from scratchpad.dual_queries.interface import Item

        expression = self.__scalar__()
        return Item(
            source(self.owner),
            Selection(
                (expression.sql,),
                expression.owners,
                lambda raw: expression.decode(raw[0]),
            ),
        )

    def __scalar__[Read: ReadRow](
        self: Column[Read, _Value],
    ) -> Expression[Read, _Value]:
        """Reuse codec handling, rejecting input classes even after type erasure."""
        from scratchpad.dual_features.models import ReadRow
        from scratchpad.dual_features.runtime import source

        if not issubclass(self.owner, ReadRow):
            message = "Only read models supply SQL columns"
            raise ModelError(message)
        return source(self.owner).column(self)


@dataclass(frozen=True)
class ForeignTarget(Generic[_Target]):
    """Deferred target plus physical FK policy, shared by input/read declarations."""

    resolve: Callable[[], Column[_Target, Any]]
    enforced: bool = True
    on_update: ReferentialAction = "NO ACTION"


@dataclass(frozen=True)
class ForeignColumn(Column[_Owner, _Value], Generic[_Owner, _Target, _Value]):
    """A column retaining its declared target as well as its read owner."""

    declaration: ForeignTarget[_Target]

    def references[Read: ReadRow, Other](
        self: ForeignColumn[Read, _Target, _Value],
        target: Referenced[Other, _Target, _Value | None],
    ) -> Predicate[Read | Other]:
        """Join the declared columns, e.g. Entry.account_id.references(Account.id)."""
        from scratchpad.dual_queries.relationships import reference_predicate

        return reference_predicate(self, self.__scalar__(), target.__reference__())


class Field[Value]:
    """Class access is a typed column; instance access is a validated value."""

    def __init__(
        self,
        *,
        default: object = _MISSING,
        default_factory: Callable[[], object] | None = None,
        inherit: bool = False,
    ) -> None:
        self.default: object = default
        self.default_factory: Callable[[], object] | None = default_factory
        self.inherit: bool = inherit
        self.generated: bool = isinstance(default, Omitted)
        self.name: str = ""

    def __set_name__(self, owner: type[object], name: str) -> None:
        del owner
        self.name = name

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
            return Column[Owner, Value](self.name, owner)
        if not isinstance(instance, Record):
            message = "Field accessed on an unrelated object"
            raise ModelError(message)
        # Record construction validates each logical type before storing it.
        return cast("Value", instance.values[self.name])

    def __set__(self, instance: object, value: Value) -> None:
        del instance, value
        message = "Model values are immutable"
        raise ModelError(message)


class ForeignField[Target: ReadRow, Value](Field[Value]):
    """A scalar field with a target-aware class column, never a loaded relation.

    `account_id: ForeignField[Account, int | None] = foreign(Account.id, default=None)`
    A forward/self target uses `foreign(lambda: Account.id, default=None)`.
    """

    def __init__(
        self, declaration: ForeignTarget[Target], *, default: object = _MISSING
    ) -> None:
        super().__init__(default=default)
        self.declaration: ForeignTarget[Target] = declaration

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
            return ForeignColumn[Owner, Target, Value](
                self.name, owner, self.declaration
            )
        return super().__get__(instance, owner)


@overload
def foreign[Target: ReadRow, Value](
    target: Column[Target, Value] | Callable[[], Column[Target, Value]],
    *,
    default: None,
    enforced: bool = True,
    on_update: ReferentialAction = "NO ACTION",
) -> ForeignField[Target, Value | None]: ...
@overload
def foreign[Target: ReadRow, Value](
    target: Column[Target, Value] | Callable[[], Column[Target, Value]],
    *,
    default: Value | _Missing = _MISSING,
    enforced: bool = True,
    on_update: ReferentialAction = "NO ACTION",
) -> ForeignField[Target, Value]: ...
def foreign[Target: ReadRow](
    target: Column[Target, Any] | Callable[[], Column[Target, Any]],
    *,
    default: object = _MISSING,
    enforced: bool = True,
    on_update: ReferentialAction = "NO ACTION",
) -> ForeignField[Target, Any]:
    """Declare a direct or deferred FK target in the same place as its scalar field."""
    if on_update not in {"CASCADE", "RESTRICT", "NO ACTION", "SET NULL", "SET DEFAULT"}:
        message = "Unsupported foreign-key ON UPDATE action"
        raise ModelError(message)
    resolve: Callable[[], Column[Target, Any]]
    if isinstance(target, Column):

        def resolve() -> Column[Target, Any]:
            return target
    else:
        resolve = target
    return ForeignField(ForeignTarget(resolve, enforced, on_update), default=default)


class Generated[Value](Field[Value]):
    """Keep scalar reads while admitting an explicit omission as constructor input."""

    def __set__(self, instance: object, value: Value | Omitted) -> None:
        del instance, value
        message = "Model values are immutable"
        raise ModelError(message)


def generated[Value](*, default: Omitted) -> Generated[Value]:
    """The explicit default keyword also tells ty that this field is optional."""
    return Generated(default=default)


def field[Value](
    *,
    default: Value | Omitted | _Missing = _MISSING,
    default_factory: Callable[[], Value] | None = None,
) -> Field[Value]:
    """Declare an input/read column and optional client or server default."""
    return Field(default=default, default_factory=default_factory)


def required[Value]() -> Field[Value]:
    """Refine an inherited generated field to its required materialized type."""
    return Field(inherit=True)


@dataclass(frozen=True)
class _Spec:
    adapter: TypeAdapter[object]
    default: object
    default_factory: Callable[[], object] | None
    generated: bool
    logical_type: object


@dataclass_transform(
    field_specifiers=(field, required, generated, foreign),
    kw_only_default=True,
    frozen_default=True,
)
class Record:
    """Shared immutable model mechanics, without choosing an insert constructor."""

    specs: ClassVar[Mapping[str, _Spec]] = MappingProxyType[str, _Spec]({})

    def __init__(self, **values: object) -> None:
        object.__setattr__(self, "_values", MappingProxyType(self._prepare(values)))

    def __init_subclass__(cls) -> None:
        inherited: dict[str, _Spec] = {}
        for base in reversed(cls.__mro__[1:]):
            if issubclass(base, Record):
                inherited.update(base.specs)
        # Resolve logical value annotations now, but permit relationship targets
        # to refer to read classes that have not been declared yet.
        for name, annotation in get_annotations(cls, format=Format.FORWARDREF).items():
            origin = get_origin(annotation)
            if not isinstance(origin, type) or not issubclass(origin, Field):
                continue
            descriptor = vars(cls).get(name)
            if not isinstance(descriptor, Field):
                continue
            logical_type = get_args(annotation)[-1]
            generated = descriptor.generated
            if descriptor.inherit:
                if name not in inherited:
                    message = f"Cannot refine undeclared field {name!r}"
                    raise ModelError(message)
                original = inherited[name]
                original_members = (
                    get_args(original.logical_type)
                    if get_origin(original.logical_type) is UnionType
                    else (original.logical_type,)
                )
                refined_members = (
                    get_args(logical_type)
                    if get_origin(logical_type) is UnionType
                    else (logical_type,)
                )
                expected = tuple(
                    member for member in original_members if member is not Omitted
                )
                if set(refined_members) != set(expected):
                    message = f"Refinement of {name!r} must only remove Omitted"
                    raise ModelError(message)
                generated = original.generated
            inherited[name] = _Spec(
                adapter=TypeAdapter(
                    logical_type, config=ConfigDict(arbitrary_types_allowed=True)
                ),
                default=descriptor.default,
                default_factory=descriptor.default_factory,
                generated=generated,
                logical_type=logical_type,
            )
        cls.specs = MappingProxyType(inherited)

    def __setattr__(self, name: str, value: object) -> None:
        del name, value
        message = "Model values are immutable"
        raise ModelError(message)

    @property
    def values(self) -> Mapping[str, object]:
        """The prototype's validated storage, not a mutable public row mapping."""
        return cast("Mapping[str, object]", object.__getattribute__(self, "_values"))

    @classmethod
    def _prepare(
        cls, provided: Mapping[str, object], *, for_insert: bool = False
    ) -> dict[str, object]:
        unknown = provided.keys() - cls.specs.keys()
        if unknown:
            message = f"Unknown fields: {sorted(unknown)}"
            raise ModelError(message)
        prepared: dict[str, object] = {}
        for name, spec in cls.specs.items():
            if name in provided:
                value = provided[name]
            elif spec.default_factory is not None:
                value = spec.default_factory()
            else:
                value = spec.default
            if (
                for_insert
                and spec.generated
                and (isinstance(value, (Omitted, _Missing)))
            ):
                continue
            if isinstance(value, _Missing):
                message = f"Missing required field {name!r}"
                raise ModelError(message)
            try:
                prepared[name] = spec.adapter.validate_python(value, strict=True)
            except ValidationError as error:
                message = f"Invalid value for {name!r}"
                raise ModelError(message) from error
        return prepared


class Model(Record):
    """A single row class whose constructor signature also describes insert input."""

    @classmethod
    def create[**Parameters, Row: Record](
        cls: Callable[Parameters, Row],
        *args: Parameters.args,
        **kwargs: Parameters.kwargs,
    ) -> Insert[Row]:
        if args or not isinstance(cls, type) or not issubclass(cls, Record):
            message = "Expected a keyword-only model constructor"
            raise ModelError(message)
        # The guard establishes that the captured constructor is a model class.
        # ty loses its Callable return coordinate when narrowing with issubclass.
        row_type = cast("type[Row]", cls)
        return Insert(row_type, MappingProxyType(cls._prepare(kwargs, for_insert=True)))


@dataclass(frozen=True)
class Insert[Row: Record]:
    """Already-validated input values plus their precise materialized row type."""

    row_type: type[Row]
    values: Mapping[str, object]

    def with_(self, assignment: Assignment[Row]) -> Insert[Row]:
        if assignment.owner is not self.row_type:
            message = "Assignment belongs to a different model"
            raise ModelError(message)
        values = {**self.values, assignment.name: assignment.value}
        return Insert(
            self.row_type,
            MappingProxyType(self.row_type._prepare(values, for_insert=True)),  # noqa: SLF001
        )

    async def execute(self, connection: Connection, *, table: str) -> Row:
        """Use raw SQLite RETURNING to exercise real model materialization."""
        table_sql = '"' + table.replace('"', '""') + '"'
        column_sql = ['"' + name.replace('"', '""') + '"' for name in self.values]
        returning = ", ".join(
            '"' + name.replace('"', '""') + '"' for name in self.row_type.specs
        )
        if column_sql:
            placeholders = ", ".join("?" for _ in column_sql)
            sql = (
                f"INSERT INTO {table_sql} ({', '.join(column_sql)}) "  # noqa: S608 - identifiers quoted; values bound
                f"VALUES ({placeholders}) RETURNING {returning}"
            )
        else:
            sql = f"INSERT INTO {table_sql} DEFAULT VALUES RETURNING {returning}"  # noqa: S608
        async with connection.execute(sql, tuple(self.values.values())) as cursor:
            raw_row = await cursor.fetchone()
        if raw_row is None:
            message = "INSERT RETURNING produced no row"
            raise ModelError(message)
        return self.row_type(**dict(zip(self.row_type.specs, raw_row, strict=True)))


class BoundInsert[**Parameters, Input: Record, Row: Record]:
    def __init__(
        self, input_factory: Callable[Parameters, Input], row_type: type[Row]
    ) -> None:
        self.input_factory: Callable[Parameters, Input] = input_factory
        self.row_type: type[Row] = row_type

    def __call__(
        self, *args: Parameters.args, **kwargs: Parameters.kwargs
    ) -> Insert[Row]:
        source = self.input_factory(*args, **kwargs)
        prepared = self.row_type._prepare(source.values, for_insert=True)  # noqa: SLF001
        return Insert(self.row_type, MappingProxyType(prepared))


class InsertUsing[**Parameters, Input: Record]:
    def __init__(self, input_factory: Callable[Parameters, Input]) -> None:
        self.input_factory: Callable[Parameters, Input] = input_factory

    def __get__[Row: Record](
        self, instance: object, owner: type[Row]
    ) -> BoundInsert[Parameters, Input, Row]:
        del instance
        return BoundInsert(self.input_factory, owner)


def insert_using[**Parameters, Input: Record](
    factory: Callable[Parameters, Input],
) -> InsertUsing[Parameters, Input]:
    """Bind another model's input signature while inferring the read-row owner."""
    return InsertUsing(factory)

"""Row-first experiment over the existing immutable metadata and native SQL adapters."""

from annotationlib import Format, get_annotations
from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from types import EllipsisType, MappingProxyType, get_original_bases
from typing import (
    Any,
    ClassVar,
    Generic,
    Literal,
    Self,
    TypeVar,
    cast,
    dataclass_transform,
    get_args,
    get_origin,
)

from snekql import sqlite as native
from snekql._declaration_binding import _OnceBinding

from scratchpad.dual_backends import sqlite as backend
from scratchpad.dual_backends.core import (
    Column,
    Insert,
    Source,
    capture,
    foreign_declaration,
)
from scratchpad.dual_basics.sqlite import Database, DoNothing, DoUpdate, Transaction
from scratchpad.dual_features.records import Record as Values
from scratchpad.dual_finalization.interface import Definition, Record, RecordMeta
from scratchpad.dual_storage.interface import (
    OMIT,
    FieldDefinition,
    Omitted,
    ReadRow,
    _without_omitted,
    required,
)
from scratchpad.dual_storage.interface import (
    Field as StorageField,
)

__all__ = [
    "OMIT",
    "Database",
    "DoNothing",
    "DoUpdate",
    "Field",
    "ForeignField",
    "ForeignKey",
    "Integer",
    "Model",
    "Omitted",
    "Row",
    "Text",
    "Transaction",
    "default",
    "insert",
    "insert_using",
    "omitted",
    "scaffold",
    "select",
]

Field = backend.Field
ForeignField = backend.ForeignField
select = backend.select
scaffold = backend.scaffold
Result = TypeVar("Result", bound="Row")


def _server_default(value: object) -> object:
    if (
        value is not ...
        and value is not native.CurrentTimestamp
        and not isinstance(value, native.LiteralDefault)
    ):
        raise native.ModelDeclarationError(
            "Use a SQL default expression, not a Python default"
        )
    return value


def Integer(
    *,
    primary_key: bool = False,
    auto_increment: bool = False,
    server_default: native.LiteralDefault[Any]
    | type[native.CurrentTimestamp]
    | EllipsisType = ...,
) -> Field[Any]:
    """SQL generation does not make the row constructor's argument optional."""
    return Field(
        capture(
            "sqlite",
            native.Integer(primary_key=primary_key, auto_increment=auto_increment),
            default=OMIT
            if auto_increment and server_default is ...
            else _server_default(server_default),
        )
    )


def Text(
    *,
    unique: bool = False,
    server_default: native.LiteralDefault[Any]
    | type[native.CurrentTimestamp]
    | EllipsisType = ...,
) -> Field[Any]:
    """Separate a SQL default from a Python constructor default."""
    return Field(
        capture(
            "sqlite",
            native.Text(unique=unique),
            default=_server_default(server_default),
        )
    )


def ForeignKey[Target: ReadRow, Value](
    target: Column[Literal["sqlite"], Target, Value]
    | Callable[[], Column[Literal["sqlite"], Target, Value]],
    *,
    primary_key: bool = False,
    server_default: native.LiteralDefault[Any]
    | type[native.CurrentTimestamp]
    | EllipsisType = ...,
    on_update: Any = None,
) -> ForeignField[Target, Value]:
    """Retain field-local targets while keeping the row's value required."""
    return ForeignField(
        foreign_declaration(
            "sqlite",
            target,
            default=_server_default(server_default),
            primary_key=primary_key,
            on_update=on_update,
        )
    )


@dataclass(frozen=True)
class InputDefault:
    value: object


def omitted() -> Any:
    """Inherit storage and supply OMIT only for a database-generated field."""
    return InputDefault(OMIT)


def default(value: object) -> Any:
    """Set an input-only Python default, without changing the row or SQL default."""
    return InputDefault(value)


def _generated(descriptor: FieldDefinition[Any]) -> bool:
    value = descriptor.declaration.default
    return (
        value is OMIT
        or value is native.CurrentTimestamp
        or isinstance(value, native.LiteralDefault)
    )


def _field_type(annotation: Any, logical: Any) -> Any:
    return get_origin(annotation)[(*get_args(annotation)[:-1], logical)]


def _contract(
    owner: type[object], annotations: dict[str, Any], fields: dict[str, Any]
) -> Any:
    """Derive a private old-style contract, never a second authored storage schema."""
    return type(
        f"_{owner.__name__}Values",
        (backend.Input,),
        {
            "__module__": owner.__module__,
            "__annotations__": annotations,
            **{name: type(field)(field.declaration) for name, field in fields.items()},
        },
    )


def _row_declaration(cls: Any) -> None:
    annotations: dict[str, Any] = {}
    fields: dict[str, Any] = {}
    for base in reversed(cls.__mro__[1:]):
        annotations.update(vars(base).get("_row_annotations", {}))
        fields.update(vars(base).get("fields", {}))
    for name, annotation in get_annotations(cls, format=Format.FORWARDREF).items():
        origin = get_origin(annotation)
        if isinstance(origin, type) and issubclass(origin, StorageField):
            descriptor = vars(cls).get(name)
            if not isinstance(descriptor, StorageField):
                raise native.ModelDeclarationError(
                    "Rows declare complete storage fields"
                )
            if Omitted in get_args(get_args(annotation)[-1]):
                raise native.ModelDeclarationError("Row values cannot include Omitted")
            annotations[name] = annotation
            fields[name] = descriptor
    input_annotations = {
        name: _field_type(annotation, get_args(annotation)[-1] | Omitted)
        if _generated(fields[name])
        else annotation
        for name, annotation in annotations.items()
    }
    input_contract = _contract(cls, input_annotations, fields)
    read_contract = type(
        f"_{cls.__name__}Complete",
        (input_contract, backend.Model),
        {
            "__module__": cls.__module__,
            "__annotations__": annotations,
            **{name: required() for name in fields},
        },
    )
    cls._row_annotations = MappingProxyType(annotations)
    cls._read_contract = read_contract
    cls.fields = read_contract.fields
    cls.logical = read_contract.logical
    cls.refined = read_contract.refined
    cls._definition = Definition(cls)
    cls._finalized = True


def _input_declaration(cls: Any) -> None:
    targets = [
        get_args(base)[0]
        for base in get_original_bases(cls)
        if get_origin(base) is Model
    ]
    if len(targets) != 1:
        raise native.ModelDeclarationError("Input needs one declared row type")
    row = targets[0]
    if (
        not isinstance(row, type)
        or not issubclass(row, Row)
        or row is Row
        or issubclass(row, Model)
    ):
        raise native.ModelDeclarationError(
            "Input target must be a row, not another input"
        )
    if issubclass(cls, Row) and not issubclass(cls, row):
        raise native.ModelDeclarationError(
            "Inherited row and declared insert target disagree"
        )
    recorded = vars(cls).get("__generated_fields__")
    if recorded is not None and tuple(recorded) != tuple(row.fields):
        raise native.ModelDeclarationError(
            "Generated input fields are stale; regenerate"
        )
    defaults: dict[str, object] = {}
    annotations = dict(row._row_annotations)
    fields = dict(row.fields)
    for name, annotation in get_annotations(cls, format=Format.FORWARDREF).items():
        origin = get_origin(annotation)
        if not isinstance(origin, type) or not issubclass(origin, StorageField):
            continue
        if name not in fields:
            raise native.ModelDeclarationError("Input cannot add storage fields")
        previous = annotations[name]
        logical = get_args(annotation)[-1]
        if (
            get_origin(annotation) is not get_origin(previous)
            or get_args(annotation)[:-1] != get_args(previous)[:-1]
            or _without_omitted(logical) != get_args(previous)[-1]
        ):
            raise native.ModelDeclarationError(
                "Input override must preserve field kind, target and value type"
            )
        marker = vars(cls).get(name)
        if marker is not None and not isinstance(marker, InputDefault):
            raise native.ModelDeclarationError(
                "Input overrides defaults, never storage"
            )
        if isinstance(marker, InputDefault):
            defaults[name] = marker.value
            if marker.value is OMIT:
                if not _generated(fields[name]) or Omitted not in get_args(logical):
                    raise native.ModelDeclarationError(
                        "Only generated inputs may default to OMIT"
                    )
            else:
                fields[name] = type(fields[name])(
                    replace(fields[name].declaration, default=marker.value)
                )
        annotations[name] = annotation
    # Old input contracts require Omitted in generated logical types, even when the
    # public constructor keeps that particular field required.
    contract_annotations = {
        name: _field_type(annotation, get_args(annotation)[-1] | Omitted)
        if _generated(fields[name])
        else annotation
        for name, annotation in annotations.items()
    }
    cls._input_contract = _contract(cls, contract_annotations, fields)
    cls._row_target = row
    cls._input_annotations = MappingProxyType(annotations)
    cls._input_defaults = MappingProxyType(defaults)
    cls.fields = cls._input_contract.fields
    for name, descriptor in cls.fields.items():
        setattr(cls, name, descriptor)
    cls._definition = None
    cls._finalized = True


def _prepare_input(
    cls: Any, provided: Mapping[str, object], *, for_insert: bool
) -> dict[str, object]:
    values = dict(provided)
    for name, annotation in cls._input_annotations.items():
        if name not in values:
            if name not in cls._input_defaults:
                raise native.ModelValidationError(f"Missing input field {name!r}")
            values[name] = cls._input_defaults[name]
        if values[name] is OMIT and Omitted not in get_args(get_args(annotation)[-1]):
            raise native.ModelValidationError(
                f"Input field {name!r} does not admit Omitted"
            )
    return dict(cls._input_contract._prepare(values, for_insert=for_insert))


class ContractMeta(RecordMeta):
    def __setattr__(cls, name: str, value: object) -> None:  # noqa: N805 - metaclass
        if vars(cls).get("_finalized", False) and name in {
            "_row_target",
            "_input_contract",
            "_input_annotations",
            "_input_defaults",
            "_read_contract",
            "_row_annotations",
        }:
            raise native.FrozenModelError("Row-first contract metadata is immutable")
        super().__setattr__(name, value)


@dataclass_transform(
    field_specifiers=(Integer, Text, ForeignKey),
    frozen_default=True,
    kw_only_default=True,
)
class Row(Record, ReadRow, metaclass=ContractMeta):
    """All physical declarations and complete value annotations live here."""

    _read_contract: ClassVar[Any]

    def __init_subclass__(cls) -> None:
        if issubclass(cls, Model):
            _input_declaration(cls)
        else:
            _row_declaration(cls)

    @classmethod
    def __table_source__(cls) -> Source[Literal["sqlite"], Self]:
        if issubclass(cls, Model):
            raise native.ModelDeclarationError("Input subclasses are not SQL sources")
        return Source("sqlite", cls)

    @classmethod
    def _prepare(
        cls, provided: Mapping[str, object], *, for_insert: bool = False
    ) -> dict[str, object]:
        if issubclass(cls, Model):
            return _prepare_input(cls, provided, for_insert=for_insert)
        return dict(cls._read_contract._prepare(provided, for_insert=for_insert))


@dataclass_transform(
    field_specifiers=(Integer, Text, ForeignKey),
    frozen_default=True,
    kw_only_default=True,
)
class Model(Generic[Result], Values, metaclass=ContractMeta):
    """Input-only contract; nominally separate unless the application inherits its row."""

    fields: ClassVar[Any]
    _input_contract: ClassVar[Any]
    _input_annotations: ClassVar[Any]
    _row_target: ClassVar[Any]

    def __init_subclass__(cls) -> None:
        _input_declaration(cls)

    @classmethod
    def _prepare(
        cls, provided: Mapping[str, object], *, for_insert: bool = False
    ) -> dict[str, object]:
        return _prepare_input(cls, provided, for_insert=for_insert)


def insert[Result: Row](value: Model[Result]) -> Insert[Literal["sqlite"], Result]:
    """Implicit destination comes from the input's declared row type."""
    if not isinstance(value, Model):
        raise native.ModelDeclarationError("Insert requires an input value")
    row: Any = type(value)._row_target
    return cast(
        "Insert[Literal['sqlite'], Result]",
        Insert(
            row.__table_source__(),
            MappingProxyType(row._prepare(value.values, for_insert=True)),
        ),
    )


class BoundFactory[**Parameters, Result]:
    def __init__(
        self, owner: type[Result], constructor: Callable[Parameters, Model[Any]]
    ) -> None:
        self.owner: type[Result] = owner
        self.constructor: Callable[Parameters, Model[Any]] = constructor

    def __call__(
        self, *args: Parameters.args, **kwargs: Parameters.kwargs
    ) -> Insert[Literal["sqlite"], Result]:
        value = self.constructor(*args, **kwargs)
        if not isinstance(value, Model) or type(value)._row_target is not self.owner:
            raise native.ModelDeclarationError(
                "create must use the matching input constructor"
            )
        return cast("Insert[Literal['sqlite'], Result]", insert(value))


class InsertUsing[**Parameters]:
    def __init__(
        self, constructor: Callable[[], Callable[Parameters, Model[Any]]]
    ) -> None:
        self.binding: _OnceBinding[Callable[Parameters, Model[Any]]] = _OnceBinding(
            "row-first input constructor",
            constructor,
        )

    def __get__[Result: Row](
        self, instance: object, owner: type[Result]
    ) -> BoundFactory[Parameters, Result]:
        del instance
        constructor = self.binding.get()
        if constructor is None:
            raise native.ModelDeclarationError("Missing input constructor")
        return BoundFactory(owner, constructor)


def insert_using[**Parameters](
    constructor: Callable[[], Callable[Parameters, Model[Any]]],
) -> InsertUsing[Parameters]:
    """Defer the input constructor while retaining its keyword signature."""
    return InsertUsing(constructor)

"""Input-first MariaDB pairs over existing storage, binding, and query adapters."""

from annotationlib import Format, get_annotations
from collections.abc import Callable, Mapping
from types import MappingProxyType
from typing import (
    Any,
    ClassVar,
    Literal,
    Protocol,
    cast,
    dataclass_transform,
    get_args,
    get_origin,
)

from snekql import mariadb as native
from snekql._declaration_binding import _OnceBinding

from scratchpad.dual_backends.core import Insert, Table, capture
from scratchpad.dual_backends.mariadb import Field as Col
from scratchpad.dual_backends.mariadb import ForeignField as FKCol
from scratchpad.dual_backends.mariadb import (
    ForeignKey,
    Integer,
    Json,
    Transaction,
    scaffold,
    select,
)
from scratchpad.dual_backends.mariadb import Input as BaseModel
from scratchpad.dual_backends.mariadb import JsonField as JsonCol
from scratchpad.dual_backends.mariadb import Model as Row
from scratchpad.dual_pairing.sqlite import PairMeta
from scratchpad.dual_storage.interface import OMIT, Index, Omitted, required
from scratchpad.dual_storage.interface import FieldDefinition as BaseCol


def Text(
    *,
    length: int = 255,
    unique: bool = False,
    collation: Literal[
        "utf8mb4_bin", "utf8mb4_general_ci", "utf8mb4_unicode_ci"
    ] = "utf8mb4_bin",
    default: Any = ...,
) -> Col[Any]:
    return Col(
        capture(
            "mariadb",
            native.Text(length=length, unique=unique, collation=collation),
            default=default,
        )
    )


def Decimal(precision: int, scale: int, *, unique: bool = False) -> Col[Any]:
    return Col(capture("mariadb", native.Decimal(precision, scale, unique=unique)))


def Uuid() -> Col[Any]:
    return Col(capture("mariadb", native.Uuid()))


def DateTime(*, default: Any = ...) -> Col[Any]:
    return Col(capture("mariadb", native.DateTime(), default=default))


def Boolean(*, default: Any = ...) -> Col[Any]:
    return Col(capture("mariadb", native.Boolean(), default=default))


def LongText() -> Col[Any]:
    return Col(capture("mariadb", native.LongText()))


def Blob() -> Col[Any]:
    return Col(capture("mariadb", native.Blob()))


class Pair[Result]:
    """The input can exist before its complete class; resolve its link only on use."""

    def __init__(self, resolve: Callable[[], type[Result]]) -> None:
        self._binding: _OnceBinding[type[Result]] = _OnceBinding(
            "MariaDB row pair", resolve
        )

    def __get__(self, instance: object, owner: type[object]) -> type[Result]:
        del instance, owner
        # The resolver returns a class or raises; insertion validates ownership below.
        return cast("type[Result]", self._binding.get())


def paired[Result](resolve: Callable[[], type[Result]]) -> Pair[Result]:
    return Pair(resolve)


@dataclass_transform(
    field_specifiers=(
        Integer,
        Text,
        Decimal,
        Uuid,
        DateTime,
        Json,
        Boolean,
        LongText,
        Blob,
        ForeignKey,
        required,
    ),
    frozen_default=True,
    kw_only_default=True,
)
class Model(BaseModel, metaclass=PairMeta):
    """Annotation-only row refinements retain the input's storage declarations."""

    def __init_subclass__(cls) -> None:
        hints = get_annotations(cls, format=Format.FORWARDREF)
        for name, annotation in hints.items():
            origin = get_origin(annotation)
            if (
                name not in vars(cls)
                and isinstance(origin, type)
                and issubclass(origin, BaseCol)
                and any(name in getattr(base, "fields", {}) for base in cls.__mro__[1:])
            ):
                setattr(cls, name, required())
        if "__row__" in hints and "__row__" not in vars(cls):

            def resolve() -> Any:
                annotation = get_annotations(cls)["__row__"]
                if (
                    get_origin(annotation) is not ClassVar
                    or get_origin(get_args(annotation)[0]) is not type
                ):
                    raise native.ModelDeclarationError("Declare a ClassVar row type")
                return get_args(get_args(annotation)[0])[0]

            cls.__row__ = paired(resolve)
        super().__init_subclass__()


class Paired[Result](Protocol):
    @property
    def values(self) -> Mapping[str, object]: ...

    @property
    def __row__(self) -> type[Table[Literal["mariadb"], Result]]: ...


def insert[Result](pending: Paired[Result]) -> Insert[Literal["mariadb"], Result]:
    row: Any = getattr(pending, "__row__", None)
    if (
        not isinstance(pending, Model)
        or not isinstance(row, type)
        or not issubclass(row, Row)
        or not issubclass(row, type(pending))
        or row.backend != "mariadb"
        or set(row.fields) != set(type(pending).fields)
    ):
        raise native.ModelDeclarationError("Insert requires its paired MariaDB row")
    # Ownership and backend checks establish the pair behind the public result witness.
    return cast(
        "Insert[Literal['mariadb'], Result]",
        Insert(
            row.__table_source__(),
            MappingProxyType(row._prepare(pending.values, for_insert=True)),
        ),
    )


__all__ = [
    "OMIT",
    "Blob",
    "Boolean",
    "Col",
    "DateTime",
    "Decimal",
    "FKCol",
    "ForeignKey",
    "Index",
    "Integer",
    "Json",
    "JsonCol",
    "LongText",
    "Model",
    "Omitted",
    "Row",
    "Text",
    "Transaction",
    "Uuid",
    "insert",
    "paired",
    "scaffold",
    "select",
]

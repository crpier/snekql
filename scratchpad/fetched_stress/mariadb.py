"""MariaDB row-owned storage and independent nested input constructors."""

from collections.abc import Callable
from types import EllipsisType, MappingProxyType
from typing import Any, ClassVar, Literal, Self, cast, dataclass_transform

from snekql import mariadb as native

from scratchpad.dual_backends.core import (
    Column,
    Insert,
    Source,
    capture,
    foreign_declaration,
)
from scratchpad.dual_backends.mariadb import (
    Field,
    ForeignField,
    JsonField,
    Transaction,
    scaffold,
    select,
)
from scratchpad.dual_storage.interface import Index, ReadRow
from scratchpad.fetched_stress import contracts
from scratchpad.row_first.sqlite import OMIT, Omitted, _server_default, default, omitted


def Integer(*, primary_key: bool = False, auto_increment: bool = False) -> Field[Any]:
    return Field(
        capture(
            "mariadb",
            native.Integer(primary_key=primary_key, auto_increment=auto_increment),
            default=OMIT if auto_increment else ...,
        )
    )


def Text(
    *,
    length: int = 255,
    unique: bool = False,
    collation: Literal[
        "utf8mb4_bin", "utf8mb4_general_ci", "utf8mb4_unicode_ci"
    ] = "utf8mb4_bin",
) -> Field[Any]:
    return Field(
        capture(
            "mariadb", native.Text(length=length, unique=unique, collation=collation)
        )
    )


def Decimal(precision: int, scale: int, *, unique: bool = False) -> Field[Any]:
    return Field(capture("mariadb", native.Decimal(precision, scale, unique=unique)))


def Uuid() -> Field[Any]:
    return Field(capture("mariadb", native.Uuid()))


def DateTime(
    *,
    server_default: type[native.CurrentTimestamp]
    | native.LiteralDefault[Any]
    | EllipsisType = ...,
) -> Field[Any]:
    return Field(
        capture("mariadb", native.DateTime(), default=_server_default(server_default))
    )


def Json() -> JsonField[Any]:
    return JsonField(capture("mariadb", native.Json()))


def Boolean() -> Field[Any]:
    return Field(capture("mariadb", native.Boolean()))


def LongText() -> Field[Any]:
    return Field(capture("mariadb", native.LongText()))


def Blob() -> Field[Any]:
    return Field(capture("mariadb", native.Blob()))


def ForeignKey[Target: ReadRow, Value](
    target: Column[Literal["mariadb"], Target, Value]
    | Callable[[], Column[Literal["mariadb"], Target, Value]],
    *,
    on_update: str | None = None,
    on_delete: str | None = None,
) -> ForeignField[Target, Any]:
    return ForeignField(
        foreign_declaration("mariadb", target, on_update=on_update, on_delete=on_delete)
    )


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
    ),
    frozen_default=True,
    kw_only_default=True,
)
class Pending(contracts.Pending):
    backend: ClassVar[Literal["mariadb"]] = "mariadb"


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
    ),
    frozen_default=True,
    kw_only_default=True,
)
class Row(contracts.Row):
    backend: ClassVar[Literal["mariadb"]] = "mariadb"

    @classmethod
    def __table_source__(cls) -> Source[Literal["mariadb"], Self]:
        return Source("mariadb", cls)


def insert[Result: Row](
    pending: contracts.Paired[Result],
) -> Insert[Literal["mariadb"], Result]:
    if not isinstance(pending, Pending):
        raise native.ModelDeclarationError("Insert a MariaDB Pending value")
    row: Any = type(pending)._row_target
    if row.backend != "mariadb":
        raise native.ModelDeclarationError("Insert crosses Backend Families")
    # Declaration checks establish the row/result relation before this erased bridge.
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
    "DateTime",
    "Decimal",
    "Field",
    "ForeignField",
    "ForeignKey",
    "Index",
    "Integer",
    "Json",
    "JsonField",
    "LongText",
    "Omitted",
    "Pending",
    "Row",
    "Text",
    "Transaction",
    "Uuid",
    "default",
    "insert",
    "omitted",
    "scaffold",
    "select",
]

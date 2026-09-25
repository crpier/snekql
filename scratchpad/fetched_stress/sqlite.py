"""SQLite nested contracts with deferred foreign-owner agreement."""

from collections.abc import Callable
from types import EllipsisType, MappingProxyType
from typing import Any, ClassVar, Literal, Self, cast, dataclass_transform

from snekql import sqlite as native

from scratchpad.dual_backends.core import (
    Column,
    Insert,
    Source,
    capture,
    foreign_declaration,
)
from scratchpad.fetched_stress import contracts
from scratchpad.row_first.sqlite import (
    OMIT,
    Database,
    DoUpdate,
    Field,
    ForeignField,
    Integer,
    Omitted,
    Text,
    Transaction,
    _server_default,
    default,
    omitted,
    scaffold,
    select,
)


def Blob() -> Field[Any]:
    return Field(capture("sqlite", native.Blob()))


def ForeignKey[Target: contracts.Row, Value](
    target: Column[Literal["sqlite"], Target, Value]
    | Callable[[], Column[Literal["sqlite"], Target, Value]],
    *,
    server_default: native.LiteralDefault[Any] | EllipsisType = ...,
    on_update: str | None = None,
    on_delete: str | None = None,
) -> ForeignField[Target, Any]:
    """Annotation supplies local nullability; graph binding validates the value domain."""
    return ForeignField(
        foreign_declaration(
            "sqlite",
            target,
            default=_server_default(server_default),
            on_update=on_update,
            on_delete=on_delete,
        )
    )


@dataclass_transform(
    field_specifiers=(Integer, Text, Blob, ForeignKey),
    frozen_default=True,
    kw_only_default=True,
)
class Pending(contracts.Pending):
    backend: ClassVar[Literal["sqlite"]] = "sqlite"


@dataclass_transform(
    field_specifiers=(Integer, Text, Blob, ForeignKey),
    frozen_default=True,
    kw_only_default=True,
)
class Row(contracts.Row):
    @classmethod
    def __table_source__(cls) -> Source[Literal["sqlite"], Self]:
        return Source("sqlite", cls)


def insert[Result: Row](
    pending: contracts.Paired[Result],
) -> Insert[Literal["sqlite"], Result]:
    if not isinstance(pending, Pending):
        raise native.ModelDeclarationError("Insert a SQLite Pending value")
    row: Any = type(pending)._row_target
    if row.backend != "sqlite":
        raise native.ModelDeclarationError("Insert crosses Backend Families")
    # Declaration checks bind this nominal Pending class to exactly one complete row.
    return cast(
        "Insert[Literal['sqlite'], Result]",
        Insert(
            row.__table_source__(),
            MappingProxyType(row._prepare(pending.values, for_insert=True)),
        ),
    )


__all__ = [
    "OMIT",
    "Blob",
    "Database",
    "DoUpdate",
    "Field",
    "ForeignField",
    "ForeignKey",
    "Integer",
    "Omitted",
    "Pending",
    "Row",
    "Text",
    "Transaction",
    "default",
    "insert",
    "omitted",
    "scaffold",
    "select",
]

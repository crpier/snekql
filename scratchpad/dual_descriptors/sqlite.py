"""Experimental direct native query descriptors over dual declaration metadata."""

from collections.abc import Callable
from typing import Any, ClassVar, Literal, dataclass_transform, overload

from snekql import sqlite as native
from snekql.model import Table
from snekql.storage import Attr, FKAttr

from scratchpad.dual_backends.core import Column as DeclarationColumn
from scratchpad.dual_backends.core import capture, foreign_declaration
from scratchpad.dual_descriptors.columns import Descriptor, _LazyColumn
from scratchpad.dual_features.records import Record
from scratchpad.dual_storage.interface import (
    OMIT,
    ForeignDefinition,
    Omitted,
    required,
)
from scratchpad.dual_typing_parity.bridge import (
    Owner,
    Row,
    Transaction,
    insert,
    insert_many,
    table,
)
from scratchpad.paired_situations.dual_sqlite import Model as OriginalModel
from scratchpad.paired_situations.dual_sqlite import paired, scaffold

type Column[Access: Row, Value, Compare = Value] = Attr[
    Table[native.Pending],
    Table[native.Fetched],
    Owner[Access],
    Value,
    Value,
    Value,
    Compare,
]


class Col[Value](Descriptor[Value]):
    """SQLite-native class expressions with ordinary logical instance values."""

    __family__: ClassVar[Literal["sqlite"]] = "sqlite"

    @overload
    def __get__[Access: Row, NonNull](
        self: Col[NonNull | None], instance: None, owner: type[Access]
    ) -> Column[Access, NonNull | None, NonNull]: ...
    @overload
    def __get__[Access: Row](
        self, instance: None, owner: type[Access]
    ) -> Column[Access, Value]: ...
    @overload
    def __get__(self, instance: None, owner: type[Record]) -> object: ...
    @overload
    def __get__(self, instance: Record, owner: type[object]) -> Value: ...
    def __get__(self, instance: Record | None, owner: type[object]) -> Any:
        return self._access(instance, owner)


type ForeignColumn[Access: Row, Target: Row, Value, Compare = Value] = FKAttr[
    Table[native.Pending],
    Table[native.Fetched],
    Owner[Access],
    Value,
    Value,
    Owner[Target],
    Value,
    Compare,
]


class FKCol[Target: Row, Value](Col[Value], ForeignDefinition):
    """Native foreign expressions keep the exact public target's phantom owner."""

    @overload
    def __get__[Access: Row, NonNull](
        self: FKCol[Target, NonNull | None], instance: None, owner: type[Access]
    ) -> ForeignColumn[Access, Target, NonNull | None, NonNull]: ...
    @overload
    def __get__[Access: Row](
        self, instance: None, owner: type[Access]
    ) -> ForeignColumn[Access, Target, Value]: ...
    @overload
    def __get__(self, instance: None, owner: type[Record]) -> object: ...
    @overload
    def __get__(self, instance: Record, owner: type[object]) -> Value: ...
    def __get__(self, instance: Record | None, owner: type[object]) -> Any:
        return self._access(instance, owner)


@overload
def ForeignKey[Target: Row, Value](
    target: Column[Target, Value, Any],
    *,
    on_update: str | None = None,
    on_delete: str | None = None,
    primary_key: bool = False,
) -> FKCol[Target, Value]: ...
@overload
def ForeignKey[Target: Row, Value](
    target: Column[Target, Value, Any] | Callable[[], Column[Target, Value, Any]],
    *,
    default: native.LiteralDefault[None],
    on_update: str | None = None,
    on_delete: str | None = None,
    primary_key: bool = False,
) -> FKCol[Target, Value | Omitted | None]: ...
@overload
def ForeignKey[Target: Row, Value](
    target: Column[Target, Value, Any] | Callable[[], Column[Target, Value, Any]],
    *,
    default: native.LiteralDefault[Value] | Omitted,
    on_update: str | None = None,
    on_delete: str | None = None,
    primary_key: bool = False,
) -> FKCol[Target, Value | Omitted]: ...
@overload
def ForeignKey[Target: Row, Value](
    target: Column[Target, Value, Any] | Callable[[], Column[Target, Value, Any]],
    *,
    default: None,
    on_update: str | None = None,
    on_delete: str | None = None,
    primary_key: bool = False,
) -> FKCol[Target, Value | None]: ...
@overload
def ForeignKey[Target: Row, Value](
    target: Column[Target, Value, Any] | Callable[[], Column[Target, Value, Any]],
    *,
    default: Value,
    on_update: str | None = None,
    on_delete: str | None = None,
    primary_key: bool = False,
) -> FKCol[Target, Value]: ...
def ForeignKey(
    target: Any,
    *,
    default: Any = ...,
    on_update: str | None = None,
    on_delete: str | None = None,
    primary_key: bool = False,
) -> Any:
    def resolve() -> DeclarationColumn[Literal["sqlite"], Row, Any]:
        column = target() if callable(target) else target
        if not isinstance(column, _LazyColumn):
            raise native.ModelDeclarationError(
                "Foreign target requires a dual SQLite column"
            )
        # Read declaration identity without evaluating the native graph it names.
        return type(column).__declaration_reference__(column)

    return FKCol(
        foreign_declaration(
            "sqlite",
            resolve,
            default=default,
            on_update=on_update,
            on_delete=on_delete,
            primary_key=primary_key,
        )
    )


def Integer(
    *,
    default: Any = ...,
    default_factory: Any = ...,
    primary_key: bool = False,
    auto_increment: bool = False,
) -> Col[Any]:
    return Col(
        capture(
            "sqlite",
            native.Integer(primary_key=primary_key, auto_increment=auto_increment),
            default=default,
            default_factory=default_factory,
        )
    )


def Text(
    *, default: Any = ..., default_factory: Any = ..., unique: bool = False
) -> Col[Any]:
    return Col(
        capture(
            "sqlite",
            native.Text(unique=unique),
            default=default,
            default_factory=default_factory,
        )
    )


def Real(*, default: Any = ..., default_factory: Any = ...) -> Col[Any]:
    return Col(
        capture(
            "sqlite", native.Real(), default=default, default_factory=default_factory
        )
    )


def Blob(*, default: Any = ..., default_factory: Any = ...) -> Col[Any]:
    return Col(
        capture(
            "sqlite", native.Blob(), default=default, default_factory=default_factory
        )
    )


@dataclass_transform(
    field_specifiers=(Integer, Text, Real, Blob, ForeignKey, required),
    frozen_default=True,
    kw_only_default=True,
)
class Model(OriginalModel):
    """Retain input-first metadata and pairing; change only the column interface."""


__all__ = [
    "OMIT",
    "Blob",
    "Col",
    "FKCol",
    "ForeignKey",
    "Integer",
    "Model",
    "Omitted",
    "Real",
    "Row",
    "Text",
    "Transaction",
    "insert",
    "insert_many",
    "paired",
    "scaffold",
    "table",
]

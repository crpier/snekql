"""Bounded SQLite declaration namespace with familiar Column Type constructors."""

from collections.abc import Callable
from typing import Any, ClassVar, Literal, Self, dataclass_transform, overload

from snekql import sqlite as native

from scratchpad.dual_backends.core import (
    Column,
    Namespace,
    Source,
    capture,
    foreign_declaration,
)
from scratchpad.dual_backends.core import Field as BaseField
from scratchpad.dual_backends.core import ForeignField as BaseForeignField
from scratchpad.dual_backends.core import Input as BaseInput
from scratchpad.dual_backends.core import Select as BaseSelect
from scratchpad.dual_backends.core import Transaction as BaseTransaction
from scratchpad.dual_storage.interface import OMIT, Omitted, ReadRow, required

__all__ = [
    "OMIT",
    "Field",
    "ForeignField",
    "ForeignKey",
    "Input",
    "Integer",
    "Model",
    "Omitted",
    "Select",
    "Text",
    "Transaction",
    "insert_using",
    "required",
    "scaffold",
    "select",
]


class Field[Value](BaseField[Literal["sqlite"], Value]):
    """SQLite-owned field values and column expressions."""

    __family__: ClassVar[Literal["sqlite"]] = "sqlite"


def Integer(
    *,
    default: Any = ...,
    default_factory: Any = ...,
    primary_key: bool = False,
    auto_increment: bool = False,
) -> Field[Any]:
    return Field(
        capture(
            "sqlite",
            native.Integer(primary_key=primary_key, auto_increment=auto_increment),
            default=default,
            default_factory=default_factory,
        )
    )


def Text(
    *, default: Any = ..., default_factory: Any = ..., unique: bool = False
) -> Field[Any]:
    return Field(
        capture(
            "sqlite",
            native.Text(unique=unique),
            default=default,
            default_factory=default_factory,
        )
    )


class ForeignField[Target: ReadRow, Value](
    BaseForeignField[Literal["sqlite"], Target, Value]
):
    """Target-aware foreign columns owned by this Backend Namespace."""

    __family__: ClassVar[Literal["sqlite"]] = "sqlite"


@overload
def ForeignKey[Target: ReadRow, Value](
    target: Column[Literal["sqlite"], Target, Value]
    | Callable[[], Column[Literal["sqlite"], Target, Value]],
    *,
    default: native.LiteralDefault[None],
    on_update: str | None = None,
    on_delete: str | None = None,
    primary_key: bool = False,
) -> ForeignField[Target, Value | Omitted | None]: ...
@overload
def ForeignKey[Target: ReadRow, Value](
    target: Column[Literal["sqlite"], Target, Value]
    | Callable[[], Column[Literal["sqlite"], Target, Value]],
    *,
    default: native.LiteralDefault[Value] | Omitted,
    on_update: str | None = None,
    on_delete: str | None = None,
    primary_key: bool = False,
) -> ForeignField[Target, Value | Omitted]: ...
@overload
def ForeignKey[Target: ReadRow, Value](
    target: Column[Literal["sqlite"], Target, Value]
    | Callable[[], Column[Literal["sqlite"], Target, Value]],
    *,
    default: None,
    on_update: str | None = None,
    on_delete: str | None = None,
    primary_key: bool = False,
) -> ForeignField[Target, Value | None]: ...
@overload
def ForeignKey[Target: ReadRow, Value](
    target: Column[Literal["sqlite"], Target, Value]
    | Callable[[], Column[Literal["sqlite"], Target, Value]],
    *,
    default: Value = ...,
    on_update: str | None = None,
    on_delete: str | None = None,
    primary_key: bool = False,
) -> ForeignField[Target, Value]: ...
def ForeignKey(
    target: Any,
    *,
    default: Any = ...,
    on_update: str | None = None,
    on_delete: str | None = None,
    primary_key: bool = False,
) -> Any:
    return ForeignField(
        foreign_declaration(
            "sqlite",
            target,
            default=default,
            on_update=on_update,
            on_delete=on_delete,
            primary_key=primary_key,
        )
    )


@dataclass_transform(
    field_specifiers=(Integer, Text, ForeignKey, required),
    frozen_default=True,
    kw_only_default=True,
)
class Input(BaseInput[Literal["sqlite"]]):
    """Input contract with a hidden SQLite witness."""


class Model(ReadRow):
    """Marker for complete fetched SQLite values."""

    @classmethod
    def __table_source__(cls) -> Source[Literal["sqlite"], Self]:
        return Source("sqlite", cls)


_namespace: Namespace[Literal["sqlite"]] = Namespace("sqlite", native)
select = _namespace.select
scaffold = _namespace.scaffold

insert_using = _namespace.insert_using


class Transaction(BaseTransaction[Literal["sqlite"]]):
    """A backend-pinned view of an active native transaction."""

    def __init__(self, transaction: native.Transaction) -> None:
        super().__init__("sqlite", transaction, native)


type Select[Result] = BaseSelect[Literal["sqlite"], Result]

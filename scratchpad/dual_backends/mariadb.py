"""Bounded MariaDB declaration namespace, including typed native JSON operations."""

from collections.abc import Callable
from typing import Any, ClassVar, Literal, Self, dataclass_transform, overload

from snekql import mariadb as native

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
from scratchpad.dual_backends.core import JsonField as BaseJsonField
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
    "Json",
    "JsonField",
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


class Field[Value](BaseField[Literal["mariadb"], Value]):
    """MariaDB-owned field values and columns."""

    __family__: ClassVar[Literal["mariadb"]] = "mariadb"


class JsonField[Value](BaseJsonField[Literal["mariadb"], Value], Field[Value]):
    """Native JSON operations remain available on this field's class column."""


def Integer(
    *,
    default: Any = ...,
    default_factory: Any = ...,
    primary_key: bool = False,
    auto_increment: bool = False,
) -> Field[Any]:
    return Field(
        capture(
            "mariadb",
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
            "mariadb",
            native.Text(unique=unique),
            default=default,
            default_factory=default_factory,
        )
    )


def Json(*, default: Any = ..., default_factory: Any = ...) -> JsonField[Any]:
    return JsonField(
        capture(
            "mariadb", native.Json(), default=default, default_factory=default_factory
        )
    )


class ForeignField[Target: ReadRow, Value](
    BaseForeignField[Literal["mariadb"], Target, Value]
):
    """Target-aware foreign columns owned by this Backend Namespace."""

    __family__: ClassVar[Literal["mariadb"]] = "mariadb"


@overload
def ForeignKey[Target: ReadRow, Value](
    target: Column[Literal["mariadb"], Target, Value]
    | Callable[[], Column[Literal["mariadb"], Target, Value]],
    *,
    default: native.LiteralDefault[None],
    on_update: str | None = None,
    on_delete: str | None = None,
) -> ForeignField[Target, Value | Omitted | None]: ...
@overload
def ForeignKey[Target: ReadRow, Value](
    target: Column[Literal["mariadb"], Target, Value]
    | Callable[[], Column[Literal["mariadb"], Target, Value]],
    *,
    default: native.LiteralDefault[Value] | Omitted,
    on_update: str | None = None,
    on_delete: str | None = None,
) -> ForeignField[Target, Value | Omitted]: ...
@overload
def ForeignKey[Target: ReadRow, Value](
    target: Column[Literal["mariadb"], Target, Value]
    | Callable[[], Column[Literal["mariadb"], Target, Value]],
    *,
    default: None,
    on_update: str | None = None,
    on_delete: str | None = None,
) -> ForeignField[Target, Value | None]: ...
@overload
def ForeignKey[Target: ReadRow, Value](
    target: Column[Literal["mariadb"], Target, Value]
    | Callable[[], Column[Literal["mariadb"], Target, Value]],
    *,
    default: Value = ...,
    on_update: str | None = None,
    on_delete: str | None = None,
) -> ForeignField[Target, Value]: ...
def ForeignKey(
    target: Any,
    *,
    default: Any = ...,
    on_update: str | None = None,
    on_delete: str | None = None,
) -> Any:
    return ForeignField(
        foreign_declaration(
            "mariadb", target, default=default, on_update=on_update, on_delete=on_delete
        )
    )


@dataclass_transform(
    field_specifiers=(Integer, Text, ForeignKey, Json, required),
    frozen_default=True,
    kw_only_default=True,
)
class Input(BaseInput[Literal["mariadb"]], backend="mariadb"):
    """Input contract with a hidden MariaDB witness."""


class Model(ReadRow):
    """Marker for complete fetched MariaDB values."""

    @classmethod
    def __table_source__(cls) -> Source[Literal["mariadb"], Self]:
        return Source("mariadb", cls)


_namespace: Namespace[Literal["mariadb"]] = Namespace("mariadb", native)
select = _namespace.select
scaffold = _namespace.scaffold

insert_using = _namespace.insert_using


class Transaction(BaseTransaction[Literal["mariadb"]]):
    """A backend-pinned view of an active native transaction."""

    def __init__(self, transaction: native.Transaction) -> None:
        super().__init__("mariadb", transaction, native)


type Select[Result] = BaseSelect[Literal["mariadb"], Result]

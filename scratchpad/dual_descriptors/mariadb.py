"""MariaDB descriptor experiment; model-result execution still uses the older adapter."""

from collections.abc import Callable
from typing import (
    Any,
    ClassVar,
    Generic,
    Literal,
    TypeVar,
    cast,
    dataclass_transform,
    overload,
)

from snekql import mariadb as native
from snekql.mariadb.storage import JsonAttr
from snekql.model import Table
from snekql.storage import Attr, FKAttr

from scratchpad.dual_backends.core import Column as DeclarationColumn
from scratchpad.dual_backends.core import Table as TableSource
from scratchpad.dual_backends.core import capture, foreign_declaration
from scratchpad.dual_descriptors.columns import Descriptor, _LazyColumn
from scratchpad.dual_features.records import Record
from scratchpad.dual_finalization.interface import Record as StorageRecord
from scratchpad.dual_finalization.interface import Schema
from scratchpad.dual_storage.interface import OMIT, ForeignDefinition, Omitted, required
from scratchpad.paired_situations.dual_mariadb import Model as OriginalModel
from scratchpad.paired_situations.dual_mariadb import Row as OriginalRow
from scratchpad.paired_situations.dual_mariadb import (
    Transaction,
    insert,
    paired,
    scaffold,
)


class Row(Table[native.Fetched], OriginalRow, StorageRecord):
    """A complete dual MariaDB value, satisfying native query result bounds."""


Result = TypeVar("Result", bound=Row)


class Owner(native.Model[native.Pending, Result], Generic[Result]):  # noqa: UP046 - Explicit invariance in public row identity.
    """Native query owner, invariant in the corresponding complete public class."""


def table[Result: Row](
    row: type[TableSource[Literal["mariadb"], Result]],
) -> type[Owner[Result]]:
    if not isinstance(row, type) or not issubclass(row, Row):
        raise native.ModelDeclarationError("Query a complete MariaDB row class")
    # Only owner typing is translated here. Native scalar decoding is unchanged;
    # a model-result consumer would still need a dedicated materialization adapter.
    return cast("type[Owner[Result]]", Schema(row).native(row))


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

    __family__: ClassVar[Literal["mariadb"]] = "mariadb"

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
    def resolve() -> DeclarationColumn[Literal["mariadb"], Row, Any]:
        column = target() if callable(target) else target
        if not isinstance(column, _LazyColumn):
            raise native.ModelDeclarationError(
                "Foreign target requires a dual MariaDB column"
            )
        # Read declaration identity without evaluating the native graph it names.
        return type(column).__declaration_reference__(column)

    return FKCol(
        foreign_declaration(
            "mariadb",
            resolve,
            default=default,
            on_update=on_update,
            on_delete=on_delete,
            primary_key=primary_key,
        )
    )


type JsonColumn[Access: Row, Value, Compare = Value] = JsonAttr[
    Table[native.Pending],
    Table[native.Fetched],
    Owner[Access],
    Value,
    Value,
    Value,
    Compare,
]


class JsonCol[Value](Col[Value]):
    """Native JSON query expressions stay distinct from ordinary columns."""

    @overload
    def __get__[Access: Row, NonNull](
        self: JsonCol[NonNull | None], instance: None, owner: type[Access]
    ) -> JsonColumn[Access, NonNull | None, NonNull]: ...
    @overload
    def __get__[Access: Row](
        self, instance: None, owner: type[Access]
    ) -> JsonColumn[Access, Value]: ...
    @overload
    def __get__(self, instance: None, owner: type[Record]) -> object: ...
    @overload
    def __get__(self, instance: Record, owner: type[object]) -> Value: ...
    def __get__(self, instance: Record | None, owner: type[object]) -> Any:
        return self._access(instance, owner)


def Integer(
    *, default: Any = ..., primary_key: bool = False, auto_increment: bool = False
) -> Col[Any]:
    return Col(
        capture(
            "mariadb",
            native.Integer(primary_key=primary_key, auto_increment=auto_increment),
            default=default,
        )
    )


def Text(*, default: Any = ..., unique: bool = False) -> Col[Any]:
    return Col(capture("mariadb", native.Text(unique=unique), default=default))


def Decimal(precision: int, scale: int, *, unique: bool = False) -> Col[Any]:
    return Col(capture("mariadb", native.Decimal(precision, scale, unique=unique)))


def Json(*, default: Any = ...) -> JsonCol[Any]:
    return JsonCol(capture("mariadb", native.Json(), default=default))


@dataclass_transform(
    field_specifiers=(Integer, Text, Decimal, Json, ForeignKey, required),
    frozen_default=True,
    kw_only_default=True,
)
class Model(OriginalModel):
    """Input-first storage and pairing, with direct native class expressions."""


__all__ = [
    "OMIT",
    "Col",
    "Decimal",
    "FKCol",
    "ForeignKey",
    "Integer",
    "Json",
    "JsonCol",
    "Model",
    "Omitted",
    "Row",
    "Text",
    "Transaction",
    "insert",
    "paired",
    "scaffold",
    "table",
]

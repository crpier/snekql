"""Fetched-first nesting research; native storage and runtime through prior adapters."""

from annotationlib import Format, ForwardRef, get_annotations
from collections.abc import Mapping
from types import MappingProxyType
from typing import (
    Any,
    ClassVar,
    Literal,
    Protocol,
    cast,
    dataclass_transform,
    evaluate_forward_ref,
    get_args,
    get_origin,
)

from snekql import sqlite as native

from scratchpad.dual_backends.core import Insert
from scratchpad.dual_features.records import Record as Values
from scratchpad.row_first import sqlite as rows

Field = rows.Field
ForeignField = rows.ForeignField
Integer = rows.Integer
Text = rows.Text
ForeignKey = rows.ForeignKey
omitted = rows.omitted
default = rows.default
OMIT = rows.OMIT
Omitted = rows.Omitted
Database = rows.Database
Transaction = rows.Transaction
DoNothing = rows.DoNothing
DoUpdate = rows.DoUpdate
select = rows.select
scaffold = rows.scaffold


class ContractMeta(rows.ContractMeta):
    def __setattr__(cls, name: str, value: object) -> None:
        if vars(cls).get("_finalized", False) and name in {"__row__", "Pending"}:
            raise native.FrozenModelError("Nested contract pairing is immutable")
        super().__setattr__(name, value)

    def __delattr__(cls, name: str) -> None:
        if vars(cls).get("_finalized", False) and name in {"__row__", "Pending"}:
            raise native.FrozenModelError("Nested contract pairing is immutable")
        super().__delattr__(name)


@dataclass_transform(
    field_specifiers=(Integer, Text, ForeignKey),
    frozen_default=True,
    kw_only_default=True,
)
class Pending(Values, metaclass=ContractMeta):
    """A separate value class, completed by its enclosing Row declaration."""

    fields: ClassVar[Any]
    _input_contract: ClassVar[Any]
    _input_annotations: ClassVar[Any]
    _input_defaults: ClassVar[Any]
    _row_target: ClassVar[Any]

    def __init_subclass__(cls) -> None:
        pass

    @classmethod
    def _prepare(
        cls, provided: Mapping[str, object], *, for_insert: bool = False
    ) -> dict[str, object]:
        if not vars(cls).get("_finalized", False):
            raise native.ModelDeclarationError(
                "Bind Pending to an enclosing row before construction"
            )
        return rows._prepare_input(cls, provided, for_insert=for_insert)


class Row(rows.Row, metaclass=ContractMeta):
    """Complete values and all storage declarations live on the short outer name."""

    def __init_subclass__(cls) -> None:
        super().__init_subclass__()
        _bind_pending(cls, require_witness=True)


def _bind_pending(cls: Any, *, require_witness: bool) -> None:
    """Reuse row-first validation with an outer row known at class completion."""
    pending = vars(cls).get("Pending")
    if not isinstance(pending, type) or not issubclass(pending, Pending):
        raise native.ModelDeclarationError("Declare a nested Pending contract")
    hints = get_annotations(pending, format=Format.FORWARDREF)
    if require_witness:
        witness = hints.get("__row__")
        if (
            get_origin(witness) is not ClassVar
            or get_origin(get_args(witness)[0]) is not type
        ):
            raise native.ModelDeclarationError("Pending needs a ClassVar row witness")
        target = get_args(get_args(witness)[0])[0]
        if isinstance(target, ForwardRef):
            target = evaluate_forward_ref(
                target, owner=pending, locals={cls.__name__: cls}
            )
        if target is not cls:
            raise native.ModelDeclarationError("Pending must name its enclosing row")
    annotations = {name: hint for name, hint in hints.items() if name != "__row__"}
    if set(annotations) != set(cls.fields):
        raise native.ModelDeclarationError("Repeat every row field in Pending")
    contract = type(
        f"_{cls.__name__}PendingContract",
        (rows.Model,),
        {
            "__module__": cls.__module__,
            "__orig_bases__": (rows.Model[cls],),
            "__annotations__": annotations,
            **{
                name: vars(pending)[name]
                for name in annotations
                if name in vars(pending)
            },
        },
    )
    for name in (
        "_input_contract",
        "_input_annotations",
        "_input_defaults",
        "_row_target",
        "fields",
    ):
        setattr(pending, name, getattr(contract, name))
    for name, descriptor in pending.fields.items():
        setattr(pending, name, descriptor)
    pending.__row__ = cls
    pending._finalized = True


class Paired[Result](Protocol):
    @property
    def values(self) -> Mapping[str, object]: ...
    @property
    def __row__(self) -> type[Result]: ...


def insert[Result: rows.Row](
    pending: Paired[Result],
) -> Insert[Literal["sqlite"], Result]:
    """Infer the result from a concrete outward witness, not runtime nesting alone."""
    if not isinstance(pending, Pending):
        raise native.ModelDeclarationError("Insert a nested Pending value")
    row: Any = type(pending)._row_target
    # Runtime declaration validation establishes the private metadata/result relation.
    return cast(
        "Insert[Literal['sqlite'], Result]",
        Insert(
            row.__table_source__(),
            MappingProxyType(row._prepare(pending.values, for_insert=True)),
        ),
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

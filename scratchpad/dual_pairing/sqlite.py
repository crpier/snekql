"""Implicit-pairing experiment; native adapters still own storage and execution."""

from annotationlib import Format, get_annotations
from collections.abc import Callable, Mapping
from types import MappingProxyType
from typing import Any, ClassVar, Literal, Protocol, cast, get_args, get_origin

from snekql import sqlite as native
from snekql._declaration_binding import _OnceBinding

from scratchpad.dual_backends.core import Insert, Table
from scratchpad.dual_basics.sqlite import (
    OMIT,
    Database,
    DoNothing,
    DoUpdate,
    Field,
    ForeignField,
    ForeignKey,
    Integer,
    Omitted,
    Row,
    Text,
    Transaction,
    insert_using,
    scaffold,
    select,
)
from scratchpad.dual_basics.sqlite import Model as BaseModel
from scratchpad.dual_finalization.interface import RecordMeta

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
    "insert",
    "insert_using",
    "paired",
    "scaffold",
    "select",
]


class PairMeta(RecordMeta):
    """Treat the row witness as a declaration fact, like fields and table names."""

    def __setattr__(cls, name: str, value: object) -> None:  # noqa: N805 - metaclass
        if name == "__row__" and vars(cls).get("_finalized", False):
            raise native.FrozenModelError("The declared row pair cannot be replaced")
        super().__setattr__(name, value)


class Model(BaseModel, metaclass=PairMeta):
    """Construction remains independent of a row class or schema registry."""

    def __init_subclass__(cls) -> None:
        annotation = get_annotations(cls, format=Format.FORWARDREF).get("__row__")
        if annotation is not None and "__row__" not in vars(cls):

            def resolve() -> Any:
                declared = get_annotations(cls)["__row__"]
                if get_origin(declared) is not ClassVar:
                    raise native.ModelDeclarationError(
                        "Pair annotations require ClassVar"
                    )
                target = get_args(declared)[0]
                if get_origin(target) is not type:
                    raise native.ModelDeclarationError(
                        "Pair annotations require a row class"
                    )
                return get_args(target)[0]

            descriptor = paired(resolve)
            descriptor.__set_name__(cls, "__row__")
            setattr(cls, "__row__", descriptor)
        super().__init_subclass__()


class Paired[Result](Protocol):
    @property
    def values(self) -> Mapping[str, object]: ...

    @property
    def __row__(self) -> type[Table[Literal["sqlite"], Result]]: ...


class Pair[Result]:
    """A typed lazy link, fixed on first use and shared by constructed inputs."""

    def __init__(self, callback: Callable[[], type[Result]]) -> None:
        self._callback: Callable[[], type[Result]] = callback
        self._owner: type[Model] | None = None
        self._failed: bool = False
        self._binding: _OnceBinding[type[Result]] = _OnceBinding(
            "implicit row pair", self._resolve
        )

    def __set_name__(self, owner: type[Model], name: str) -> None:
        if name != "__row__" or self._owner is not None:
            raise native.ModelDeclarationError("Declare each pair once as __row__")
        self._owner = owner

    def __get__(self, instance: object, owner: type[object]) -> type[Result]:
        del instance, owner
        # _resolve returns a class or raises; None is only a reentry sentinel.
        try:
            return cast("type[Result]", self._binding.get())
        except native.ModelDeclarationError:
            self._failed = True
            raise

    def _resolve(self) -> type[Result]:
        row = self._callback()
        if self._failed:
            raise native.ModelDeclarationError("Reentrant use poisoned the pair")
        _validate_pair(self._owner, row)
        return row


def _validate_pair(owner: object, row: object, *, allow_complete: bool = False) -> None:
    if (
        not isinstance(owner, type)
        or not issubclass(owner, Model)
        or not isinstance(row, type)
        or not issubclass(row, Row)
        or not issubclass(row, owner)
        or (row is owner and not allow_complete)
        or row.backend != "sqlite"
        or set(row.fields) != set(owner.fields)
    ):
        raise native.ModelDeclarationError(
            "The paired row must be a complete SQLite row of this input contract"
        )


def paired[Result](callback: Callable[[], type[Result]]) -> Pair[Result]:
    """Declare the row on the input without evaluating a forward reference yet."""
    return Pair(callback)


def insert[Result](value: Paired[Result]) -> Insert[Literal["sqlite"], Result]:
    """Insert an existing input value using its declared row, never a destination arg."""
    if not isinstance(value, Model):
        raise native.ModelDeclarationError(
            "Insert requires a paired SQLite model value"
        )
    row: Any = getattr(value, "__row__", None)
    _validate_pair(type(value), row, allow_complete=True)
    return Insert(
        row.__table_source__(),
        MappingProxyType(row._prepare(value.values, for_insert=True)),
    )

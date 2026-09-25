"""Canonical native columns shared by the experimental backend descriptors."""

from collections.abc import Iterator
from contextlib import contextmanager
from threading import RLock, get_ident
from typing import Any, Literal

from snekql import sqlite as native
from snekql.mariadb.storage import JsonAttr
from snekql.storage import FKAttr

from scratchpad.dual_backends.core import Column as DeclarationColumn
from scratchpad.dual_features.records import Record as Values
from scratchpad.dual_finalization.interface import Record
from scratchpad.dual_storage.interface import Declaration, FieldDefinition, ReadRow


class _LazyColumn(FKAttr[Any, Any, Any, Any, Any, Any]):
    """One canonical column before, during, and after native graph binding."""

    def __init__(self, row: type[Record], name: str) -> None:
        object.__setattr__(self, "_dual_row", row)
        object.__setattr__(self, "_dual_name", name)
        object.__setattr__(self, "_dual_building", None)

    def __getattribute__(self, name: str) -> Any:
        if name.startswith("_dual_") or name == "__class__":
            return object.__getattribute__(self, name)
        if object.__getattribute__(self, "_dual_building") != get_ident():
            # Failed graphs remain unreadable, including after partial assembly.
            _ = object.__getattribute__(self, "_dual_row").binding
        return object.__getattribute__(self, name)

    def __setattr__(self, name: str, value: object) -> None:
        if name.startswith("_dual_"):
            raise native.FrozenModelError("Query column identity is immutable")
        super().__setattr__(name, value)

    def __delattr__(self, name: str) -> None:
        raise native.FrozenModelError("Query column metadata is immutable")

    def __declaration_reference__(
        self,
    ) -> DeclarationColumn[Literal["sqlite", "mariadb"], Record, Any]:
        return DeclarationColumn(
            self._dual_row, self._dual_name, self._dual_row.backend
        )

    def __copy__(self) -> Any:
        # Alias roles copy the completed native descriptor, not its binding lease.
        clone = object.__new__(self._dual_native_type)
        for name, value in vars(self).items():
            if not name.startswith("_dual_"):
                object.__setattr__(clone, name, value)
        return clone


class _LazyJsonColumn(_LazyColumn, JsonAttr[Any, Any, Any, Any, Any]):
    """Keep native JSON methods on the canonical descriptor itself."""


class _InputColumn:
    """An input field is not a SQL query source; use its complete row class."""


class Descriptor[Value](FieldDefinition[Value]):
    """Direct native expressions on a complete class, logical values on instances."""

    def __init__(self, declaration: Declaration) -> None:
        super().__init__(declaration)
        self._columns: dict[type[Record], _LazyColumn]
        self._lock: RLock
        object.__setattr__(self, "_columns", {})
        object.__setattr__(self, "_lock", RLock())

    def _column(self, owner: type[Record]) -> _LazyColumn:
        with self._lock:
            if owner not in self._columns:
                self._columns[owner] = (
                    _LazyJsonColumn
                    if issubclass(self.declaration.attribute_type, JsonAttr)
                    else _LazyColumn
                )(owner, self.name)
            return self._columns[owner]

    @contextmanager
    def native_binding(self, owner: type[object], column: Any) -> Iterator[Any]:
        if not (issubclass(owner, ReadRow) and issubclass(owner, Record)):
            raise native.ModelDeclarationError("Native binding requires a complete row")
        canonical = self._column(owner)
        object.__getattribute__(canonical, "__dict__").update(vars(column))
        object.__setattr__(canonical, "_dual_native_type", type(column))
        object.__setattr__(canonical, "_dual_building", get_ident())
        try:
            yield canonical
        finally:
            object.__setattr__(canonical, "_dual_building", None)

    def _access(self, instance: Values | None, owner: type[object]) -> Any:
        if instance is not None:
            return self.instance_value(instance)
        if not (issubclass(owner, ReadRow) and issubclass(owner, Record)):
            return _InputColumn()
        # The immutable declaration and Row-bound overload fix owner and value.
        # Runtime binding checks storage and returns the corresponding native Attr.
        return self._column(owner)

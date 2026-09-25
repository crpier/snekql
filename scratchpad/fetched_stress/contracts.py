"""Throwaway nested declaration adapter reusing native-backed storage finalization."""

from annotationlib import Format, ForwardRef, get_annotations
from collections.abc import Mapping
from dataclasses import replace
from types import MappingProxyType, UnionType
from typing import Any, ClassVar, Protocol, evaluate_forward_ref, get_args, get_origin

from snekql import sqlite as native

from scratchpad.dual_backends import mariadb as maria_backend
from scratchpad.dual_backends import sqlite as sqlite_backend
from scratchpad.dual_features.records import Record as Values
from scratchpad.dual_finalization.interface import Definition, Record
from scratchpad.dual_storage.interface import Field as StorageField
from scratchpad.dual_storage.interface import ForeignField as StorageForeignField
from scratchpad.dual_storage.interface import (
    Omitted,
    ReadRow,
    _without_omitted,
    required,
)
from scratchpad.fetched_first.sqlite import ContractMeta
from scratchpad.row_first.sqlite import InputDefault, _field_type, _generated


class Paired[Result](Protocol):
    @property
    def values(self) -> Mapping[str, object]: ...
    @property
    def __row__(self) -> type[Result]: ...


class Pending(Values, metaclass=ContractMeta):
    """Independent value contract. Only the enclosing row binds its fields."""

    _input_contract: ClassVar[Any]
    _input_annotations: ClassVar[Any]
    _input_defaults: ClassVar[Any]
    _row_target: ClassVar[Any]
    fields: ClassVar[Any]
    backend: ClassVar[str]

    def __init_subclass__(cls) -> None:
        pass

    @classmethod
    def _prepare(
        cls, provided: Mapping[str, object], *, for_insert: bool = False
    ) -> dict[str, object]:
        from scratchpad.row_first.sqlite import _prepare_input

        if not vars(cls).get("_finalized", False):
            raise native.ModelDeclarationError("Bind Pending to an enclosing row")
        return _prepare_input(cls, provided, for_insert=for_insert)


class Row(Record, ReadRow, metaclass=ContractMeta):
    """Concrete backend subclasses supply the source witness and declaration family."""

    _read_contract: ClassVar[Any]

    def __init_subclass__(cls) -> None:
        # Backend bases have no Pending contract; concrete models must declare one.
        if cls.__module__ in {
            "scratchpad.fetched_stress.sqlite",
            "scratchpad.fetched_stress.mariadb",
        }:
            return
        _declare(cls)

    @classmethod
    def _prepare(
        cls, provided: Mapping[str, object], *, for_insert: bool = False
    ) -> dict[str, object]:
        return dict(cls._read_contract._prepare(provided, for_insert=for_insert))


def _foreign_resolver(row: Any, pending: Any, name: str, resolve: Any) -> Any:
    """Compare concrete owner identities after deferred class names are available."""

    def target() -> Any:
        column = resolve()
        for owner in (row, pending):
            annotation = get_annotations(owner, format=Format.FORWARDREF)[name]
            declared = get_args(annotation)[-2]
            if isinstance(declared, ForwardRef):
                declared = evaluate_forward_ref(
                    declared, owner=owner, locals={row.__name__: row}
                )
            if declared is not column.owner:
                raise native.ModelDeclarationError(
                    "Pending and row foreign targets must agree"
                )
        domains = [
            set(get_args(logical)) - {type(None)}
            if get_origin(logical) is UnionType
            else {logical}
            for logical in (row.logical[name], column.owner.logical[column.name])
        ]
        if domains[0] != domains[1]:
            raise native.ModelDeclarationError("Foreign logical domains must agree")
        return column

    return target


def _declare(row: Any) -> None:
    """Bind independent constructors now; defer only FK target identity to graph use."""
    if any("Pending" in vars(base) for base in row.__mro__[1:]):
        raise native.ModelDeclarationError(
            "Concrete row inheritance is outside this experiment"
        )
    backend: Any = sqlite_backend if row.backend == "sqlite" else maria_backend
    pending = vars(row).get("Pending")
    if not isinstance(pending, type) or not issubclass(pending, Pending):
        raise native.ModelDeclarationError("Declare a nested Pending contract")
    if pending.backend != row.backend:
        raise native.ModelDeclarationError(
            "Nested input belongs to another Backend Family"
        )
    hints = get_annotations(pending, format=Format.FORWARDREF)
    witness = hints.pop("__row__", None)
    if (
        get_origin(witness) is not ClassVar
        or get_origin(get_args(witness)[0]) is not type
    ):
        raise native.ModelDeclarationError("Pending needs a ClassVar row witness")
    target = get_args(get_args(witness)[0])[0]
    if isinstance(target, ForwardRef):
        target = evaluate_forward_ref(target, owner=pending, locals={row.__name__: row})
    if target is not row:
        raise native.ModelDeclarationError("Pending must name its enclosing row")
    annotations = {
        name: annotation
        for name, annotation in get_annotations(row, format=Format.FORWARDREF).items()
        if isinstance(origin := get_origin(annotation), type)
        and issubclass(origin, StorageField)
    }
    if set(hints) != set(annotations):
        raise native.ModelDeclarationError("Repeat every row field in Pending")
    fields: dict[str, Any] = {}
    input_fields: dict[str, Any] = {}
    defaults: dict[str, object] = {}
    for name, annotation in annotations.items():
        descriptor = vars(row).get(name)
        if not isinstance(descriptor, StorageField):
            raise native.ModelDeclarationError("Rows own storage declarations")
        logical = get_args(annotation)[-1]
        input_annotation = hints[name]
        if Omitted in get_args(logical):
            raise native.ModelDeclarationError("Complete rows cannot contain Omitted")
        if (
            get_origin(input_annotation) is not get_origin(annotation)
            or _without_omitted(get_args(input_annotation)[-1]) != logical
        ):
            raise native.ModelDeclarationError(
                "Pending must preserve field kind and logical type"
            )
        declaration = descriptor.declaration
        if isinstance(descriptor, StorageForeignField):
            declaration = replace(
                declaration,
                target=_foreign_resolver(row, pending, name, declaration.target),
            )
        fields[name] = type(descriptor)(declaration)
        input_fields[name] = type(descriptor)(declaration)
        marker = vars(pending).get(name)
        if marker is not None:
            if not isinstance(marker, InputDefault):
                raise native.ModelDeclarationError(
                    "Pending changes defaults, not storage"
                )
            defaults[name] = marker.value
            from scratchpad.dual_storage.interface import OMIT

            if marker.value is OMIT:
                if not _generated(descriptor) or Omitted not in get_args(
                    get_args(input_annotation)[-1]
                ):
                    raise native.ModelDeclarationError(
                        "Only generated fields may be omitted"
                    )
            else:
                input_fields[name] = type(descriptor)(
                    replace(declaration, default=marker.value)
                )

    def contract(name: str, fields: dict[str, Any], hints: dict[str, Any]) -> Any:
        return type(
            name,
            (backend.Input,),
            {
                "__module__": row.__module__,
                "__annotations__": {
                    field: _field_type(annotation, get_args(annotation)[-1] | Omitted)
                    if _generated(fields[field])
                    else annotation
                    for field, annotation in hints.items()
                },
                **fields,
            },
        )

    storage = contract(f"_{row.__name__}StorageValues", fields, annotations)
    complete = type(
        f"_{row.__name__}Complete",
        (storage, backend.Model),
        {
            "__module__": row.__module__,
            "__annotations__": annotations,
            **{name: required() for name in fields},
        },
    )
    row._read_contract = complete
    row.fields = complete.fields
    row.logical = complete.logical
    row.refined = complete.refined
    row._definition = Definition(row)
    pending._input_contract = contract(
        f"_{row.__name__}PendingValues", input_fields, hints
    )
    pending._input_annotations = MappingProxyType(hints)
    pending._input_defaults = MappingProxyType(defaults)
    pending._row_target = row
    pending.fields = pending._input_contract.fields
    for name, descriptor in pending.fields.items():
        setattr(pending, name, descriptor)
    pending.__row__ = row
    pending._finalized = True
    row._finalized = True

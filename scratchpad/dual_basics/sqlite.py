"""Research SQLite namespace using the agreed model and row names."""

from annotationlib import Format, get_annotations
from typing import Literal, get_origin

from snekql.sqlite import DoNothing

from scratchpad.dual_backends.core import DoUpdate as BaseDoUpdate
from scratchpad.dual_backends.sqlite import (
    OMIT,
    Field,
    ForeignField,
    ForeignKey,
    Integer,
    Omitted,
    Select,
    Text,
    Transaction,
    insert_using,
    scaffold,
    select,
)
from scratchpad.dual_backends.sqlite import (
    Input as BaseModel,
)
from scratchpad.dual_backends.sqlite import (
    Model as Row,
)
from scratchpad.dual_basics.runtime import Database
from scratchpad.dual_storage.interface import FieldDefinition as BaseField
from scratchpad.dual_storage.interface import required

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
    "Select",
    "Text",
    "Transaction",
    "insert_using",
    "scaffold",
    "select",
]


class Model(BaseModel):
    """An annotation-only override requires a value but retains inherited storage."""

    def __init_subclass__(cls) -> None:
        for name, annotation in get_annotations(cls, format=Format.FORWARDREF).items():
            origin = get_origin(annotation)
            if (
                name not in vars(cls)
                and isinstance(origin, type)
                and issubclass(origin, BaseField)
                and any(name in getattr(base, "fields", {}) for base in cls.__mro__[1:])
            ):
                setattr(cls, name, required())
        super().__init_subclass__()


class DoUpdate[Owner](BaseDoUpdate[Literal["sqlite"], Owner]):
    """Update only explicitly assigned columns when an insertion conflicts."""

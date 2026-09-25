"""Input-first SQLite pairs with the original column vocabulary."""

from typing import Any, dataclass_transform

from snekql import sqlite as native

from scratchpad.dual_backends.core import capture
from scratchpad.dual_pairing.sqlite import (
    OMIT,
    Database,
    DoUpdate,
    ForeignKey,
    Integer,
    Omitted,
    Row,
    Text,
    Transaction,
    insert,
    paired,
    scaffold,
    select,
)
from scratchpad.dual_pairing.sqlite import Field as Col
from scratchpad.dual_pairing.sqlite import ForeignField as FKCol
from scratchpad.dual_pairing.sqlite import Model as BaseModel
from scratchpad.dual_storage.interface import required


def Blob() -> Col[Any]:
    return Col(capture("sqlite", native.Blob()))


@dataclass_transform(
    field_specifiers=(Integer, Text, Blob, ForeignKey, required),
    frozen_default=True,
    kw_only_default=True,
)
class Model(BaseModel):
    """Include the additional Blob constructor in the checked input signature."""


__all__ = [
    "OMIT",
    "Blob",
    "Col",
    "Database",
    "DoUpdate",
    "FKCol",
    "ForeignKey",
    "Integer",
    "Model",
    "Omitted",
    "Row",
    "Text",
    "Transaction",
    "insert",
    "paired",
    "scaffold",
    "select",
]

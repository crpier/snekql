"""Comparison-only native column names; constructors and descriptors are unchanged."""

from scratchpad.fetched_stress.sqlite import (
    OMIT,
    Blob,
    Database,
    DoUpdate,
    ForeignKey,
    Integer,
    Omitted,
    Pending,
    Row,
    Text,
    Transaction,
    default,
    insert,
    omitted,
    scaffold,
    select,
)
from scratchpad.fetched_stress.sqlite import Field as Col
from scratchpad.fetched_stress.sqlite import ForeignField as FKCol

__all__ = [
    "OMIT",
    "Blob",
    "Col",
    "Database",
    "DoUpdate",
    "FKCol",
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

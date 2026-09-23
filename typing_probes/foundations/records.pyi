"""Separate ordinary Python data contracts from SQL expression objects."""

# Retain explanatory docstrings and explicit owner/input invariance.
# ruff: noqa: PYI021, UP046

from collections.abc import Callable
from typing import Generic, TypeVar

from typing_probes.foundations.core import Column, Deleting, Query, Updating, Write

_Row = TypeVar("_Row")
_Input = TypeVar("_Input")

class Table(Generic[_Row, _Input]):
    def __init__(self, row_type: type[_Row], insert_type: type[_Input]) -> None: ...
    def column[Value](
        self, selector: Callable[[_Row], Value]
    ) -> Column[_Row, Value]: ...
    def select(self) -> Query[_Row, _Row]: ...
    def insert(self, row: _Input) -> Write[_Row]: ...
    def update(self) -> Updating[_Row]: ...
    def delete(self) -> Deleting[_Row]: ...

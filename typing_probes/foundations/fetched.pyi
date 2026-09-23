"""Fetched-only models move insert intent out of row construction."""

# Research contracts retain explanatory docstrings.
# ruff: noqa: PYI021

from typing import dataclass_transform, overload

from typing_probes.foundations.core import (
    Assignment,
    Column,
    Deleting,
    Query,
    Updating,
    Write,
)

class Field[Value]:
    @overload
    def __get__[Owner](
        self, instance: None, owner: type[Owner]
    ) -> Column[Owner, Value]: ...
    @overload
    def __get__(self, instance: object, owner: type[object]) -> Value: ...
    def __set__(self, instance: object, value: Value) -> None: ...

def field[Value]() -> Field[Value]: ...

@dataclass_transform(field_specifiers=(field,), kw_only_default=True)
class Model: ...

def select[Owner](model: type[Owner]) -> Query[Owner, Owner]: ...
def insert[Owner](
    model: type[Owner], first: Assignment[Owner], *rest: Assignment[Owner]
) -> Write[Owner]: ...
def update[Owner](model: type[Owner]) -> Updating[Owner]: ...
def delete[Owner](model: type[Owner]) -> Deleting[Owner]: ...

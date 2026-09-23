"""Throwaway signature experiment, not a runtime UNION implementation."""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

class Expr[T](Protocol):
    def value(self) -> T: ...

@dataclass(frozen=True)
class Fields[IdT, TitleT]:
    event_id: Expr[IdT]
    title: Expr[TitleT]

@dataclass(frozen=True)
class DifferentFields[IdT]:
    event_id: Expr[IdT]

class Query[LayoutT]:
    def __init__(self, layout: LayoutT) -> None: ...
    def union_all[OtherLayoutT](
        self, other: Query[OtherLayoutT]
    ) -> Combined[LayoutT, OtherLayoutT]: ...

class Combined[LeftT, RightT]:
    def column[T](self, choose: Callable[[LeftT | RightT], Expr[T]]) -> Expr[T]: ...
    def union_all[OtherT](
        self, other: Query[OtherT]
    ) -> Combined[LeftT | RightT, OtherT]: ...

def integer() -> Expr[int]: ...
def optional_integer() -> Expr[int | None]: ...
def text() -> Expr[str]: ...
def optional_text() -> Expr[str | None]: ...

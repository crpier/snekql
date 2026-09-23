"""Throwaway wide layout; compound methods remain entirely generic."""

from dataclasses import dataclass
from typing import Self

from layout_union import Expr

class WideSchema: ...

@dataclass(frozen=True)
class WideFields[
    T0: int | None,
    T1: int | None,
    T2: int | None,
    T3: int | None,
    T4: int | None,
    T5: int | None,
    T6: int | None,
    T7: int | None,
    T8: int | None,
    T9: int | None,
    T10: int | None,
    T11: int | None,
]:
    field_0: Expr[T0]
    field_1: Expr[T1]
    field_2: Expr[T2]
    field_3: Expr[T3]
    field_4: Expr[T4]
    field_5: Expr[T5]
    field_6: Expr[T6]
    field_7: Expr[T7]
    field_8: Expr[T8]
    field_9: Expr[T9]
    field_10: Expr[T10]
    field_11: Expr[T11]
    def schema(self, schema: WideSchema) -> WideSchema: ...
    def layout(self) -> Self: ...

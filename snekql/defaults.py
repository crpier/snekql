"""Explicit markers for database-supplied literal values."""

from dataclasses import dataclass

from snekql.errors import ModelDeclarationError


@dataclass(frozen=True)
class LiteralDefault[T]:
    """Supply a constant when an INSERT omits a generated column.

    Pass the marker as `default`, rather than using a Python constructor default:

    ```python
    from typing import ClassVar

    from snekql import sqlite


    class Entry[S = sqlite.Pending](sqlite.Model[S]):
        __row_type__: ClassVar[sqlite.ReadType[Entry[sqlite.Row]]]
        attempts: sqlite.GenCol[int] = sqlite.Integer(default=sqlite.LiteralDefault(0))
    ```
    """

    value: T

    def __post_init__(self) -> None:
        if type(self.value) not in (int, bool, str, type(None)):
            msg = "LiteralDefault accepts only integer, Boolean, text, or None values"
            raise ModelDeclarationError(msg)

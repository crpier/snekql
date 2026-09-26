"""Model declared WITHOUT `from __future__ import annotations`.

Regression fixture for issue #143: under PEP 649/749 (default in 3.14) the
class namespace carries a deferred `__annotate__` function instead of a
materialized `__annotations__` dict. Generated-column detection must still
work, so this module deliberately omits the future import.
"""

from typing import ClassVar

from snekql.sqlite import (
    CurrentTimestamp,
    Model,
    Pending,
    ReadType,
    Row,
    Text,
    UtcDatetime,
)


class Memory[S = Pending](Model[S]):
    """Model whose server-default column requires GenCol detection."""

    __row_type__: ClassVar[ReadType[Memory[Row]]]

    created_at: Memory.GenCol[UtcDatetime] = Text(default=CurrentTimestamp)

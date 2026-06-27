"""Model declared WITHOUT `from __future__ import annotations`.

Regression fixture for issue #143: under PEP 649/749 (default in 3.14) the
class namespace carries a deferred `__annotate__` function instead of a
materialized `__annotations__` dict. Generated-column detection must still
work, so this module deliberately omits the future import.
"""

from datetime import datetime

from snekql.sqlite import CurrentTimestamp, Fetched, Model, Pending, Text


class Memory[S = Pending](Model[S, "Memory[Fetched]"]):
    """Model whose server-default column requires GenCol detection."""

    created_at: Memory.GenCol[datetime] = Text(default=CurrentTimestamp)

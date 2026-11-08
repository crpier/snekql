"""Experimental #599 policies; not snekql exports or automatic write hooks."""

from datetime import datetime
from decimal import Decimal
from typing import Annotated

from pydantic import Field, TypeAdapter

_DECIMAL_5_2 = TypeAdapter(
    Annotated[Decimal, Field(max_digits=5, decimal_places=2, allow_inf_nan=False)]
)


def require_decimal_5_2(value: object) -> object:
    """Check a deliberately narrow Decimal/text parameter; do not change it."""
    if not isinstance(value, Decimal | str):
        msg = "this exact-decimal parameter policy supports only Decimal or text"
        raise TypeError(msg)
    _DECIMAL_5_2.validate_python(value)
    return value


def require_milliseconds(value: datetime) -> datetime:
    """Reject, rather than truncate, fractions that milliseconds cannot retain."""
    if value.microsecond % 1000:
        msg = "datetime fraction cannot be preserved at millisecond precision"
        raise ValueError(msg)
    return value

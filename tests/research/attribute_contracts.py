"""Research-only explicit storage contracts for #596, not library exports."""

from datetime import date
from typing import Annotated

from pydantic import BeforeValidator, Strict, StrictBool


def _bool01(value: object) -> object:
    if type(value) is int and value in (0, 1):
        return bool(value)
    return value


def _canonical_date(value: object) -> object:
    if isinstance(value, str):
        parsed = date.fromisoformat(value)
        if parsed.isoformat() != value:
            msg = "expected canonical YYYY-MM-DD text"
            raise ValueError(msg)
        return parsed
    return value


SqlBool01 = Annotated[StrictBool, BeforeValidator(_bool01)]
CanonicalSqlDate = Annotated[date, Strict(), BeforeValidator(_canonical_date)]

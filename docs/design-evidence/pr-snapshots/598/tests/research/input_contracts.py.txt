"""Research-only read policies, exercised through public TypeAdapter (#596)."""

from datetime import UTC, datetime

from pydantic import TypeAdapter, ValidationInfo

from snekql.sqlite import LocalDatetime, UtcDatetime

_UTC_WIRE = TypeAdapter(UtcDatetime)


def sql_bool01(value: object) -> object:
    if type(value) is int and value in (0, 1):
        return bool(value)
    return value


def utc_text(value: object) -> object:
    if isinstance(value, str):
        return _UTC_WIRE.validate_python(value, strict=None)
    return value


def utc_fields(value: object) -> object:
    if isinstance(value, datetime) and value.tzinfo is None and value.fold == 0:
        return UtcDatetime(value.replace(tzinfo=UTC))
    return value


def civil_fields(value: object) -> object:
    if isinstance(value, datetime) and value.tzinfo is None and value.fold == 0:
        return LocalDatetime(value)
    return value


SQL_CELL_READ = object()


def contextual_bool01(value: object, info: ValidationInfo) -> object:
    if info.context is SQL_CELL_READ:
        return sql_bool01(value)
    return value

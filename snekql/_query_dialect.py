"""Backend Dialect facts used by Query Builder SQL compilation."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from snekql.storage import Attr

type QueryColumn = Attr[Any, Any, Any, Any, Any]
type QueryValueEncoder = Callable[[QueryColumn, object], object]


@dataclass(frozen=True)
class QueryDialect:
    """Small Dialect seam for compiling shared query state into backend SQL."""

    current_timestamp_sql: str
    empty_insert_sql: Callable[[str], str]
    encode_column_value: QueryValueEncoder
    placeholder: str
    quote_identifier: Callable[[str], str]

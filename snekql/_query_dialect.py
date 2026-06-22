"""Backend Dialect facts used by Query Builder SQL compilation."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from snekql.errors import QueryCompilationError
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


# Backend-family -> Dialect registry. The core stays dialect-blind (ADR 0004):
# it never imports a Backend Namespace, so each namespace registers its own
# Dialect here on import. This lets a built query render its own SQL for
# inspection by looking up the Dialect for its model's backend, without a
# Database having injected one.
_QUERY_DIALECTS: dict[str, QueryDialect] = {}


def register_query_dialect(backend: str, dialect: QueryDialect) -> None:
    """Register a backend family's query Dialect for SQL inspection."""

    _QUERY_DIALECTS[backend] = dialect


def query_dialect_for_backend(backend: str) -> QueryDialect:
    """Return the registered query Dialect for a backend family.

    Importing a Backend Namespace registers its Dialect, so a built query whose
    model belongs to that backend can always resolve one. A missing entry means
    the namespace was never imported, which cannot happen for a real query.
    """

    dialect = _QUERY_DIALECTS.get(backend)
    if dialect is None:
        msg = f"no query dialect registered for backend {backend!r}"
        raise QueryCompilationError(msg)
    return dialect

"""Immutable public outcomes from Table Model schema verification."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class SchemaDriftIssue:
    """One live-schema divergence associated with a checked table.

    >>> SchemaDriftIssue("user", "table is missing")
    SchemaDriftIssue(table_name='user', detail='table is missing')
    """

    table_name: str
    detail: str


@dataclass(frozen=True, slots=True)
class SchemaVerificationResult:
    """Ordered tables checked and every Schema Drift issue discovered.

    >>> SchemaVerificationResult(checked_tables=("user",), issues=())
    SchemaVerificationResult(checked_tables=('user',), issues=())
    """

    checked_tables: tuple[str, ...]
    issues: tuple[SchemaDriftIssue, ...]

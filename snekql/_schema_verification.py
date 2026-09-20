"""Immutable public outcomes from Table Model schema verification."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True, slots=True)
class SchemaDriftIssue:
    """One live-schema divergence associated with a checked table.

    >>> SchemaDriftIssue("user", "table is missing")
    SchemaDriftIssue(table_name='user', detail='table is missing')
    """

    table_name: str
    detail: str


@dataclass(frozen=True, slots=True)
class SchemaVerificationFact:
    """One compared property or explicitly unchecked verification scope.

    `object_name` names a column or index, or is None for a table-wide fact.
    `kind` is a machine-readable code; `detail` is human-readable evidence.
    Unchecked facts do not assert that an uninspected feature exists or is absent.
    """

    table_name: str
    object_name: str | None
    kind: str
    status: Literal["matched", "drift", "unchecked"]
    detail: str


@dataclass(frozen=True, slots=True)
class SchemaVerificationResult:
    """Ordered checked tables, drift issues, and immutable comparison evidence.

    `facts` separates matched properties, drift, and known unchecked scope.
    Unchecked scope does not claim live feature presence or trigger schema policy.

    >>> SchemaVerificationResult(checked_tables=("user",), issues=())
    SchemaVerificationResult(checked_tables=('user',), issues=(), facts=())
    """

    checked_tables: tuple[str, ...]
    issues: tuple[SchemaDriftIssue, ...]
    facts: tuple[SchemaVerificationFact, ...] = ()

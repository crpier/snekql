"""Bound-parameter visibility policy for logs and exception text."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from typing import Literal

type ParameterVisibility = Literal["redacted", "values"]


def fingerprint_sql(backend: Literal["sqlite", "mariadb"], sql: str) -> str:
    """Hash parameterized SQL without examining bound values or retaining a cache."""
    digest = sha256((backend + "\0" + sql).encode("utf-8")).hexdigest()
    return f"v1:{digest}"


def format_bound_params(
    params: tuple[object, ...],
    visibility: ParameterVisibility,
) -> str:
    """Render values only after an explicit unsafe opt-in."""

    if visibility == "values":
        return repr(params)
    return f"<redacted:{len(params)}>"


@dataclass(frozen=True)
class QueryDiagnostics:
    """Plan-owned diagnostics, separate from the actual driver execution inputs.

    Builders supply SQL context. Raw plans supply fixed safe data and require
    suppressed driver exception chaining. Neither policy infers an SQL verb.
    """

    failure_message: str
    params: tuple[object, ...]
    sql: str
    raw: bool = False

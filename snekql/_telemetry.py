"""Bound-parameter visibility policy for logs and exception text."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

type ParameterVisibility = Literal["redacted", "values"]


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

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
    """Builder-owned diagnostic context, separate from driver execution inputs.

    Execution plans supply the message and statement context. The runtime must
    not infer an SQL verb to choose either the error message or diagnostic data.
    """

    failure_message: str
    params: tuple[object, ...]
    sql: str

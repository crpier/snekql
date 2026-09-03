"""Bound-parameter visibility policy for logs and exception text."""

from __future__ import annotations

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

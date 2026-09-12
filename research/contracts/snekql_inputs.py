"""Application input policy stricter than Python's bool-is-an-int relationship."""

from typing import Any

from pydantic import TypeAdapter, ValidationError

from snekql.errors import ModelValidationError


def validate_integer_inputs(supplied: dict[str, Any]) -> None:
    """Run before model construction, which intentionally converts bool to int."""
    adapter = TypeAdapter(int)
    for name in ("price_cents", "quantity"):
        if name in supplied:
            try:
                adapter.validate_python(supplied[name], strict=True)
            except ValidationError as e:
                msg = f"{name}: {e}"
                raise ModelValidationError(msg) from e

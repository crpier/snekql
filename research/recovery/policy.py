"""Added application policy, deliberately separate from native library behavior."""

from typing import Annotated, Any

from pydantic import Field, TypeAdapter

type Quantity = Annotated[int, Field(strict=True, gt=0)]


def validate_patch(supplied: dict[str, Any]) -> None:
    """Omission is allowed; a supplied quantity must be an actual positive int."""
    if "quantity" in supplied:
        TypeAdapter(Quantity).validate_python(supplied["quantity"])

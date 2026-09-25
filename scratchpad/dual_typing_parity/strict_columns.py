"""A typed Python-default experiment, not a complete Column Type namespace."""

from typing import Any, dataclass_transform, overload

from scratchpad.dual_storage.interface import required
from scratchpad.paired_situations.dual_sqlite import (
    Col,
    ForeignKey,
    Integer,
    Row,
)
from scratchpad.paired_situations.dual_sqlite import Model as OriginalModel
from scratchpad.paired_situations.dual_sqlite import Text as OriginalText


@overload
def Text[Value](*, default: Value, unique: bool = False) -> Col[Value]: ...
@overload
def Text(*, unique: bool = False) -> Col[Any]: ...
def Text(*, default: Any = ..., unique: bool = False) -> Col[Any]:
    """Preserve a supplied default's logical type instead of returning Col[Any]."""
    return OriginalText(default=default, unique=unique)


@dataclass_transform(
    field_specifiers=(Integer, Text, ForeignKey, required),
    frozen_default=True,
    kw_only_default=True,
)
class Model(OriginalModel):
    """Expose the alternative Text constructor to dataclass-transform checking."""


__all__ = ["Col", "ForeignKey", "Integer", "Model", "Row", "Text"]

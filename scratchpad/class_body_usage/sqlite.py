"""Witness-only increment: keep native construction and specialization behavior."""

from typing import Any, ClassVar

from snekql import sqlite as native
from snekql.model import _MODEL_BASE_MARKER

from scratchpad.state_declarations.sqlite import ModelMeta, ReadType


class Model[State](native.Model[State, Any], metaclass=ModelMeta):
    """Reuse only result-annotation validation, not the earlier constructor changes."""

    __snekql_framework_base__: ClassVar[object] = _MODEL_BASE_MARKER


__all__ = ["Model", "ReadType"]

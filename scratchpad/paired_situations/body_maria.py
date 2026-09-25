"""MariaDB equivalent of the witness-only SQLite base; no constructor changes."""

from typing import Any, ClassVar, dataclass_transform

from snekql import mariadb
from snekql.mariadb.model import ModelMeta as NativeMeta
from snekql.model import _MODEL_BASE_MARKER

from scratchpad.state_declarations.sqlite import ModelMeta as WitnessMeta
from scratchpad.state_declarations.sqlite import ReadType


@dataclass_transform(
    field_specifiers=(
        mariadb.Integer,
        mariadb.Text,
        mariadb.Real,
        mariadb.Blob,
        mariadb.Decimal,
        mariadb.Json,
        mariadb.Boolean,
        mariadb.DateTime,
        mariadb.Uuid,
        mariadb.ForeignKey,
    ),
    kw_only_default=True,
)
class ModelMeta(WitnessMeta, NativeMeta):
    """Reuse witness validation while retaining MariaDB's constructor typing."""


class Model[State](mariadb.Model[State, Any], metaclass=ModelMeta):
    __snekql_framework_base__: ClassVar[object] = _MODEL_BASE_MARKER


__all__ = ["Model", "ReadType"]

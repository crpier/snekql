"""SQLite Table Model declaration base and backend-pinned column aliases."""

from __future__ import annotations

from typing import Any, ClassVar, Literal, TypeVar, dataclass_transform

from snekql.indexes import NormalizedIndex
from snekql.model import _MODEL_BASE_MARKER, Fetched, Pending, Table
from snekql.model import Model as BaseModel
from snekql.model import ModelMeta as BaseModelMeta
from snekql.storage import (
    Attr,
    Blob,
    ForeignKey,
    Integer,
    PendingGeneration,
    Real,
    Text,
    _UnboundOwner,
)
from snekql.storage import FKAttr as _FKAttr

StateT = TypeVar("StateT")
ReadModelT = TypeVar("ReadModelT", bound=Table[Any])


@dataclass_transform(
    field_specifiers=(Integer, Real, Text, Blob, ForeignKey),
    kw_only_default=True,
)
class ModelMeta(BaseModelMeta):
    """Typing hook for SQLite-specific Table Model declarations."""


class Model[StateT, ReadModelT: Table[Any]](
    BaseModel[StateT, ReadModelT],
    metaclass=ModelMeta,
):
    """SQLite Table Model base for backend-specific declarations."""

    __snekql_backend__: ClassVar[Literal["sqlite"]] = "sqlite"
    __snekql_columns__: ClassVar[dict[str, Attr[Any, Any, Any, Any, Any]]]
    __snekql_framework_base__: ClassVar[object] = _MODEL_BASE_MARKER
    __snekql_indexes__: ClassVar[tuple[NormalizedIndex, ...]]
    __tablename__: ClassVar[str]

    type Col[T] = Attr[Table[Pending], Table[Fetched], _UnboundOwner, T, T]
    type GenCol[T] = Attr[
        Table[Pending],
        Table[Fetched],
        _UnboundOwner,
        T | PendingGeneration,
        T,
    ]
    type FKCol[Target: Model[Any, Any], T] = _FKAttr[
        Table[Pending],
        Table[Fetched],
        _UnboundOwner,
        T,
        T,
        Target,
    ]

    @classmethod
    def __backend_family_type__(cls) -> Literal["sqlite"]:
        """Typing-only witness for backend-family propagation."""

        return "sqlite"


type Col[T] = Attr[Table[Pending], Table[Fetched], _UnboundOwner, T, T]
type GenCol[T] = Attr[
    Table[Pending], Table[Fetched], _UnboundOwner, T | PendingGeneration, T
]
type FKCol[Target: Model[Any, Any], T] = _FKAttr[
    Table[Pending],
    Table[Fetched],
    _UnboundOwner,
    T,
    T,
    Target,
]

__all__ = ["Col", "FKCol", "GenCol", "Model", "ModelMeta"]

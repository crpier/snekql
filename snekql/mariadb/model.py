"""MariaDB table model declaration base."""

from __future__ import annotations

from typing import Any, ClassVar, Literal, TypeVar, dataclass_transform

from snekql.indexes import NormalizedIndex
from snekql.mariadb.storage import (
    Blob,
    Boolean,
    DateTime,
    Decimal,
    Integer,
    Json,
    JsonAttr,
    Real,
    Text,
    Uuid,
)
from snekql.model import Fetched, Pending, Table
from snekql.model import Model as BaseModel
from snekql.model import ModelMeta as BaseModelMeta
from snekql.storage import Attr, ForeignKey, _UnboundOwner

StateT = TypeVar("StateT")
ReadModelT = TypeVar("ReadModelT", bound=Table[Any])


type JsonCol[T] = JsonAttr[
    Table[Pending],
    Table[Fetched],
    _UnboundOwner,
    T,
    T,
]


@dataclass_transform(
    field_specifiers=(
        Integer,
        Real,
        Text,
        Blob,
        Decimal,
        Json,
        Boolean,
        DateTime,
        Uuid,
        ForeignKey,
    ),
    kw_only_default=True,
)
class ModelMeta(BaseModelMeta):
    """Typing hook for MariaDB-specific column declaration functions."""


class Model[StateT, ReadModelT: Table[Any]](
    BaseModel[StateT, ReadModelT],
    metaclass=ModelMeta,
):
    """MariaDB table model base for backend-specific declarations.

    >>> class User[S = Pending](Model[S, "User[Fetched]"]):
    ...     email: Col[str] = Text()
    """

    __snekql_backend__: ClassVar[Literal["mariadb"]] = "mariadb"
    __snekql_columns__: ClassVar[dict[str, Attr[Any, Any, Any, Any, Any]]]
    __snekql_indexes__: ClassVar[tuple[NormalizedIndex, ...]]
    __tablename__: ClassVar[str]

    type JsonCol[T] = JsonAttr[Table[Pending], Table[Fetched], _UnboundOwner, T, T]


__all__ = ["JsonCol", "Model", "ModelMeta"]

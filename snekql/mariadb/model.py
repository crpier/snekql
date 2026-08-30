"""MariaDB table model declaration base."""

from __future__ import annotations

from typing import Any, ClassVar, Literal, TypeVar

from snekql.indexes import NormalizedIndex
from snekql.mariadb.storage import JsonAttr
from snekql.model import Fetched, ModelMeta, Pending, Table
from snekql.model import Model as BaseModel
from snekql.storage import Attr

StateT = TypeVar("StateT")
ReadModelT = TypeVar("ReadModelT", bound=Table[Any])


type JsonCol[OwnerT: Table[Any], T] = JsonAttr[
    Table[Pending],
    Table[Fetched],
    OwnerT,
    T,
    T,
]


class Model[StateT, ReadModelT: Table[Any]](BaseModel[StateT, ReadModelT]):
    """MariaDB table model base for backend-specific declarations.

    >>> class User[S = Pending](Model[S, "User[Fetched]"]):
    ...     email: User.Col[str] = Text(nullable=False)
    """

    __snekql_backend__: ClassVar[Literal["mariadb"]] = "mariadb"
    __snekql_columns__: ClassVar[dict[str, Attr[Any, Any, Any, Any, Any]]]
    __snekql_indexes__: ClassVar[tuple[NormalizedIndex, ...]]
    __tablename__: ClassVar[str]

    type JsonCol[OwnerT: Table[Any], T] = JsonAttr[
        Table[Pending], Table[Fetched], OwnerT, T, T
    ]


__all__ = ["JsonCol", "Model", "ModelMeta"]

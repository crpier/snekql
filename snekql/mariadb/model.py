"""MariaDB table model declaration base."""

from __future__ import annotations

from typing import Any, ClassVar, TypeVar

from snekql.indexes import NormalizedIndex
from snekql.model import Model as BaseModel
from snekql.model import ModelMeta, Table
from snekql.storage import Attr

StateT = TypeVar("StateT")
ReadModelT = TypeVar("ReadModelT", bound=Table[Any])


class Model[StateT, ReadModelT: Table[Any]](BaseModel[StateT, ReadModelT]):
    """MariaDB table model base for backend-specific declarations.

    >>> class User[S = Pending](Model[S, "User[Fetched]"]):
    ...     email: User.Col[str] = Text(nullable=False)
    """

    __snekql_columns__: ClassVar[dict[str, Attr[Any, Any, Any, Any, Any]]]
    __snekql_indexes__: ClassVar[tuple[NormalizedIndex, ...]]
    __tablename__: ClassVar[str]


__all__ = ["Model", "ModelMeta"]

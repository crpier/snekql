"""MariaDB table model declaration base."""

from __future__ import annotations

from typing import Any, ClassVar, Literal, Self, TypeVar

from snekql.indexes import NormalizedIndex
from snekql.mariadb.storage import JsonAttr
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

    __snekql_backend__: ClassVar[Literal["mariadb"]] = "mariadb"
    __snekql_columns__: ClassVar[dict[str, Attr[Any, Any, Any, Any, Any]]]
    __snekql_indexes__: ClassVar[tuple[NormalizedIndex, ...]]
    __tablename__: ClassVar[str]

    # MariaDB-only JSON column alias: resolves to the JSON column subtype so the
    # dialect JSON path operators are visible on JSON columns only (ADR 0004).
    type JsonCol[T] = JsonAttr[Self, ReadModelT, Self, T, T]


__all__ = ["Model", "ModelMeta"]

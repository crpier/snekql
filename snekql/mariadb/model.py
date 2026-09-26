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
from snekql.model import (
    _MODEL_BASE_MARKER,
    Pending,
    Row,
    Table,
    _complete_model,
    _RowDeclaration,
)
from snekql.model import Model as BaseModel
from snekql.model import ModelMeta as BaseModelMeta
from snekql.storage import (
    Attr,
    FKAttr,
    ForeignKey,
    PendingGeneration,
    _UnboundOwner,
)

StateT = TypeVar("StateT")


type JsonCol[T] = JsonAttr[
    Table[Pending],
    Table[Row],
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
    frozen_default=True,
)
class ModelMeta(BaseModelMeta):
    """Typing hook for MariaDB-specific column declaration functions."""


class Model[StateT](
    BaseModel[StateT],
    metaclass=ModelMeta,
):
    """MariaDB table model base for backend-specific declarations.

    >>> from snekql.mariadb import ReadType
    >>> class User[S = Pending](Model[S]):
    ...     __row_type__: ClassVar[ReadType[User[Row]]]
    ...     email: Col[str] = Text()
    """

    __snekql_backend__: ClassVar[Literal["mariadb"]] = "mariadb"
    __snekql_columns__: ClassVar[dict[str, Attr[Any, Any, Any, Any, Any]]]
    __snekql_framework_base__: ClassVar[object] = _MODEL_BASE_MARKER
    __snekql_indexes__: ClassVar[tuple[NormalizedIndex, ...]]
    __tablename__: ClassVar[str]

    type Col[T] = Attr[Table[Pending], Table[Row], _UnboundOwner, T, T]
    type GenCol[T] = Attr[
        Table[Pending],
        Table[Row],
        _UnboundOwner,
        T | PendingGeneration,
        T,
    ]
    type FKCol[Target: Model[Any], T] = FKAttr[
        Table[Pending],
        Table[Row],
        _UnboundOwner,
        T,
        T,
        Target,
    ]
    type JsonCol[T] = JsonAttr[Table[Pending], Table[Row], _UnboundOwner, T, T]

    @classmethod
    def __backend_family_type__(cls) -> Literal["mariadb"]:
        """Typing-only witness for backend-family propagation."""

        return "mariadb"


type Col[T] = Attr[Table[Pending], Table[Row], _UnboundOwner, T, T]
type GenCol[T] = Attr[
    Table[Pending], Table[Row], _UnboundOwner, T | PendingGeneration, T
]
type FKCol[Target: Model[Any], T] = FKAttr[
    Table[Pending],
    Table[Row],
    _UnboundOwner,
    T,
    T,
    Target,
]


def complete[Result: Table[Row]](
    model: _RowDeclaration[Literal["mariadb"], Result], /, **values: object
) -> Result:
    """Create a validated Row snapshot without database I/O.

    `complete(User, user_id=7, email="Ada")` requires every declared field.
    Keywords are runtime-validated. The result cannot be inserted and does not
    prove that a database row exists.
    """
    return _complete_model(model, values, backend="mariadb")


__all__ = ["Col", "FKCol", "GenCol", "JsonCol", "Model", "ModelMeta", "complete"]

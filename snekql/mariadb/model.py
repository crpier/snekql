"""MariaDB table model declaration base."""

lazy from collections.abc import Mapping
lazy from typing import Any, ClassVar, Literal, Self, TypeVar, dataclass_transform

lazy from snekql.expressions import Aggregate, _Aggregate
lazy from snekql.indexes import NormalizedIndex
lazy from snekql.mariadb.storage import (
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
lazy from snekql.model import (
    _MODEL_BASE_MARKER,
    Pending,
    Row,
    Table,
    _complete_model,
    _RowDeclaration,
)
lazy from snekql.model import Model as BaseModel
lazy from snekql.model import ModelMeta as BaseModelMeta
lazy from snekql.storage import (
    PENDING_GENERATION,
    Attr,
    FKAttr,
    ForeignKey,
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
    __snekql_columns__: ClassVar[Mapping[str, Attr[Any, Any, Any, Any, Any]]]
    __snekql_framework_base__: ClassVar[object] = _MODEL_BASE_MARKER
    __snekql_indexes__: ClassVar[tuple[NormalizedIndex, ...]]
    __tablename__: ClassVar[str]

    type Col[T] = Attr[
        Table[Pending], Table[Row], _UnboundOwner, T, T, T, Any, Literal["mariadb"]
    ]
    type GenCol[T] = Attr[
        Table[Pending],
        Table[Row],
        _UnboundOwner,
        T | PENDING_GENERATION,
        T,
        T | PENDING_GENERATION,
        Any,
        Literal["mariadb"],
    ]
    type FKCol[Target: Model[Any], T] = FKAttr[
        Table[Pending],
        Table[Row],
        _UnboundOwner,
        T,
        T,
        Target,
        T,
        Any,
        Literal["mariadb"],
    ]
    type JsonCol[T] = JsonAttr[Table[Pending], Table[Row], _UnboundOwner, T, T]

    @classmethod
    def count_all(cls) -> Aggregate[Self, int, int, Literal["mariadb"]]:
        """Count rows, preserving the model's backend family."""
        return _Aggregate[Self, int, int, Literal["mariadb"]](
            func="COUNT", column=None, owner=cls
        )

    @classmethod
    def __backend_family_type__(cls) -> Literal["mariadb"]:
        """Typing-only witness for backend-family propagation."""

        return "mariadb"


type Col[T] = Attr[
    Table[Pending], Table[Row], _UnboundOwner, T, T, T, Any, Literal["mariadb"]
]
type GenCol[T] = Attr[
    Table[Pending],
    Table[Row],
    _UnboundOwner,
    T | PENDING_GENERATION,
    T,
    T | PENDING_GENERATION,
    Any,
    Literal["mariadb"],
]
type FKCol[Target: Model[Any], T] = FKAttr[
    Table[Pending], Table[Row], _UnboundOwner, T, T, Target, T, Any, Literal["mariadb"]
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

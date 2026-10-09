"""SQLite Table Model declaration base and backend-pinned column aliases."""

lazy from collections.abc import Mapping
lazy from typing import Any, ClassVar, Literal, Self, TypeVar, dataclass_transform

lazy from snekql.expressions import Aggregate, _Aggregate
lazy from snekql.indexes import NormalizedIndex
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
    Blob,
    ForeignKey,
    Integer,
    Real,
    Text,
    _UnboundOwner,
)
lazy from snekql.storage import FKAttr as _FKAttr

StateT = TypeVar("StateT")


@dataclass_transform(
    field_specifiers=(Integer, Real, Text, Blob, ForeignKey),
    kw_only_default=True,
    frozen_default=True,
)
class ModelMeta(BaseModelMeta):
    """Typing hook for SQLite-specific Table Model declarations."""


class Model[StateT](
    BaseModel[StateT],
    metaclass=ModelMeta,
):
    """SQLite Table Model base for backend-specific declarations."""

    __snekql_backend__: ClassVar[Literal["sqlite"]] = "sqlite"
    __snekql_columns__: ClassVar[Mapping[str, Attr[Any, Any, Any, Any, Any]]]
    __snekql_framework_base__: ClassVar[object] = _MODEL_BASE_MARKER
    __snekql_indexes__: ClassVar[tuple[NormalizedIndex, ...]]
    __tablename__: ClassVar[str]

    type Col[T] = Attr[
        Table[Pending], Table[Row], _UnboundOwner, T, T, T, Any, Literal["sqlite"]
    ]
    type GenCol[T] = Attr[
        Table[Pending],
        Table[Row],
        _UnboundOwner,
        T | PENDING_GENERATION,
        T,
        T | PENDING_GENERATION,
        Any,
        Literal["sqlite"],
    ]
    type FKCol[Target: Model[Any], T] = _FKAttr[
        Table[Pending],
        Table[Row],
        _UnboundOwner,
        T,
        T,
        Target,
        T,
        Any,
        Literal["sqlite"],
    ]

    @classmethod
    def count_all(cls) -> Aggregate[Self, int, int, Literal["sqlite"]]:
        """Count rows, preserving the model's backend family."""
        return _Aggregate[Self, int, int, Literal["sqlite"]](
            func="COUNT", column=None, owner=cls
        )

    @classmethod
    def __backend_family_type__(cls) -> Literal["sqlite"]:
        """Typing-only witness for backend-family propagation."""

        return "sqlite"


type Col[T] = Attr[
    Table[Pending], Table[Row], _UnboundOwner, T, T, T, Any, Literal["sqlite"]
]
type GenCol[T] = Attr[
    Table[Pending],
    Table[Row],
    _UnboundOwner,
    T | PENDING_GENERATION,
    T,
    T | PENDING_GENERATION,
    Any,
    Literal["sqlite"],
]
type FKCol[Target: Model[Any], T] = _FKAttr[
    Table[Pending], Table[Row], _UnboundOwner, T, T, Target, T, Any, Literal["sqlite"]
]


def complete[Result: Table[Row]](
    model: _RowDeclaration[Literal["sqlite"], Result], /, **values: object
) -> Result:
    """Create a validated Row snapshot without database I/O.

    `complete(User, user_id=7, email="Ada")` requires every declared field.
    Keywords are runtime-validated. The result cannot be inserted and does not
    prove that a database row exists.
    """
    return _complete_model(model, values, backend="sqlite")


__all__ = ["Col", "FKCol", "GenCol", "Model", "ModelMeta", "complete"]

"""Public index declarations and normalized model index metadata."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, TypeVar, cast, overload

from snekql.errors import ModelDeclarationError
from snekql.storage import Attr

OwnerT = TypeVar("OwnerT")


@dataclass(frozen=True)
class Index[OwnerT]:
    """Public table-level index declaration.

    >>> class User[S = Pending](Model[S, "User[Fetched]"]):
    ...     email: User.Col[str] = Text(nullable=False)
    ...     __indexes__ = [Index(email)]
    """

    columns: tuple[Attr[Any, Any, OwnerT, Any, Any], ...]
    unique: bool
    name: str | None

    @overload
    def __init__(
        self,
        *columns: Attr[Any, Any, OwnerT, Any, Any],
        unique: bool = False,
        name: str | None = None,
    ) -> None: ...

    @overload
    def __init__(
        self,
        *columns: object,
        unique: bool = False,
        name: str | None = None,
    ) -> None: ...

    def __init__(
        self,
        *columns: object,
        unique: bool = False,
        name: str | None = None,
    ) -> None:
        if not columns:
            msg = "Index() requires at least one column"
            raise ModelDeclarationError(msg)
        seen_column_ids: set[int] = set()
        for column in columns:
            if not isinstance(column, Attr):
                msg = "Index() arguments must be snekql column descriptors"
                raise ModelDeclarationError(msg)
            attr_column = cast("Attr[Any, Any, OwnerT, Any, Any]", column)
            column_id = id(attr_column)
            if column_id in seen_column_ids:
                msg = "Index() cannot repeat a column"
                raise ModelDeclarationError(msg)
            seen_column_ids.add(column_id)
        object.__setattr__(
            self,
            "columns",
            cast("tuple[Attr[Any, Any, OwnerT, Any, Any], ...]", columns),
        )
        object.__setattr__(self, "unique", unique)
        object.__setattr__(self, "name", name)


@dataclass(frozen=True, kw_only=True)
class NormalizedIndex:
    """Immutable model-owned index metadata used by schema startup."""

    column_names: tuple[str, ...]
    name: str
    unique: bool


def require_index_declaration(value: object) -> Index[Any]:
    """Validate a public __indexes__ entry before normalization."""

    if not isinstance(value, Index):
        msg = "__indexes__ entries must be Index declarations"
        raise ModelDeclarationError(msg)
    return cast("Index[Any]", value)

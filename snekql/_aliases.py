"""Typed query roles, independent of schema declarations and model codecs."""

from __future__ import annotations

from copy import copy
from dataclasses import dataclass
from re import fullmatch
from typing import Any, ClassVar, Never, cast

from snekql.errors import ModelDeclarationError, QueryConstructionError
from snekql.model import (
    BackendFamily,
    ModelMeta,
    Table,
    require_model_backend,
    require_model_columns,
    require_model_table_name,
)
from snekql.storage import Attr


class _AliasOwner[FamilyT, OwnerT, RoleT](Table[Any]):
    """Nominal scope coordinate; the role never changes the fetched model type."""

    def _role_identity(self, role: RoleT) -> RoleT:
        return role

    def _model_identity(self, model: OwnerT) -> OwnerT:
        return model

    def _family_identity(self, family: FamilyT) -> FamilyT:
        return family


class _AliasRelation(Table[Any]):
    """Private query-source identity, never a Table Model declaration.

    Bound columns keep their original descriptor owner for logical codecs.
    Query scope separately resolves their relation to this identity.
    """

    __snekql_columns__: ClassVar[dict[str, Attr[Any, Any, Any, Any, Any]]]
    source_model: ClassVar[type[Table[Any]]]
    role: ClassVar[type[object]]


@dataclass(frozen=True, slots=True, repr=False)
class TableAlias[FamilyT, OwnerT, ReadT, RoleT]:
    """An immutable query role obtained from a backend's `alias` factory."""

    _relation: type[_AliasRelation]

    def column[T, CompareT](
        self,
        column: Attr[Any, Any, OwnerT, Any, T, Any, CompareT],
    ) -> Attr[
        Never, Never, _AliasOwner[FamilyT, OwnerT, RoleT], Never, T, Never, CompareT
    ]:
        """Bind an original model column to this query role, retaining its codec."""
        originals = require_model_columns(self._relation.source_model)
        if (
            not isinstance(column, Attr)
            or originals.get(column.name or "") is not column
        ):
            msg = "alias.column requires an original column of the aliased model"
            raise QueryConstructionError(msg)
        # Metadata lookup erases column generics; identity above proves this is
        # the role-bound copy of exactly the descriptor supplied by the caller.
        return cast(
            "Attr[Never, Never, _AliasOwner[FamilyT, OwnerT, RoleT], Never, T, Never, CompareT]",
            require_model_columns(self._relation)[column.name or ""],
        )

    def __query_source__(self) -> type[_AliasRelation]:
        """Private source consumed by Query Builder, never by schema operations."""
        return self._relation

    @classmethod
    def __backend_family_type__(cls) -> FamilyT:
        raise NotImplementedError

    @classmethod
    def __owner_type__(cls) -> type[_AliasOwner[FamilyT, OwnerT, RoleT]]:
        raise NotImplementedError

    @classmethod
    def __owner_invariant__(
        cls, owner: _AliasOwner[FamilyT, OwnerT, RoleT]
    ) -> _AliasOwner[FamilyT, OwnerT, RoleT]:
        return owner

    @classmethod
    def __read_type__(cls) -> type[ReadT]:
        raise NotImplementedError

    def __repr__(self) -> str:
        return f"TableAlias(model={self._relation.source_model.__name__!r}, name={self._relation.__name__!r})"


def build_alias(
    model: object, role: object, *, name: str, backend: BackendFamily
) -> TableAlias[Any, Any, Any, Any]:
    """Create a query-only source with distinct identity and untouched model metadata."""
    if not isinstance(model, ModelMeta) or not issubclass(model, Table):
        msg = "alias requires a table model"
        raise QueryConstructionError(msg)
    if not isinstance(role, type):
        msg = "alias requires a role marker class"
        raise QueryConstructionError(msg)
    if not isinstance(name, str) or fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name) is None:
        msg = "alias name must be an SQL identifier"
        raise QueryConstructionError(msg)
    if require_model_backend(model) != backend:
        msg = "alias backend does not match the model"
        raise QueryConstructionError(msg)
    try:
        require_model_table_name(model)
        columns = require_model_columns(model)
    except ModelDeclarationError as error:
        msg = "alias requires a declared table model"
        raise QueryConstructionError(msg) from error
    # A plain Table-derived source carries query metadata without invoking
    # ModelMeta, registering a schema, or synthesizing a fetched-model class.
    relation = type(
        name,
        (_AliasRelation,),
        {
            "source_model": model,
            "role": role,
            "__tablename__": name,
            "__snekql_backend__": backend,
        },
    )
    bound_columns = {}
    for column_name, column in columns.items():
        bound = copy(column)
        object.__setattr__(bound, "_query_relation", relation)
        bound_columns[column_name] = bound
    relation.__snekql_columns__ = bound_columns
    return TableAlias(relation)


def require_query_source(value: object) -> type[Table[Any]]:
    """Normalize model and alias SELECT sources without accepting schema lookalikes."""
    if isinstance(value, TableAlias):
        return value.__query_source__()
    if not isinstance(value, type) or not issubclass(value, Table):
        msg = "query source requires a table model or alias"
        raise QueryConstructionError(msg)
    try:
        require_model_columns(value)
    except ModelDeclarationError as error:
        msg = "query source requires a table model or alias"
        raise QueryConstructionError(msg) from error
    return value

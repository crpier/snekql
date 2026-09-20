"""Query-only named definitions and their decoded output references."""

from __future__ import annotations

from dataclasses import dataclass
from re import fullmatch
from typing import Any, ClassVar, Protocol, cast, overload

from pydantic import BaseModel

from snekql._dialect_expr import CompileCtx
from snekql._output_label import _NullExtendedLabel, _OutputLabel
from snekql._query_dialect import query_dialect_for_backend
from snekql._query_state import SelectState, require_single_column_subquery
from snekql._value_decode import _decode_projection_field
from snekql._value_encode import _predicate_value_encoder
from snekql.errors import QueryConstructionError
from snekql.expressions import Comparable, OrderBy, _OrderBy, _Scalar
from snekql.model import BackendFamily, Table, require_model_backend
from snekql.storage import StorageBackend


class _LabelContract[OwnerT, T, CompareT](Protocol):
    """Structural witnesses preserve domains when callers choose between tokens."""

    def __owner_type__(self) -> OwnerT: ...

    def __value_type__(self) -> T: ...

    def __accepts_comparison__(self, value: CompareT, /) -> None: ...


class _SensitiveLabelContract[OwnerT, T, CompareT](
    _LabelContract[OwnerT, T, CompareT], Protocol
):
    """A token whose SQL value can be null-extended with its source owner."""

    def __null_extension_sensitive__(self) -> None: ...


class _CteOwner[FamilyT, SourceT, RoleT](Table[Any]):
    """Invariant family, source and role coordinates for a query-only owner."""

    def _family_identity(self, family: FamilyT) -> FamilyT:
        return family

    def _source_identity(self, source: SourceT) -> SourceT:
        return source

    def _role_identity(self, role: RoleT) -> RoleT:
        return role


@dataclass(frozen=True, slots=True, eq=False, repr=False)
class _CteDefinition:
    """An immutable SQL definition, independent of each reference to it."""

    name: str
    state: SelectState

    @property
    def presence_name(self) -> str:
        """A private output name that cannot shadow a declared result label."""
        projection = self.state.named_projection
        labels = (
            set()
            if projection is None
            else {label.casefold() for label in projection.labels}
        )
        name = "__snekql_present"
        while name.casefold() in labels:
            name += "_"
        return name


class _CteRelation(Table[Any]):
    """An SQL source identity without schema columns or a Table Model class."""

    definition: ClassVar[_CteDefinition]
    role: ClassVar[type[object]]


@dataclass(frozen=True, slots=True, repr=False)
class _CtePresence:
    """Private row-presence reference, never a public output token."""

    relation: type[_CteRelation]

    def __owner_model__(self) -> type[_CteRelation]:
        return self.relation

    def __compile_sql__(self, ctx: CompileCtx) -> tuple[str, tuple[object, ...]]:
        owner = ctx.quote_identifier(self.relation.__name__)
        name = ctx.quote_identifier(self.relation.definition.presence_name)
        return f"{owner}.{name}", ()


@dataclass(frozen=True, slots=True, eq=False, repr=False)
class _CteOutput[OwnerT: Table[Any], T, CompareT](Comparable[OwnerT, CompareT, T]):
    """A readonly reference whose wire decoder remains the definition's source."""

    position: int
    relation: type[_CteRelation]

    def __owner_model__(self) -> type[OwnerT]:
        # Construction binds every output to exactly this reference's relation.
        return cast("type[OwnerT]", self.relation)

    def __column_owner_type__(self) -> OwnerT:
        raise NotImplementedError

    def __column_value_type__(self) -> T:
        raise NotImplementedError

    def __compile_sql__(self, ctx: CompileCtx) -> tuple[str, tuple[object, ...]]:
        definition = self.relation.definition
        projection = definition.state.named_projection
        if projection is None:
            msg = "CTE outputs require a named definition"
            raise QueryConstructionError(msg)
        name = ctx.quote_identifier(projection.labels[self.position])
        owner = ctx.quote_identifier(self.relation.__name__)
        return f"{owner}.{name}", ()

    def __compile_select_sql__(self, ctx: CompileCtx) -> tuple[str, tuple[object, ...]]:
        return self.__compile_sql__(ctx)

    def __encode_comparison__(self, value: object) -> object:
        source = self.relation.definition.state.fields[self.position]
        while isinstance(source, _Scalar):
            source = require_single_column_subquery(source.subquery).fields[0]
        dialect = query_dialect_for_backend(require_model_backend(self.relation))
        return _predicate_value_encoder(source, dialect)(value)

    def __decode__(self, raw: object) -> T:
        return self.__decode_with_policy__(
            raw, backend=require_model_backend(self.relation), validate=True
        )

    def __decode_with_policy__(
        self, raw: object, *, backend: StorageBackend, validate: bool
    ) -> T:
        state = self.relation.definition.state
        # The output index identifies the original SQL expression, not a field
        # produced by an intermediate Pydantic result validator.
        return cast(
            "T",
            _decode_projection_field(
                state.fields[self.position],
                raw,
                nullable_models=frozenset(
                    join.model for join in state.joins if join.join_type == "LEFT"
                ),
                backend=backend,
                validate=validate,
            ),
        )

    def asc(self) -> OrderBy[OwnerT]:
        """Order consumers by this output without re-evaluating its definition."""
        return _OrderBy(column=self, direction="ASC")

    def desc(self) -> OrderBy[OwnerT]:
        """Order consumers by this output in descending SQL order."""
        return _OrderBy(column=self, direction="DESC")

    def label(self, name: str) -> _NullExtendedLabel[OwnerT, T, CompareT]:
        """Bind this SQL output into a downstream named definition."""
        return _NullExtendedLabel(name=name, operand=self)


@dataclass(frozen=True, slots=True, eq=False, repr=False)
class _Cte[
    FamilyT,
    SourceT: Table[Any],
    ResultT: BaseModel,
    RoleT,
    NonNullableOwnerT = SourceT,
]:
    """A named SELECT relation; never a schema object or a mutation target."""

    _relation: type[_CteRelation]

    def __query_source__(self) -> type[_CteRelation]:
        return self._relation

    @classmethod
    def __backend_family_type__(cls) -> FamilyT:
        raise NotImplementedError

    @classmethod
    def __owner_type__(cls) -> type[_CteOwner[FamilyT, SourceT, RoleT]]:
        raise NotImplementedError

    @classmethod
    def __owner_invariant__(
        cls, owner: _CteOwner[FamilyT, SourceT, RoleT]
    ) -> _CteOwner[FamilyT, SourceT, RoleT]:
        return owner

    @classmethod
    def __read_type__(cls) -> type[ResultT]:
        raise NotImplementedError

    @overload
    def column[T, CompareT](
        self, token: _SensitiveLabelContract[NonNullableOwnerT, T, CompareT]
    ) -> _CteOutput[_CteOwner[FamilyT, SourceT, RoleT], T, CompareT]: ...

    @overload
    def column[TokenOwnerT, T, CompareT](
        self, token: _SensitiveLabelContract[TokenOwnerT, T, CompareT]
    ) -> _CteOutput[_CteOwner[FamilyT, SourceT, RoleT], T | None, CompareT]: ...

    @overload
    def column[TokenOwnerT, T, CompareT](
        self, token: _LabelContract[TokenOwnerT, T, CompareT]
    ) -> _CteOutput[_CteOwner[FamilyT, SourceT, RoleT], T, CompareT]: ...

    def column(self, token: object) -> _CteOutput[Any, Any, Any]:
        """Rebind a token actually present in this definition, by identity."""
        projection = self._relation.definition.state.named_projection
        if projection is not None and isinstance(token, _OutputLabel):
            for position, original in enumerate(projection.output_tokens):
                if original is token:
                    return _CteOutput(position=position, relation=self._relation)
        msg = "CTE column requires a label token bound by this definition"
        raise QueryConstructionError(msg)


def _require_reference_identity(role: object, name: str) -> None:
    """Validate a nominal role and quoted SQL reference name before construction."""
    if not isinstance(role, type):
        msg = "CTE definitions require a role marker class"
        raise QueryConstructionError(msg)
    if not isinstance(name, str) or fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name) is None:
        msg = "CTE name must be an SQL identifier"
        raise QueryConstructionError(msg)


def build_cte(
    state: SelectState, role: type[object], *, name: str
) -> _Cte[Any, Any, Any, Any, Any]:
    """Freeze a completed named definition without executing its SQL."""
    if not state.explicit_all and not state.predicates:
        msg = "CTE definitions require all() or where()"
        raise QueryConstructionError(msg)
    if state.lock_wait is not None:
        msg = "CTE definitions cannot contain a locking SELECT"
        raise QueryConstructionError(msg)
    if state.named_projection is None:
        msg = "CTE definitions require named projections"
        raise QueryConstructionError(msg)
    _require_reference_identity(role, name)
    relation = type(
        name,
        (_CteRelation,),
        {
            "definition": _CteDefinition(name=name, state=state),
            "role": role,
            "__tablename__": name,
            "__snekql_backend__": require_model_backend(state.model),
        },
    )
    return _Cte(relation)


def build_cte_alias(
    source: _Cte[Any, Any, Any, Any, Any],
    role: type[object],
    *,
    name: str,
    backend: BackendFamily,
) -> _Cte[Any, Any, Any, Any, Any]:
    """Bind a new role to the existing definition without copying its SELECT."""
    _require_reference_identity(role, name)
    original = source.__query_source__()
    if require_model_backend(original) != backend:
        msg = "CTE alias backend does not match the definition"
        raise QueryConstructionError(msg)
    relation = type(
        name,
        (_CteRelation,),
        {
            "definition": original.definition,
            "role": role,
            "__tablename__": name,
            "__snekql_backend__": backend,
        },
    )
    return _Cte(relation)

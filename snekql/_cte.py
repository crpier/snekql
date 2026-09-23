"""Query-only named definitions and their decoded output references."""

from __future__ import annotations

from dataclasses import dataclass, field
from re import fullmatch
from typing import Any, ClassVar, Protocol, cast, overload

from pydantic import BaseModel

from snekql._dialect_expr import CompileCtx
from snekql._literal import _IntegerLiteral
from snekql._output_domain import OutputDomain
from snekql._output_label import _NullExtendedLabel, _OutputLabel
from snekql._output_layout import OutputLayout, OutputSlot, build_output_layout
from snekql._query_dialect import query_dialect_for_backend
from snekql._query_state import (
    SelectState,
    require_single_column_subquery,
    selectable_owner_model,
)
from snekql._value_decode import _normalize_sum
from snekql._value_expression import ExpressionMethods, ValueExpression
from snekql.errors import QueryConstructionError
from snekql.expressions import (
    Aggregate,
    Comparable,
    OrderBy,
    _Aggregate,
    _OrderBy,
    _Scalar,
)
from snekql.model import BackendFamily, Table, require_model_backend
from snekql.storage import Attr, StorageBackend


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
    recursive_step: SelectState | None = None
    recursive_seed: _CteDefinition | None = None
    is_recursive_seed: bool = False

    layout: OutputLayout = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "layout", build_output_layout(self.state))

    @property
    def presence_name(self) -> str:
        return self.layout.presence_name


class _CteRelation(Table[Any]):
    """An SQL source identity without schema columns or a Table Model class."""

    definition: ClassVar[_CteDefinition]
    role: ClassVar[type[object]]


class _CompoundRelation(_CteRelation):
    """Scope-local derived output, never an independently readable definition."""


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
class _CteOutput[OwnerT: Table[Any], T, CompareT](
    ExpressionMethods[OwnerT, T], Comparable[OwnerT, CompareT, T]
):
    """A readonly reference whose wire decoder remains the definition's source."""

    position: int
    relation: type[_CteRelation]

    def __owner_model__(self) -> type[OwnerT]:
        # Construction binds every output to exactly this reference's relation.
        return cast("type[OwnerT]", self.relation)

    def __grouping_column__(self) -> None:
        """Typing witness for a readonly GROUP BY column reference."""

    def __column_owner_type__(self) -> OwnerT:
        raise NotImplementedError

    def __column_value_type__(self) -> T:
        raise NotImplementedError

    def __compile_sql__(self, ctx: CompileCtx) -> tuple[str, tuple[object, ...]]:
        name = ctx.quote_identifier(self.__output_slot__().label)
        owner = ctx.quote_identifier(self.relation.__name__)
        return f"{owner}.{name}", ()

    def __compile_select_sql__(self, ctx: CompileCtx) -> tuple[str, tuple[object, ...]]:
        return self.__compile_sql__(ctx)

    def __encode_comparison__(self, value: object) -> object:
        return self.__output_slot__().encode_comparison(value)

    def __decode__(self, raw: object) -> T:
        return self.__decode_with_policy__(
            raw, backend=require_model_backend(self.relation), validate=True
        )

    def __decode_with_policy__(
        self, raw: object, *, backend: StorageBackend, validate: bool
    ) -> T:
        slot = self.__output_slot__()
        if backend != slot.backend:
            msg = "CTE output decode backend differs from its definition"
            raise QueryConstructionError(msg)
        return cast("T", slot.decode(raw, validate=validate))

    def __output_slot__(self) -> OutputSlot:
        return self.relation.definition.layout.slots[self.position]

    def __nullable_when_extended__(self) -> bool:
        """A missing reference nulls this SQL column regardless of its definition."""
        return True

    def __output_domain__(self) -> OutputDomain:
        return self.__output_slot__().domain

    def __value_operand__(self) -> ValueExpression[OwnerT, T]:
        """Expose native wire-compatible operations without schema capabilities."""
        state = self.relation.definition.state
        value_type, nullable = _native_value_profile(state, state.fields[self.position])
        return ValueExpression(
            column=self,
            owner=self.__owner_model__(),
            value_type=value_type,
            nullable=nullable,
        )

    def count(self) -> Aggregate[OwnerT, int]:
        """Count non-NULL SQL outputs without decoding intermediate rows."""
        return _Aggregate(column=self, func="COUNT", owner=self.relation)

    def sum(self) -> Aggregate[OwnerT, T | None, CompareT]:
        """Sum numeric outputs using their original SQL result domain."""
        self._numeric_source()
        return _Aggregate(column=self, func="SUM", owner=self.relation)

    def avg(self) -> Aggregate[OwnerT, float | None, float]:
        """Average numeric outputs, returning NULL for an empty input."""
        self._numeric_source()
        return _Aggregate(column=self, func="AVG", owner=self.relation)

    def __decode_sum__(self, raw: object) -> object:
        source = self._numeric_source()
        if isinstance(source, Attr):
            return _normalize_sum(source, raw)
        return source(cast("int | float", raw))

    def __encode_sum_comparison__(self, value: object) -> object:
        source = self._numeric_source()
        if isinstance(source, Attr):
            dialect = query_dialect_for_backend(require_model_backend(self.relation))
            return dialect.encode_sum_value(source, value)
        return value

    def _numeric_source(self) -> type[int | float] | Attr[Any, Any, Any, Any, Any]:
        source = self.relation.definition.state.fields[self.position]
        while True:
            if isinstance(source, _CteOutput):
                source = source.relation.definition.state.fields[source.position]
            elif isinstance(source, _Scalar):
                source = require_single_column_subquery(source.subquery).fields[0]
            elif isinstance(source, _Aggregate):
                if source.func == "COUNT":
                    return int
                if source.func == "AVG":
                    return float
                source = source.column
            else:
                break
        if isinstance(source, Attr):
            source.sum()
            return source
        if isinstance(
            source, (ValueExpression, _IntegerLiteral)
        ) and source.value_type in {int, float}:
            return cast("type[int | float]", source.value_type)
        msg = "sum()/avg() require a known numeric CTE output domain"
        raise QueryConstructionError(msg)

    def min(self) -> Aggregate[OwnerT, T | None, CompareT]:
        """Select the least output, or NULL when no non-NULL value exists."""
        self._require_ordering()
        return _Aggregate(column=self, func="MIN", owner=self.relation)

    def max(self) -> Aggregate[OwnerT, T | None, CompareT]:
        """Select the greatest output without decoding intermediate rows."""
        self._require_ordering()
        return _Aggregate(column=self, func="MAX", owner=self.relation)

    def asc(self) -> OrderBy[OwnerT]:
        """Order consumers by this output without re-evaluating its definition."""
        self._require_ordering()
        return _OrderBy(column=self, direction="ASC")

    def desc(self) -> OrderBy[OwnerT]:
        """Order consumers by this output in descending SQL order."""
        self._require_ordering()
        return _OrderBy(column=self, direction="DESC")

    def _require_ordering(self) -> None:
        source = self.relation.definition.state.fields[self.position]
        while True:
            if isinstance(source, _CteOutput):
                source = source.relation.definition.state.fields[source.position]
            elif isinstance(source, _Scalar):
                source = require_single_column_subquery(source.subquery).fields[0]
            elif isinstance(source, _Aggregate) and source.func in {"MIN", "MAX"}:
                source = source.column
            else:
                break
        if isinstance(source, Attr):
            source.asc()

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
        if isinstance(token, _OutputLabel):
            for position, slot in enumerate(self._relation.definition.layout.slots):
                if slot.token is token:
                    return _CteOutput(position=position, relation=self._relation)
        msg = "CTE column requires a label token bound by this definition"
        raise QueryConstructionError(msg)


def _native_value_profile(
    state: SelectState, source: object
) -> tuple[type[int | float | str], bool]:
    """Resolve native wire compatibility independently of the final result model."""
    if isinstance(source, _IntegerLiteral):
        return int, False
    if isinstance(source, _Scalar):
        inner = require_single_column_subquery(source.subquery)
        value_type, _ = _native_value_profile(inner, inner.fields[0])
        return value_type, True
    if isinstance(source, _Aggregate) and source.func == "COUNT":
        return int, False
    if not isinstance(source, (Attr, ValueExpression, _CteOutput)):
        msg = "CTE arithmetic requires a known native wire-compatible output"
        raise QueryConstructionError(msg)
    operand = source.__value_operand__()
    nullable = operand.nullable
    nullable_owners = {join.model for join in state.joins if join.join_type == "LEFT"}
    if selectable_owner_model(source) in nullable_owners:
        nullable = nullable or operand.__nullable_when_extended__()
    return operand.value_type, nullable


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

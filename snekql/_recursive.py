"""Atomic construction of an anchor and its direct recursive member."""

from collections.abc import Callable
from dataclasses import dataclass, replace
from typing import Any

from pydantic import BaseModel

from snekql._compound import _NamedSetOperand, build_compound
from snekql._cte import _Cte, _CteOutput, _CteRelation, build_cte
from snekql._cte_graph import collect_cte_definitions
from snekql._literal import _IntegerLiteral
from snekql._query_readiness import _ExecutableQuery
from snekql._query_state import SelectState
from snekql.errors import QueryCompilationError, QueryConstructionError
from snekql.expressions import _Aggregate
from snekql.model import BackendFamily, Table, require_model_backend
from snekql.query import NamedSelectQuery
from snekql.storage import Attr


def _require_anchor_width(state: SelectState) -> None:
    """Only physical columns and full-width constants establish recursive domains."""
    for selected in state.fields:
        source = selected
        while isinstance(source, _CteOutput):
            source = source.relation.definition.state.fields[source.position]
        if not isinstance(source, (Attr, _IntegerLiteral)):
            msg = "recursive anchors require column outputs or fixed-width integer literals"
            raise QueryConstructionError(msg)


def build_recursive_cte(
    anchor: object,
    role: type[object],
    *,
    name: str,
    step: Callable[[_Cte[Any, Any, Any, Any, Any]], object],
    backend: BackendFamily,
) -> _Cte[Any, Any, Any, Any, Any]:
    """Publish a distinct definition after invoking the member callback once."""
    state = getattr(anchor, "state", None)
    if (
        not isinstance(state, SelectState)
        or require_model_backend(state.model) != backend
    ):
        msg = "recursive anchor requires a completed named query of the same backend"
        raise QueryConstructionError(msg)
    _require_anchor_width(state)
    seed = build_cte(state, role, name=name)
    seed_relation = seed.__query_source__()
    seed_relation.definition = replace(seed_relation.definition, is_recursive_seed=True)
    combined = build_compound(state, step(seed), "UNION ALL")
    if combined.compound is None:
        msg = "recursive definition requires a named UNION ALL contract"
        raise QueryConstructionError(msg)
    member = combined.compound.right
    if (
        member.groupings
        or member.having
        or any(isinstance(field, _Aggregate) for field in member.fields)
    ):
        msg = "recursive member cannot use aggregates, grouping or HAVING"
        raise QueryConstructionError(msg)
    if member.distinct:
        msg = "recursive member cannot use DISTINCT"
        raise QueryConstructionError(msg)
    references = tuple(
        source
        for source in member.result_models()
        if issubclass(source, _CteRelation)
        and source.definition is seed_relation.definition
    )
    if len(references) != 1:
        msg = "recursive member requires one direct self source"
        raise QueryConstructionError(msg)
    if any(
        join.join_type == "LEFT" and join.model in references for join in member.joins
    ):
        msg = "recursive self source cannot be on a nullable join side"
        raise QueryConstructionError(msg)
    completed = build_cte(combined.compound.left, role, name=name)
    relation = completed.__query_source__()
    relation.definition = replace(
        relation.definition,
        recursive_step=combined.compound.right,
        recursive_seed=seed_relation.definition,
    )
    try:
        collect_cte_definitions(SelectState(model=relation, fields=()))
    except QueryCompilationError as error:
        raise QueryConstructionError(str(error)) from error
    return completed


@dataclass(frozen=True, slots=True, kw_only=True)
class _RecursiveCteBuilder[
    FamilyT: BackendFamily,
    OwnerT: Table[Any],
    ResultT: BaseModel,
    RoleT,
    NonNullableOwnerT,
]:
    """Bind the anchor and role before the callback needs its concrete self type.

    Preparation holds no recursive symbol and is not a query source. Each step
    invocation validates a fresh definition before returning a usable relation.
    """

    anchor: NamedSelectQuery[
        FamilyT, OwnerT, ResultT, _ExecutableQuery, NonNullableOwnerT
    ]
    backend: FamilyT
    name: str
    role: type[RoleT]

    def step(
        self,
        callback: Callable[
            [_Cte[FamilyT, OwnerT, ResultT, RoleT, NonNullableOwnerT]],
            _NamedSetOperand[FamilyT, ResultT, _ExecutableQuery],
        ],
    ) -> _Cte[FamilyT, OwnerT, ResultT, RoleT, NonNullableOwnerT]:
        """Invoke the member callback once and publish only a validated CTE."""
        return build_recursive_cte(
            self.anchor,
            self.role,
            name=self.name,
            step=callback,
            backend=self.backend,
        )

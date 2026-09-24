"""Backend-owned staged recursive CTE construction."""

from typing import Any, Literal

from pydantic import BaseModel

from snekql._query_readiness import _ExecutableQuery
from snekql._recursive import _RecursiveCteBuilder
from snekql.model import Table
from snekql.query import NamedSelectQuery


def recursive_cte[OwnerT: Table[Any], ResultT: BaseModel, RoleT, NonNullableOwnerT](
    anchor: NamedSelectQuery[
        Literal["sqlite"], OwnerT, ResultT, _ExecutableQuery, NonNullableOwnerT
    ],
    role: type[RoleT],
    *,
    name: str,
) -> _RecursiveCteBuilder[Literal["sqlite"], OwnerT, ResultT, RoleT, NonNullableOwnerT]:
    """Prepare an anchor; call `.step(callback)` to construct its recursive CTE."""
    return _RecursiveCteBuilder(anchor=anchor, backend="sqlite", name=name, role=role)

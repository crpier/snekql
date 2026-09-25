"""Backend-owned staged recursive CTE construction."""

from typing import Any, Literal

from pydantic import BaseModel

from snekql._compound import _NamedSetOperand
from snekql._cte import _Cte
from snekql._query_readiness import _ExecutableQuery
from snekql._recursive import _RecursiveCteBuilder
from snekql.model import Table
from snekql.query import NamedSelectQuery

type Cte[
    SourceT: Table[Any],
    ResultT: BaseModel,
    RoleT,
    NonNullableSourceT = SourceT,
] = _Cte[Literal["mariadb"], SourceT, ResultT, RoleT, NonNullableSourceT]
"""Nonconstructible annotation for a named relation's source, row and role.

The optional fourth argument names sources not null-extended by anchor joins.
Obtain relations from `.cte()` or `recursive_cte(...).step(...)`.
"""

type NamedOperand[ResultT: BaseModel] = _NamedSetOperand[
    Literal["mariadb"], ResultT, _ExecutableQuery
]
"""Nonconstructible annotation for a completed named composition operand.

Use for helpers returning UNION operands or recursive members. It preserves the
backend, result class and readiness without exposing scope-erased fluent edits.
Use `ReadQuery[Scope, ResultT]` for queries passed directly to a Transaction.
"""


def recursive_cte[OwnerT: Table[Any], ResultT: BaseModel, RoleT, NonNullableOwnerT](
    anchor: NamedSelectQuery[
        Literal["mariadb"], OwnerT, ResultT, _ExecutableQuery, NonNullableOwnerT
    ],
    role: type[RoleT],
    *,
    name: str,
) -> _RecursiveCteBuilder[
    Literal["mariadb"], OwnerT, ResultT, RoleT, NonNullableOwnerT
]:
    """Prepare an anchor; call `.step(callback)` to construct its recursive CTE."""
    return _RecursiveCteBuilder(anchor=anchor, backend="mariadb", name=name, role=role)

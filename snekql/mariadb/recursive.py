"""Backend-owned recursive CTE construction."""

from collections.abc import Callable
from typing import Any, Literal

from pydantic import BaseModel

from snekql._compound import _NamedSetOperand
from snekql._cte import _Cte
from snekql._query_readiness import _ExecutableQuery
from snekql._recursive import build_recursive_cte
from snekql.model import Table
from snekql.query import NamedSelectQuery


def recursive_cte[OwnerT: Table[Any], ResultT: BaseModel, RoleT, NonNullableOwnerT](
    anchor: NamedSelectQuery[
        Literal["mariadb"], OwnerT, ResultT, _ExecutableQuery, NonNullableOwnerT
    ],
    role: type[RoleT],
    *,
    name: str,
    step: Callable[
        [_Cte[Literal["mariadb"], OwnerT, ResultT, RoleT, NonNullableOwnerT]],
        _NamedSetOperand[Literal["mariadb"], ResultT, _ExecutableQuery],
    ],
) -> _Cte[Literal["mariadb"], OwnerT, ResultT, RoleT, NonNullableOwnerT]:
    """Build an anchor UNION ALL its callback's direct recursive member."""
    return build_recursive_cte(anchor, role, name=name, step=step, backend="mariadb")

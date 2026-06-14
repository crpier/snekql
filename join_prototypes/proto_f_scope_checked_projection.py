"""Prototype F: can we CATCH projecting/filtering a column whose table is not joined?

proto_e's gap: `select(User.email, Order.note)` seeds the owner-union from the
projected COLUMNS, so the union reflects what you *referenced*, not what you
actually joined. Forgetting `.join(Order)` is therefore invisible to the checker.

Idea: make the JOIN graph authoritative. Establish the base table with
`select(Model)`, accumulate scope through `.join(...)`, and PROJECT LAST with a
terminal `.columns(...)` whose parameters are pinned to the accumulated scope
union `OwnerT`. A projected column from an unjoined table then fails to match
`Attr[OwnerT, R]` (Attr is covariant in its owner), so it is rejected.

    select(User).join(Order, on=...).columns(User.email, Order.note)   # ok
    select(User).join(Order, on=...).columns(User.email, Region.code)  # Region not joined -> ERROR

Checked with: uv run pyright join_prototypes/proto_f_scope_checked_projection.py
"""
# pyright: reportUninitializedInstanceVariable=false

from __future__ import annotations

from typing import Any, Protocol, Self, assert_type, overload


# --- Expression objects ------------------------------------------------------
class Predicate[OwnerT_co]:
    def __and__[Other](self, o: Predicate[Other]) -> Predicate[OwnerT_co | Other]: ...


class JoinOn[LeftT_co, RightT_co]: ...


# --- Columns -----------------------------------------------------------------
class Attr[OwnerT, ReadValueT]:
    def eq(self, value: ReadValueT) -> Predicate[OwnerT]: ...


class FKAttr[OwnerT, ReadValueT, TargetOwnerT](Attr[OwnerT, ReadValueT]):
    def references(
        self, other: Attr[TargetOwnerT, ReadValueT]
    ) -> JoinOn[OwnerT, TargetOwnerT]: ...


# --- Model machinery ---------------------------------------------------------
class Pending: ...
class Fetched: ...


class Table[StateT]:
    @classmethod
    def __owner_type__(cls) -> type[Self]:
        return cls


class Model[StateT, ReadModelT](Table[StateT]):
    type Col[T] = Attr[Self, T]
    type FKCol[Target, T] = FKAttr[Self, T, Target]

    @classmethod
    def __read_type__(cls) -> type[ReadModelT]: ...


class SelectableModel[OwnerT_co, ReadModelT_co](Protocol):
    @classmethod
    def __owner_type__(cls) -> type[OwnerT_co]: ...
    @classmethod
    def __read_type__(cls) -> type[ReadModelT_co]: ...


# --- Query types -------------------------------------------------------------
class ProjectedQuery[OwnerT, *ResultTs]:
    """Terminal projection. Result shape fixed by columns; scope already closed."""

    def where(self, *predicates: Predicate[OwnerT]) -> Self: ...


class JoinQuery[OwnerT, *ResultTs]:
    """OwnerT is the AUTHORITATIVE scope union (base + joined tables)."""

    def where(self, *predicates: Predicate[OwnerT]) -> Self: ...

    def join[NewOwner, NewRead](
        self,
        model: type[SelectableModel[NewOwner, NewRead]],
        on: JoinOn[NewOwner, OwnerT] | JoinOn[OwnerT, NewOwner],
    ) -> JoinQuery[OwnerT | NewOwner, *ResultTs, NewRead]: ...

    # Terminal projection: every column's owner is pinned to the scope union.
    @overload
    def columns[R1](
        self, c1: Attr[OwnerT, R1], /
    ) -> ProjectedQuery[OwnerT, R1]: ...
    @overload
    def columns[R1, R2](
        self, c1: Attr[OwnerT, R1], c2: Attr[OwnerT, R2], /
    ) -> ProjectedQuery[OwnerT, R1, R2]: ...
    @overload
    def columns[R1, R2, R3](
        self, c1: Attr[OwnerT, R1], c2: Attr[OwnerT, R2], c3: Attr[OwnerT, R3], /
    ) -> ProjectedQuery[OwnerT, R1, R2, R3]: ...
    def columns(
        self, *cols: Attr[OwnerT, Any]
    ) -> ProjectedQuery[OwnerT, *tuple[Any, ...]]: ...


class SelectModelQuery[OwnerT, ReadModelT]:
    def where(self, *predicates: Predicate[OwnerT]) -> Self: ...

    def join[NewOwner, NewRead](
        self,
        model: type[SelectableModel[NewOwner, NewRead]],
        on: JoinOn[NewOwner, OwnerT] | JoinOn[OwnerT, NewOwner],
    ) -> JoinQuery[OwnerT | NewOwner, ReadModelT, NewRead]: ...


def select[OwnerT, ReadModelT](
    model: type[SelectableModel[OwnerT, ReadModelT]],
) -> SelectModelQuery[OwnerT, ReadModelT]: ...


async def fetch_all_join[O, *Ts](q: JoinQuery[O, *Ts]) -> list[tuple[*Ts]]: ...
async def fetch_all_proj[O, *Ts](
    q: ProjectedQuery[O, *Ts],
) -> list[tuple[*Ts]]: ...


# ============================================================================
# Models
# ============================================================================
class User[S = Pending](Model[S, "User[Fetched]"]):
    id: User.Col[int]
    email: User.Col[str]
    region_code: User.Col[str]


class Order[S = Pending](Model[S, "Order[Fetched]"]):
    id: Order.Col[int]
    user_id: Order.FKCol[User, int]
    note: Order.Col[str]
    total: Order.Col[float]


class Region[S = Pending](Model[S, "Region[Fetched]"]):
    code: Region.Col[str]
    name: Region.Col[str]


# ============================================================================
# HAPPY PATH
# ============================================================================
async def check_good() -> None:
    # Project columns from joined tables -- checked against the scope union.
    q = select(User).join(Order, on=Order.user_id.references(User.id)).columns(
        User.email, Order.note
    )
    _ = assert_type(
        q, ProjectedQuery[User[Pending] | Order[Pending], str, str]
    )
    _ = assert_type(await fetch_all_proj(q), list[tuple[str, str]])

    # Mixed-type 3-column projection.
    q3 = select(User).join(Order, on=Order.user_id.references(User.id)).columns(
        User.id, Order.note, Order.total
    )
    _ = assert_type(await fetch_all_proj(q3), list[tuple[int, str, float]])

    # where() still works against the scope union.
    _ = q.where(User.email.eq("a@b.c") & Order.total.eq(1.0))


# ============================================================================
# THE TARGET REJECTION -- project a column whose table was never joined
# ============================================================================
async def check_unjoined_rejection() -> None:
    # Region is NOT joined; projecting Region.code must be rejected.
    _ = select(User).join(Order, on=Order.user_id.references(User.id)).columns(
        User.email,
        Region.code,  # type: ignore[arg-type]
    )

    # Same for where() against an unjoined table (already sound, kept for parity).
    _ = (
        select(User)
        .join(Order, on=Order.user_id.references(User.id))
        .where(Region.code.eq("EU"))  # type: ignore[arg-type]
    )

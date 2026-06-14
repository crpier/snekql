"""Prototype H: KEEP columns-first select AND catch the unjoined-table mistake.

    select(User.email, Order.note).join(Order, on=Order.user_id.references(User.id))

No `.columns()`, no reordering: `select(col, ...)` stays exactly as today and is
also the only way to project. The "did you forget to join a referenced table?"
check is enforced at fetch time via a deferred subset constraint.

Mechanism (validated in proto_g):
  - The query carries TWO unions: ScopeT (tables actually joined) and RefT
    (owners of every referenced column, from select() and where()).
  - join() adds the on-condition's tables to ScopeT; where() adds its predicate
    owner to RefT.
  - fetch_all is typed `fetch_all[X, *Ts](q: Query[X, X, *Ts])`, unifying ScopeT
    and RefT through one fresh X. Because RefT is covariant and ScopeT invariant,
    this forces RefT <: ScopeT -- "every referenced table must be joined."

Checked with: uv run pyright join_prototypes/proto_h_columns_first_checked.py
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


# --- Projection query: ScopeT (joined) + RefT (referenced) + result tuple ----
class ProjQuery[ScopeT, RefT, *ResultTs]:
    # Phantom: pins ScopeT to an INPUT position so pyright infers it INVARIANT
    # (not covariant). Invariance is what makes the fetch_all[X, X] unification
    # enforce RefT <: ScopeT. Never called.
    def _pin_scope(self, _scope: ScopeT) -> None: ...

    def join[NewOwner, NewRead, A, B](
        self,
        model: type[SelectableModel[NewOwner, NewRead]],
        on: JoinOn[A, B],
    ) -> ProjQuery[ScopeT | A | B, RefT, *ResultTs]:
        """Joining adds the on-condition's two tables to the scope union."""
        ...

    def where[W](
        self, predicate: Predicate[W]
    ) -> ProjQuery[ScopeT, RefT | W, *ResultTs]:
        """Filtering adds the predicate's owner(s) to the referenced union."""
        ...


# Projection select -- columns-first, exactly like today. ScopeT is seeded with
# the FIRST column's owner (the implicit FROM anchor); RefT is every column's
# owner; the result tuple is the read types. Any referenced table other than the
# anchor must be brought into scope by a join.
@overload
def select[O1, R1](c1: Attr[O1, R1], /) -> ProjQuery[O1, O1, R1]: ...
@overload
def select[O1, R1, O2, R2](
    c1: Attr[O1, R1], c2: Attr[O2, R2], /
) -> ProjQuery[O1, O1 | O2, R1, R2]: ...
@overload
def select[O1, R1, O2, R2, O3, R3](
    c1: Attr[O1, R1], c2: Attr[O2, R2], c3: Attr[O3, R3], /
) -> ProjQuery[O1, O1 | O2 | O3, R1, R2, R3]: ...
def select(*columns: Attr[Any, Any]) -> ProjQuery[Any, Any, *tuple[Any, ...]]: ...


# fetch_all unifies ScopeT and RefT through one X -> forces RefT <: ScopeT,
# i.e. every referenced table must have been joined.
async def fetch_all[X, *Ts](q: ProjQuery[X, X, *Ts]) -> list[tuple[*Ts]]: ...


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
# HAPPY PATH -- columns-first, every referenced table joined
# ============================================================================
async def check_good() -> None:
    # The user's exact shape. Inference builds ScopeT through .join().
    q = select(Order.note, User.email).join(Order, on=Order.user_id.references(User.id))
    _ = assert_type(await fetch_all(q), list[tuple[str, str]])

    # where() on a joined table is fine.
    q2 = (
        select(User.id, Order.note, Order.total)
        .join(Order, on=Order.user_id.references(User.id))
        .where(User.email.eq("a@b.c") & Order.total.eq(1.0))
    )
    _ = assert_type(await fetch_all(q2), list[tuple[int, str, float]])

    # No-join single-table projection must still work (anchor == only table).
    _ = assert_type(await fetch_all(select(User.email)), list[tuple[str]])

    # No-join projection across columns of ONE table is fine too.
    q3 = select(User.id, User.email).where(User.email.eq("a@b.c"))
    _ = assert_type(await fetch_all(q3), list[tuple[int, str]])


# ============================================================================
# THE TARGET REJECTION -- referenced a table that was never joined
# ============================================================================
async def check_unjoined_rejection() -> None:
    # Region.code is selected but Region is never joined -> fetch_all must error.
    bad = select(User.email, Region.code).join(
        Order, on=Order.user_id.references(User.id)
    )
    _ = await fetch_all(bad)  # type: ignore[type-var]

    # where() references an unjoined table -> fetch_all must error.
    bad2 = (
        select(User.email, Order.note)
        .join(Order, on=Order.user_id.references(User.id))
        .where(Region.code.eq("EU"))
    )
    _ = await fetch_all(bad2)  # type: ignore[type-var]

    # Project two tables but join NOTHING -> Order is referenced, not joined.
    bad3 = select(User.email, Order.note)
    _ = await fetch_all(bad3)  # type: ignore[type-var]


# ============================================================================
# LEGITIMATE: join a table you DON'T project (filter-only) -- must stay OK
# ============================================================================
async def check_join_without_projection() -> None:
    # Project only User columns, but join Order to filter on it. refs={User},
    # scope={User,Order}; refs subset of scope -> OK.
    q = (
        select(User.email)
        .join(Order, on=Order.user_id.references(User.id))
        .where(Order.total.eq(9.99))
    )
    _ = assert_type(await fetch_all(q), list[tuple[str]])

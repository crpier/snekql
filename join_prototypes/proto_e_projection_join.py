"""Prototype E: projection-select combined with a join.

    select(User.email, Order.note).join(Order, on=Order.user_id.references(User.id))

Difference from proto_c/proto_d (which select whole MODELS and accumulate the
result tuple from joined models): here the result tuple shape is fixed by the
*columns* passed to select(), and the join only declares how tables connect.
join() therefore widens the owner-union (for where()/on) but does NOT change the
result shape.

We test:
  - result tuple type is captured from the projected columns
  - the join `on` is validated (relates an in-scope table, right types)
  - where() accepts predicates from any in-scope table
  - rejections still fire

Checked with: uv run pyright join_prototypes/proto_e_projection_join.py
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


# --- Projection query --------------------------------------------------------
class SelectProjectionQuery[OwnerT, *ResultTs]:
    """Result shape (*ResultTs) is FIXED by select(); join only widens OwnerT."""

    def where(self, *predicates: Predicate[OwnerT]) -> Self: ...

    def join[NewOwner, NewRead](
        self,
        model: type[SelectableModel[NewOwner, NewRead]],
        on: JoinOn[NewOwner, OwnerT] | JoinOn[OwnerT, NewOwner],
    ) -> SelectProjectionQuery[OwnerT | NewOwner, *ResultTs]: ...


# Projection select overloads -- one per arity. Each captures the owner of every
# column (into the union OwnerT) AND its read type (into the result tuple).
@overload
def select[O1, R1](c1: Attr[O1, R1], /) -> SelectProjectionQuery[O1, R1]: ...
@overload
def select[O1, R1, O2, R2](
    c1: Attr[O1, R1], c2: Attr[O2, R2], /
) -> SelectProjectionQuery[O1 | O2, R1, R2]: ...
@overload
def select[O1, R1, O2, R2, O3, R3](
    c1: Attr[O1, R1], c2: Attr[O2, R2], c3: Attr[O3, R3], /
) -> SelectProjectionQuery[O1 | O2 | O3, R1, R2, R3]: ...
def select(*columns: Attr[Any, Any]) -> SelectProjectionQuery[Any, *tuple[Any, ...]]: ...


async def fetch_all_proj[O, *Ts](
    q: SelectProjectionQuery[O, *Ts],
) -> list[tuple[*Ts]]: ...


# ============================================================================
# Models
# ============================================================================
class User[S = Pending](Model[S, "User[Fetched]"]):
    id: User.Col[int]
    email: User.Col[str]


class Order[S = Pending](Model[S, "Order[Fetched]"]):
    id: Order.Col[int]
    user_id: Order.FKCol[User, int]
    note: Order.Col[str]
    total: Order.Col[float]


class Unrelated[S = Pending](Model[S, "Unrelated[Fetched]"]):
    id: Unrelated.Col[int]


# ============================================================================
# HAPPY PATH
# ============================================================================
async def check_good() -> None:
    # The user's exact example.
    q = select(User.email, Order.note).join(
        Order, on=Order.user_id.references(User.id)
    )
    # Owner union is User | Order; result shape is (str, str).
    _ = assert_type(
        q, SelectProjectionQuery[User[Pending] | Order[Pending], str, str]
    )
    _ = assert_type(await fetch_all_proj(q), list[tuple[str, str]])

    # where() accepts predicates from either in-scope table.
    _ = q.where(User.email.eq("a@b.c"))
    _ = q.where(Order.total.eq(9.99))
    _ = q.where(User.email.eq("x") & Order.total.eq(1.0))

    # Three-column projection, mixed types.
    q3 = select(User.id, Order.note, Order.total).join(
        Order, on=Order.user_id.references(User.id)
    )
    _ = assert_type(await fetch_all_proj(q3), list[tuple[int, str, float]])


# ============================================================================
# REJECTIONS -- must error (verified by stripping ignores)
# ============================================================================
async def check_rejections() -> None:
    q = select(User.email, Order.note).join(
        Order, on=Order.user_id.references(User.id)
    )

    # where() from a table not in scope.
    _ = q.where(Unrelated.id.eq(1))  # type: ignore[arg-type]

    # join `on` with a wrong-type key.
    _ = select(User.email, Order.note).join(
        Order,
        on=Order.user_id.references(User.email),  # type: ignore[arg-type]
    )

    # join `on` against an unrelated target.
    _ = select(User.email, Order.note).join(
        Order,
        on=Order.user_id.references(Unrelated.id),  # type: ignore[arg-type]
    )

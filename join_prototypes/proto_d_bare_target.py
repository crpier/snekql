"""Prototype D variant: can FKCol take the BARE generic (User) not User[Pending]?

Same machinery as proto_d_relations, but FK columns are declared as
    user_id: Order.FKCol[User, int]      # instead of FKCol[User[Pending], int]
We check the happy path stays clean AND the rejections still error.

Checked with: uv run pyright join_prototypes/proto_d_bare_target.py
"""
# pyright: reportUninitializedInstanceVariable=false

from __future__ import annotations

from typing import Protocol, Self, assert_type


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
class SelectModelQuery[OwnerT, ReadModelT]:
    def where(self, *predicates: Predicate[OwnerT]) -> Self: ...

    def join[NewOwner, NewRead](
        self,
        model: type[SelectableModel[NewOwner, NewRead]],
        on: JoinOn[NewOwner, OwnerT] | JoinOn[OwnerT, NewOwner],
    ) -> JoinQuery[OwnerT | NewOwner, ReadModelT, NewRead]: ...


class JoinQuery[OwnerT, *ResultTs]:
    def where(self, *predicates: Predicate[OwnerT]) -> Self: ...

    def join[NewOwner, NewRead](
        self,
        model: type[SelectableModel[NewOwner, NewRead]],
        on: JoinOn[NewOwner, OwnerT] | JoinOn[OwnerT, NewOwner],
    ) -> JoinQuery[OwnerT | NewOwner, *ResultTs, NewRead]: ...


def select[OwnerT, ReadModelT](
    model: type[SelectableModel[OwnerT, ReadModelT]],
) -> SelectModelQuery[OwnerT, ReadModelT]: ...


async def fetch_all_join[O, *Ts](q: JoinQuery[O, *Ts]) -> list[tuple[*Ts]]: ...


# ============================================================================
# Models -- FK declared with the BARE target (User, not User[Pending])
# ============================================================================
class User[S = Pending](Model[S, "User[Fetched]"]):
    id: User.Col[int]
    email: User.Col[str]


class Order[S = Pending](Model[S, "Order[Fetched]"]):
    id: Order.Col[int]
    user_id: Order.FKCol[User, int]  # <-- bare User
    note: Order.Col[str]


class LineItem[S = Pending](Model[S, "LineItem[Fetched]"]):
    id: LineItem.Col[int]
    order_id: LineItem.FKCol[Order, int]  # <-- bare Order
    sku: LineItem.Col[str]


class Unrelated[S = Pending](Model[S, "Unrelated[Fetched]"]):
    id: Unrelated.Col[int]


# ============================================================================
# HAPPY PATH -- must be clean
# ============================================================================
async def check_good() -> None:
    q1 = select(User).join(Order, on=Order.user_id.references(User.id))
    _ = assert_type(
        await fetch_all_join(q1), list[tuple[User[Fetched], Order[Fetched]]]
    )

    q2 = q1.join(LineItem, on=LineItem.order_id.references(Order.id))
    _ = assert_type(
        await fetch_all_join(q2),
        list[tuple[User[Fetched], Order[Fetched], LineItem[Fetched]]],
    )
    _ = q2.where(User.email.eq("a@b.c") & LineItem.sku.eq("X"))


# ============================================================================
# REJECTIONS -- must still error
# ============================================================================
async def check_rejections() -> None:
    # (2a) wrong column by TYPE
    _ = select(User).join(
        Order,
        on=Order.user_id.references(User.email),  # type: ignore[arg-type]
    )

    # (2b) non-FK column has no .references
    _ = select(User).join(
        Order,
        on=Order.note.references(User.id),  # type: ignore[attr-defined]
    )

    # (1) unrelated target table
    _ = select(User).join(
        Order,
        on=Order.user_id.references(Unrelated.id),  # type: ignore[arg-type]
    )

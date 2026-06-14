"""Prototype C: full join typing experience with a COVARIANT predicate.

Combines findings from A + B:
- `Predicate` / `OrderBy` are covariant in their owner type, achieved by:
    1. boolean combinators widen:  __and__[Other](self, other) -> Pred[Owner|Other]
    2. the recursive `children` field is type-erased (tuple[Predicate[object],...])
  so a single-table predicate flows into a union-owner slot, and `&` across
  tables widens the union automatically.
- Join queries accumulate:
    * OwnerT     -- union of joined Pending models, types where()/order_by()
    * *ResultTs  -- TypeVarTuple of Fetched result shapes (tuple result)
- INNER append `T[Fetched]`; LEFT append `T[Fetched] | None`.
- Join keys are type-checked on shared read type.

Checked with: uv run pyright join_prototypes/proto_c_full.py
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import (
    Any,
    Protocol,
    Self,
    assert_type,
    dataclass_transform,
)


# --- Covariant expression objects --------------------------------------------
@dataclass(frozen=True)
class Predicate[OwnerT]:
    kind: str = ""
    column: object | None = None
    value: object = None
    # Type-erased so the recursive field does not pin OwnerT to invariant.
    children: tuple[Predicate[object], ...] = field(default_factory=tuple)

    def __and__[Other](self, other: Predicate[Other]) -> Predicate[OwnerT | Other]:
        return Predicate(kind="and", children=(self, other))

    def __or__[Other](self, other: Predicate[Other]) -> Predicate[OwnerT | Other]:
        return Predicate(kind="or", children=(self, other))

    def __invert__(self) -> Predicate[OwnerT]:
        return Predicate(kind="not", children=(self,))


@dataclass(frozen=True)
class OrderBy[OwnerT]:
    column: object | None = None
    direction: str = ""


class JoinOn:
    """Runtime carrier of a column==column join condition (type-erased)."""


# --- Column descriptor (only OwnerT + ReadValueT matter here) ----------------
@dataclass_transform()
class Attr[OwnerT, ReadValueT]:
    def eq(self, value: ReadValueT) -> Predicate[OwnerT]: ...
    def asc(self) -> OrderBy[OwnerT]: ...
    def matches(self, other: Attr[Any, ReadValueT]) -> JoinOn: ...


# --- Model machinery ---------------------------------------------------------
class Pending: ...


class Fetched: ...


class Table[StateT]:
    @classmethod
    def __owner_type__(cls) -> type[Self]:
        return cls


@dataclass_transform()
class Model[StateT, ReadModelT](Table[StateT]):
    type Col[T] = Attr[Self, T]

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
    def order_by(self, *ordering: OrderBy[OwnerT]) -> Self: ...

    def join[NewOwner, NewRead](
        self, model: type[SelectableModel[NewOwner, NewRead]], on: JoinOn
    ) -> JoinQuery[OwnerT | NewOwner, ReadModelT, NewRead]: ...

    def left_join[NewOwner, NewRead](
        self, model: type[SelectableModel[NewOwner, NewRead]], on: JoinOn
    ) -> JoinQuery[OwnerT | NewOwner, ReadModelT, NewRead | None]: ...


class JoinQuery[OwnerT, *ResultTs]:
    def where(self, *predicates: Predicate[OwnerT]) -> Self: ...
    def order_by(self, *ordering: OrderBy[OwnerT]) -> Self: ...

    def join[NewOwner, NewRead](
        self, model: type[SelectableModel[NewOwner, NewRead]], on: JoinOn
    ) -> JoinQuery[OwnerT | NewOwner, *ResultTs, NewRead]: ...

    def left_join[NewOwner, NewRead](
        self, model: type[SelectableModel[NewOwner, NewRead]], on: JoinOn
    ) -> JoinQuery[OwnerT | NewOwner, *ResultTs, NewRead | None]: ...


def select[OwnerT, ReadModelT](
    model: type[SelectableModel[OwnerT, ReadModelT]],
) -> SelectModelQuery[OwnerT, ReadModelT]: ...


async def fetch_all_model[O, R](q: SelectModelQuery[O, R]) -> list[R]: ...
async def fetch_all_join[O, *Ts](q: JoinQuery[O, *Ts]) -> list[tuple[*Ts]]: ...


# ============================================================================
# Concrete test models
# ============================================================================
class User[S = Pending](Model[S, "User[Fetched]"]):
    id: User.Col[int]
    email: User.Col[str]


class Order[S = Pending](Model[S, "Order[Fetched]"]):
    id: Order.Col[int]
    user_id: User.Col[int]
    note: Order.Col[str]
    total: Order.Col[float]


class LineItem[S = Pending](Model[S, "LineItem[Fetched]"]):
    id: LineItem.Col[int]
    order_id: Order.Col[int]
    sku: LineItem.Col[str]


class Unrelated[S = Pending](Model[S, "Unrelated[Fetched]"]):
    id: Unrelated.Col[int]


# ============================================================================
# Happy path -- must be clean
# ============================================================================
async def check() -> None:
    q0 = select(User).where(User.email.eq("a@b.c"))
    _ = assert_type(q0, SelectModelQuery[User[Pending], User[Fetched]])
    _ = assert_type(await fetch_all_model(q0), list[User[Fetched]])

    q1 = select(User).join(Order, on=User.id.matches(Unrelated.id))
    _ = assert_type(
        await fetch_all_join(q1), list[tuple[User[Fetched], Order[Fetched]]]
    )

    # where() accepts a predicate from EITHER joined table (covariance).
    q2 = q1.where(User.email.eq("a@b.c")).where(Order.total.eq(9.99))
    _ = assert_type(
        await fetch_all_join(q2), list[tuple[User[Fetched], Order[Fetched]]]
    )

    # A cross-table predicate built with `&` widens, then fits the union slot.
    _ = q1.where(User.email.eq("x") & Order.total.eq(1.0))

    _ = q1.order_by(Order.total.asc(), User.id.asc())

    q3 = q1.join(LineItem, on=Order.id.matches(LineItem.order_id))
    _ = assert_type(
        await fetch_all_join(q3),
        list[tuple[User[Fetched], Order[Fetched], LineItem[Fetched]]],
    )
    _ = q3.where(LineItem.sku.eq("ABC"))

    # LEFT join -> Optional right side, visible in the tuple.
    q4 = select(User).left_join(Order, on=User.id.matches(Order.user_id))
    _ = assert_type(
        await fetch_all_join(q4),
        list[tuple[User[Fetched], Order[Fetched] | None]],
    )

    # Mixed inner+left chain.
    q5 = (
        select(User)
        .join(Order, on=User.id.matches(Order.user_id))
        .left_join(LineItem, on=Order.id.matches(LineItem.order_id))
    )
    _ = assert_type(
        await fetch_all_join(q5),
        list[tuple[User[Fetched], Order[Fetched], LineItem[Fetched] | None]],
    )


# ============================================================================
# Rejections -- must error (verified by stripping ignores)
# ============================================================================
async def check_rejections() -> None:
    q1 = select(User).join(Order, on=User.id.matches(Order.user_id))
    _ = q1.where(Unrelated.id.eq(1))  # type: ignore[arg-type]
    _ = select(User).join(
        Order,
        on=User.id.matches(Order.note),  # type: ignore[arg-type]
    )

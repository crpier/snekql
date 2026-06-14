"""Prototype D: can the type checker reject *nonsensical* join conditions?

Two mistakes to catch (second is the important one):
  (1) on-condition references a table not in the join:
        select(User).join(Order, on=User.id.matches(Unrelated.id))
  (2) on-condition is on the right table but a column with NO relation:
        select(User).join(Order, on=User.id.matches(Order.note))   # type mismatch
        select(User).join(Order, on=User.id.matches(Order.id))     # both int, no FK

The only way the checker can know a column pairing is "sensible" is if the
schema *declares* the relationship. So this prototype gives snekql
foreign-key-typed columns: an FK column knows the model it references, and the
join condition can only be built from an FK column against its target.

We test what this catches AND what legitimate joins it would block.

Checked with: uv run pyright join_prototypes/proto_d_relations.py
"""
# pyright: reportUninitializedInstanceVariable=false

from __future__ import annotations

from typing import Protocol, Self, assert_type


# --- Expression objects (covariant, per proto_c findings) --------------------
class Predicate[OwnerT_co]:
    def __and__[Other](self, o: Predicate[Other]) -> Predicate[OwnerT_co | Other]: ...


class JoinOn[LeftT_co, RightT_co]:
    """Carries the two model owners a join condition relates."""


# --- Columns -----------------------------------------------------------------
class Attr[OwnerT, ReadValueT]:
    """Plain column."""

    def eq(self, value: ReadValueT) -> Predicate[OwnerT]: ...


class FKAttr[OwnerT, ReadValueT, TargetOwnerT](Attr[OwnerT, ReadValueT]):
    """Foreign-key column: declares the model (TargetOwnerT) it references.

    `references` only accepts a column of the referenced model with a matching
    read type, so the join condition is provably between related tables.
    """

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
    # FK column alias: Target is the *Pending* owner of the referenced model.
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
        # The condition must relate the NEW table to an ALREADY-joined one,
        # in either argument order.
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
# Models with declared relationships
# ============================================================================
class User[S = Pending](Model[S, "User[Fetched]"]):
    id: User.Col[int]
    email: User.Col[str]
    region_code: User.Col[str]


class Order[S = Pending](Model[S, "Order[Fetched]"]):
    id: Order.Col[int]
    user_id: Order.FKCol[User[Pending], int]  # FK -> User
    note: Order.Col[str]


class LineItem[S = Pending](Model[S, "LineItem[Fetched]"]):
    id: LineItem.Col[int]
    order_id: LineItem.FKCol[Order[Pending], int]  # FK -> Order
    sku: LineItem.Col[str]


class Region[S = Pending](Model[S, "Region[Fetched]"]):
    code: Region.Col[str]
    name: Region.Col[str]


class Unrelated[S = Pending](Model[S, "Unrelated[Fetched]"]):
    id: Unrelated.Col[int]


# ============================================================================
# HAPPY PATH -- must be clean
# ============================================================================
async def check_good() -> None:
    # Join along the declared FK relationship (either argument order works).
    q1 = select(User).join(Order, on=Order.user_id.references(User.id))
    _ = assert_type(
        await fetch_all_join(q1), list[tuple[User[Fetched], Order[Fetched]]]
    )

    # Chain along a second declared FK.
    q2 = q1.join(LineItem, on=LineItem.order_id.references(Order.id))
    _ = assert_type(
        await fetch_all_join(q2),
        list[tuple[User[Fetched], Order[Fetched], LineItem[Fetched]]],
    )
    _ = q2.where(User.email.eq("a@b.c") & LineItem.sku.eq("X"))


# ============================================================================
# REJECTIONS -- must error (verified by stripping ignores)
# ============================================================================
async def check_rejections() -> None:
    # (2a) Right table, wrong column by TYPE -- int FK vs str column.
    _ = select(User).join(
        Order,
        on=Order.user_id.references(User.email),  # type: ignore[arg-type]
    )

    # (2b) The join column is not an FK at all (no declared relation):
    #      `Order.note` is a plain Attr, so `.references` does not exist.
    _ = select(User).join(
        Order,
        on=Order.note.references(User.id),  # type: ignore[attr-defined]
    )

    # (1) on-condition references an UNRELATED table: Order.user_id targets
    #     User, so .references(Unrelated.id) is rejected (Unrelated != User).
    _ = select(User).join(
        Order,
        on=Order.user_id.references(Unrelated.id),  # type: ignore[arg-type]
    )

# ============================================================================
# KNOWN GAP -- NOT reliably caught by the type checker
# ============================================================================
async def check_known_gap() -> None:
    # (1b) FK is valid but relates tables NOT being joined here: we join
    #      LineItem, yet the condition relates Order<->User. Because `on`
    #      must accept BOTH argument orderings (the FK can live on either the
    #      new or an existing table), pyright cannot pin NewOwner and lets a
    #      JoinOn[Order, User] satisfy the join(LineItem, ...) slot.
    #      This is an exotic mistake; a cheap runtime check covers it better.
    _ = select(User).join(LineItem, on=Order.user_id.references(User.id))


# ============================================================================
# FLEXIBILITY COST -- legitimate joins this design BLOCKS
# ============================================================================
async def check_blocked_legitimate() -> None:
    # Joining User<->Region on a shared natural key (region_code = code) that
    # is NOT a declared FK. This is a perfectly valid SQL join, but neither
    # column is an FK, so there is no `.references` to express it.
    _ = select(User).join(
        Region,
        on=User.region_code.references(Region.code),  # type: ignore[attr-defined]
    )

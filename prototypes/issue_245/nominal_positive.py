"""Positive inference probes for the nominal staged-builder readiness design."""

from __future__ import annotations

from typing import ClassVar, assert_type

from prototypes.issue_245.nominal_design import (
    Column,
    DeleteDraft,
    DeleteReady,
    Fetched,
    Model,
    Pending,
    Select,
    SelectDraft,
    SelectReady,
    Transaction,
    UpdateAssigned,
    UpdateEmpty,
    UpdateReady,
    UpdateScoped,
    Write,
    delete,
    select,
    update,
)


class User[S = Pending](Model[S, "User[Fetched]"]):
    """Probe model."""

    id: ClassVar[Column[User[Pending], int]]
    name: ClassVar[Column[User[Pending], str]]


class Order[S = Pending](Model[S, "Order[Fetched]"]):
    """Joined probe model."""

    id: ClassVar[Column[Order[Pending], int]]
    user_id: ClassVar[Column[Order[Pending], int]]


assert_type(select(User), SelectDraft[User[Pending], User[Fetched]])
assert_type(select(User).all(), SelectReady[User[Pending], User[Fetched]])
assert_type(
    select(User).where(User.name.eq("Ada")),
    SelectReady[User[Pending], User[Fetched]],
)
assert_type(
    select(User)
    .join(Order, on=Order.user_id.references(User.id))
    .where(Order.id.eq(1)),
    SelectReady[
        User[Pending] | Order[Pending],
        tuple[User[Fetched], Order[Fetched]],
    ],
)
assert_type(
    select(User)
    .where(User.name.eq("Ada"))
    .join(Order, on=Order.user_id.references(User.id)),
    SelectReady[
        User[Pending] | Order[Pending],
        tuple[User[Fetched], Order[Fetched]],
    ],
)

assert_type(delete(User), DeleteDraft[User[Pending], User[Fetched], int])
assert_type(delete(User).all(), DeleteReady[User[Pending], User[Fetched], int])
assert_type(
    delete(User).returning().where(User.name.eq("Ada")),
    DeleteReady[User[Pending], User[Fetched], list[User[Fetched]]],
)
assert_type(
    delete(User).where(User.name.eq("Ada")).returning(User.id),
    DeleteReady[User[Pending], User[Fetched], list[int]],
)

assert_type(update(User), UpdateEmpty[User[Pending], User[Fetched], int])
assert_type(
    update(User).set(User.name.to("Ada")),
    UpdateAssigned[User[Pending], User[Fetched], int],
)
assert_type(
    update(User).all(),
    UpdateScoped[User[Pending], User[Fetched], int],
)
assert_type(
    update(User).set(User.name.to("Ada")).all(),
    UpdateReady[User[Pending], User[Fetched], int],
)
assert_type(
    update(User).where(User.id.eq(1)).set(User.name.to("Ada")),
    UpdateReady[User[Pending], User[Fetched], int],
)
assert_type(
    update(User).returning(User.id).set(User.name.to("Ada")).where(User.id.eq(1)),
    UpdateReady[User[Pending], User[Fetched], list[int]],
)
assert_type(
    update(User).where(User.id.eq(1)).returning().set(User.name.to("Ada")),
    UpdateReady[User[Pending], User[Fetched], list[User[Fetched]]],
)


async def executable_boundaries(
    transaction: Transaction,
    stored_select: Select[User[Fetched]],
    stored_write: Write[int],
) -> None:
    """Erased public aliases retain result inference and require readiness."""

    assert_type(await transaction.fetch_all(stored_select), list[User[Fetched]])
    assert_type(await transaction.execute(stored_write), int)
    assert_type(await transaction.fetch_all(select(User).all()), list[User[Fetched]])
    assert_type(
        await transaction.execute(
            update(User).set(User.name.to("Ada")).where(User.id.eq(1))
        ),
        int,
    )

"""Positive inference probes for the private-typestate readiness design."""

from __future__ import annotations

from typing import ClassVar, assert_type

from prototypes.issue_245.typestate_design import (
    Column,
    DeleteQuery,
    Fetched,
    Model,
    Pending,
    Select,
    SelectQuery,
    Transaction,
    UpdateQuery,
    Write,
    _Executable,
    _Incomplete,
    _UpdateAssigned,
    _UpdateEmpty,
    _UpdateReady,
    _UpdateScoped,
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


assert_type(select(User), SelectQuery[User[Pending], User[Fetched], _Incomplete])
assert_type(
    select(User).all(),
    SelectQuery[User[Pending], User[Fetched], _Executable],
)
assert_type(
    select(User).where(User.name.eq("Ada")),
    SelectQuery[User[Pending], User[Fetched], _Executable],
)
assert_type(
    select(User)
    .join(Order, on=Order.user_id.references(User.id))
    .where(Order.id.eq(1)),
    SelectQuery[
        User[Pending] | Order[Pending],
        tuple[User[Fetched], Order[Fetched]],
        _Executable,
    ],
)
assert_type(
    select(User)
    .where(User.name.eq("Ada"))
    .join(Order, on=Order.user_id.references(User.id)),
    SelectQuery[
        User[Pending] | Order[Pending],
        tuple[User[Fetched], Order[Fetched]],
        _Executable,
    ],
)

assert_type(delete(User), DeleteQuery[User[Pending], User[Fetched], int, _Incomplete])
assert_type(
    delete(User).all(),
    DeleteQuery[User[Pending], User[Fetched], int, _Executable],
)
assert_type(
    delete(User).returning().where(User.name.eq("Ada")),
    DeleteQuery[User[Pending], User[Fetched], list[User[Fetched]], _Executable],
)
assert_type(
    delete(User).where(User.name.eq("Ada")).returning(User.id),
    DeleteQuery[User[Pending], User[Fetched], list[int], _Executable],
)

assert_type(
    update(User),
    UpdateQuery[User[Pending], User[Fetched], int, _UpdateEmpty],
)
assert_type(
    update(User).set(User.name.to("Ada")),
    UpdateQuery[User[Pending], User[Fetched], int, _UpdateAssigned],
)
assert_type(
    update(User).all(),
    UpdateQuery[User[Pending], User[Fetched], int, _UpdateScoped],
)
assert_type(
    update(User).set(User.name.to("Ada")).all(),
    UpdateQuery[User[Pending], User[Fetched], int, _UpdateReady],
)
assert_type(
    update(User).where(User.id.eq(1)).set(User.name.to("Ada")),
    UpdateQuery[User[Pending], User[Fetched], int, _UpdateReady],
)
assert_type(
    update(User).returning(User.id).set(User.name.to("Ada")).where(User.id.eq(1)),
    UpdateQuery[User[Pending], User[Fetched], list[int], _UpdateReady],
)
assert_type(
    update(User).where(User.id.eq(1)).returning().set(User.name.to("Ada")),
    UpdateQuery[User[Pending], User[Fetched], list[User[Fetched]], _UpdateReady],
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

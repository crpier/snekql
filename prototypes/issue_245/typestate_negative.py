"""Expected rejections for the private-typestate readiness design."""

from __future__ import annotations

from typing import ClassVar

from prototypes.issue_245.typestate_design import (
    Column,
    Fetched,
    Model,
    Pending,
    Select,
    Transaction,
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

    user_id: ClassVar[Column[Order[Pending], int]]


incomplete_select: Select[User[Fetched]] = select(User)  # ty: ignore[invalid-assignment]
incomplete_delete: Write[int] = delete(User)  # ty: ignore[invalid-assignment]
assignmentless_update: Write[int] = update(User).all()  # ty: ignore[invalid-assignment]
unscoped_update: Write[int] = update(User)  # ty: ignore[invalid-assignment]


async def incomplete_queries_do_not_cross_runtime(transaction: Transaction) -> None:
    """Every statically guaranteed compilation failure is rejected at consumption."""

    await transaction.fetch_all(select(User))  # ty: ignore[invalid-argument-type]
    await transaction.fetch_all(
        select(User).join(  # ty: ignore[invalid-argument-type]
            Order,
            on=Order.user_id.references(User.id),
        )
    )
    await transaction.execute(delete(User))  # ty: ignore[invalid-argument-type]
    await transaction.execute(
        delete(User).returning()  # ty: ignore[invalid-argument-type]
    )
    await transaction.execute(
        update(User).all()  # ty: ignore[invalid-argument-type]
    )
    await transaction.execute(
        update(User).set(User.name.to("Ada"))  # ty: ignore[invalid-argument-type]
    )
    await transaction.execute(
        update(User).returning().all()  # ty: ignore[invalid-argument-type]
    )

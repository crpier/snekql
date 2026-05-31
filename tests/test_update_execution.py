"""Update query construction, compilation, and execution acceptance tests."""

from __future__ import annotations

from collections.abc import Callable
from typing import cast

from snektest import assert_eq, assert_is_none, assert_raises, test

from snekql import (
    MISSING,
    Database,
    Integer,
    Model,
    Pending,
    QueryConstructionError,
    Text,
    insert,
    select,
    update,
)
from snekql.query import compile_write_sql


@test(mark="fast")
def update_compilation_accepts_multiple_quoted_assignments() -> None:
    """Update compiles multiple assignments in caller-provided order."""

    class Order[S = Pending](Model[S, "Order[object]"]):
        """Table model with identifiers requiring SQLite quoting."""

        __tablename__ = "select"
        status: Order.Col[str] = Text(nullable=False)
        where: Order.Col[str] = Text(nullable=False)

    query = (
        update(Order)
        .set(
            Order.where.to("new"),
            Order.status.to("done"),
        )
        .where(Order.where.ne("old"))
    )

    sql, params = compile_write_sql(query)

    expected_sql = 'UPDATE "select" SET "where" = ?, "status" = ? WHERE ("where" != ?)'
    assert_eq(sql, expected_sql)
    assert_eq(params, ("new", "done", "old"))


@test(mark="fast")
def update_assignments_must_belong_to_target_model() -> None:
    """Update set() rejects assignments built from another table model."""

    class User[S = Pending](Model[S, "User[object]"]):
        """Target table model for ownership checks."""

        email: User.Col[str] = Text(nullable=False)

    class AuditLog[S = Pending](Model[S, "AuditLog[object]"]):
        """Unrelated table model for ownership checks."""

        message: AuditLog.Col[str] = Text(nullable=False)

    set_assignments = cast("Callable[..., object]", update(User).set)

    with assert_raises(QueryConstructionError):
        _ = set_assignments(AuditLog.message.to("wrong table"))


@test(mark="fast")
def update_rejects_generated_and_primary_key_assignments() -> None:
    """Generated and primary key columns are not update-assignable."""

    class User[S = Pending](Model[S, "User[object]"]):
        """Table model with both protected and updateable columns."""

        account_id: User.Col[int] = Integer(primary_key=True)
        email: User.Col[str] = Text(nullable=False)
        revision: User.GenCol[int] = Integer(default=MISSING)

    with assert_raises(QueryConstructionError):
        _ = update(User).set(User.revision.to(2))

    with assert_raises(QueryConstructionError):
        _ = update(User).set(User.account_id.to(2))


@test(mark="medium")
async def update_execute_returns_none_and_supports_explicit_all() -> None:
    """tx.execute(update(...).all()) returns None after full-table update."""

    class User[S = Pending](Model[S, "User[object]"]):
        """Table model updated through the async runtime."""

        id: User.GenCol[int] = Integer(primary_key=True, default=MISSING)
        email: User.Col[str] = Text(nullable=False)
        status: User.Col[str] = Text(nullable=False, default="active")

    database = await Database.initialize(database=":memory:", models=[User])
    try:
        async with database.transaction() as transaction:
            await transaction.execute(insert(User(email="a@example.com")))
            await transaction.execute(insert(User(email="b@example.com")))

            result = await transaction.execute(
                update(User).set(User.status.to("disabled")).all(),
            )
            statuses = await transaction.fetch_all(
                select(User.status).all().order_by(User.id.asc()),
            )
    finally:
        await database.close()

    assert_is_none(result)
    assert_eq(statuses, ["disabled", "disabled"])

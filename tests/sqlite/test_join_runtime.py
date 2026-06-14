"""End-to-end SQLite model-select join execution.

These tests drive the full path: schema startup, inserts, join compilation, and
row materialization into tuples of fetched models.
"""

from __future__ import annotations

from snektest import assert_eq, test

from snekql import (
    MISSING,
    Database,
    Fetched,
    Integer,
    Model,
    Pending,
    Text,
    insert,
    select,
)
from tests.helpers import NULL_LOGGER


class JoinUser[S = Pending](Model[S, "JoinUser[Fetched]"]):
    """Referenced table."""

    id: JoinUser.GenCol[int] = Integer(
        primary_key=True,
        auto_increment=True,
        default=MISSING,
    )
    email: JoinUser.Col[str] = Text(nullable=False)


class JoinOrder[S = Pending](Model[S, "JoinOrder[Fetched]"]):
    """Table with a foreign key to ``JoinUser``."""

    id: JoinOrder.GenCol[int] = Integer(
        primary_key=True,
        auto_increment=True,
        default=MISSING,
    )
    user_id: JoinOrder.FKCol[JoinUser, int] = Integer(foreign_key=True)
    note: JoinOrder.Col[str] = Text(nullable=False)


@test(mark="medium")
async def inner_join_fetches_tuples_of_fetched_models() -> None:
    """An inner join returns one (user, order) tuple per matching row."""

    database = await Database.initialize(
        logger=NULL_LOGGER,
        database=":memory:",
        models=[JoinUser, JoinOrder],
    )
    try:
        async with database.transaction() as tx:
            await tx.execute(insert(JoinUser(email="alice@example.com")))
            await tx.execute(insert(JoinUser(email="bob@example.com")))
            await tx.execute(insert(JoinOrder(user_id=1, note="first")))
            await tx.execute(insert(JoinOrder(user_id=1, note="second")))

            rows = await tx.fetch_all(
                select(JoinUser)
                .join(JoinOrder, on=JoinOrder.user_id.references(JoinUser.id))
                .where(JoinUser.email.eq("alice@example.com"))
                .order_by(JoinOrder.note.asc()),
            )
    finally:
        await database.close()

    assert_eq(len(rows), 2)
    first_user, first_order = rows[0]
    assert_eq(first_user.email, "alice@example.com")
    assert_eq(first_order.note, "first")
    assert_eq(first_order.user_id, 1)
    assert_eq(rows[1][1].note, "second")


@test(mark="medium")
async def left_join_yields_none_for_unmatched_right_rows() -> None:
    """A left join keeps the left row and materializes a missing right as None."""

    database = await Database.initialize(
        logger=NULL_LOGGER,
        database=":memory:",
        models=[JoinUser, JoinOrder],
    )
    try:
        async with database.transaction() as tx:
            await tx.execute(insert(JoinUser(email="alice@example.com")))
            await tx.execute(insert(JoinUser(email="bob@example.com")))
            await tx.execute(insert(JoinOrder(user_id=1, note="first")))

            rows = await tx.fetch_all(
                select(JoinUser)
                .left_join(
                    JoinOrder,
                    on=JoinOrder.user_id.references(JoinUser.id),
                )
                .where(JoinUser.email.eq("bob@example.com")),
            )
    finally:
        await database.close()

    assert_eq(len(rows), 1)
    user, order = rows[0]
    assert_eq(user.email, "bob@example.com")
    assert order is None


@test(mark="medium")
async def projection_join_fetches_tuples_of_scalars() -> None:
    """A projection join returns the projected (email, note) columns per row."""

    database = await Database.initialize(
        logger=NULL_LOGGER,
        database=":memory:",
        models=[JoinUser, JoinOrder],
    )
    try:
        async with database.transaction() as tx:
            await tx.execute(insert(JoinUser(email="alice@example.com")))
            await tx.execute(insert(JoinOrder(user_id=1, note="first")))
            await tx.execute(insert(JoinOrder(user_id=1, note="second")))

            rows = await tx.fetch_all(
                select(JoinUser.email, JoinOrder.note)
                .join(JoinOrder, on=JoinOrder.user_id.references(JoinUser.id))
                .order_by(JoinOrder.note.asc())
                .all(),
            )
    finally:
        await database.close()

    assert_eq(
        rows,
        [
            ("alice@example.com", "first"),
            ("alice@example.com", "second"),
        ],
    )


@test(mark="medium")
async def projection_join_filters_on_a_table_it_does_not_project() -> None:
    """A single-column projection can filter a joined but unprojected table."""

    database = await Database.initialize(
        logger=NULL_LOGGER,
        database=":memory:",
        models=[JoinUser, JoinOrder],
    )
    try:
        async with database.transaction() as tx:
            await tx.execute(insert(JoinUser(email="alice@example.com")))
            await tx.execute(insert(JoinOrder(user_id=1, note="keep")))
            await tx.execute(insert(JoinOrder(user_id=1, note="drop")))

            rows = await tx.fetch_all(
                select(JoinUser.email)
                .join(JoinOrder, on=JoinOrder.user_id.references(JoinUser.id))
                .where(JoinOrder.note.eq("keep")),
            )
    finally:
        await database.close()

    assert_eq(rows, ["alice@example.com"])

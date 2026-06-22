"""Update query construction, compilation, and execution acceptance tests."""

from __future__ import annotations

from collections.abc import Callable
from typing import cast

from snektest import assert_eq, assert_raises, test

from snekql.sqlite import (
    MISSING,
    CurrentTimestamp,
    Database,
    Fetched,
    Integer,
    Model,
    Pending,
    QueryConstructionError,
    Text,
    insert,
    select,
    update,
)
from snekql.sqlite.query import compile_sqlite_write_sql


@test(mark="fast")
def update_compilation_accepts_multiple_quoted_assignments() -> None:
    """Update compiles multiple assignments in caller-provided order."""

    class Order[S = Pending](Model[S, "Order[Fetched]"]):
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

    sql, params = compile_sqlite_write_sql(query)

    expected_sql = 'UPDATE "select" SET "where" = ?, "status" = ? WHERE ("where" != ?)'
    assert_eq(sql, expected_sql)
    assert_eq(params, ("new", "done", "old"))


@test(mark="fast")
def update_set_current_timestamp_renders_server_expression() -> None:
    """A CurrentTimestamp assignment renders inline server SQL with no param."""

    class Doc[S = Pending](Model[S, "Doc[Fetched]"]):
        """Table model with a column refreshed to the server clock on update."""

        title: Doc.Col[str] = Text(nullable=False)
        edited_at: Doc.Col[str] = Text(nullable=False)

    query = (
        update(Doc)
        .set(Doc.edited_at.to(CurrentTimestamp), Doc.title.to("new"))
        .where(Doc.title.ne("old"))
    )

    sql, params = compile_sqlite_write_sql(query)

    expected_sql = (
        'UPDATE "doc" SET '
        "\"edited_at\" = strftime('%Y-%m-%dT%H:%M:%fZ', 'now'), "
        '"title" = ? WHERE ("title" != ?)'
    )
    assert_eq(sql, expected_sql)
    assert_eq(params, ("new", "old"))


@test(mark="fast")
def update_assignments_must_belong_to_target_model() -> None:
    """Update set() rejects assignments built from another table model."""

    class User[S = Pending](Model[S, "User[Fetched]"]):
        """Target table model for ownership checks."""

        email: User.Col[str] = Text(nullable=False)

    class AuditLog[S = Pending](Model[S, "AuditLog[Fetched]"]):
        """Unrelated table model for ownership checks."""

        message: AuditLog.Col[str] = Text(nullable=False)

    set_assignments = cast("Callable[..., object]", update(User).set)

    with assert_raises(QueryConstructionError):
        _ = set_assignments(AuditLog.message.to("wrong table"))


@test(mark="fast")
def update_rejects_generated_and_primary_key_assignments() -> None:
    """Generated and primary key columns are not update-assignable."""

    class User[S = Pending](Model[S, "User[Fetched]"]):
        """Table model with both protected and updateable columns."""

        account_id: User.Col[int] = Integer(primary_key=True)
        email: User.Col[str] = Text(nullable=False)
        revision: User.GenCol[int] = Integer(default=MISSING)

    with assert_raises(QueryConstructionError):
        _ = update(User).set(User.revision.to(2))

    with assert_raises(QueryConstructionError):
        _ = update(User).set(User.account_id.to(2))


@test(mark="medium")
async def update_execute_returns_affected_row_count() -> None:
    """tx.execute(update(...)) returns the count of rows the statement changed."""

    class User[S = Pending](Model[S, "User[Fetched]"]):
        """Table model updated through the async runtime."""

        id: User.GenCol[int] = Integer(primary_key=True, default=MISSING)
        email: User.Col[str] = Text(nullable=False)
        status: User.Col[str] = Text(nullable=False, default="active")

    database = await Database.initialize(database=":memory:", models=[User])
    try:
        async with database.transaction() as tx:
            await tx.execute(insert(User(email="a@example.com")))
            await tx.execute(insert(User(email="b@example.com")))

            all_count = await tx.execute(
                update(User).set(User.status.to("disabled")).all(),
            )
            filtered_count = await tx.execute(
                update(User)
                .set(User.status.to("active"))
                .where(User.email.eq("a@example.com")),
            )
            no_match_count = await tx.execute(
                update(User)
                .set(User.status.to("archived"))
                .where(User.email.eq("missing@example.com")),
            )
            statuses = await tx.fetch_all(
                select(User.status).all().order_by(User.id.asc()),
            )
    finally:
        await database.close()

    assert_eq(all_count, 2)
    assert_eq(filtered_count, 1)
    assert_eq(no_match_count, 0)
    assert_eq(statuses, ["active", "disabled"])


@test(mark="medium")
async def update_to_current_timestamp_refreshes_value_from_server_clock() -> None:
    """set(col.to(CurrentTimestamp)) refreshes the column from the database clock."""

    class Doc[S = Pending](Model[S, "Doc[Fetched]"]):
        """Table model whose edited_at refreshes to the server clock on update."""

        id: Doc.GenCol[int] = Integer(primary_key=True, default=MISSING)
        title: Doc.Col[str] = Text(nullable=False)
        edited_at: Doc.Col[str] = Text(nullable=False)

    database = await Database.initialize(database=":memory:", models=[Doc])
    try:
        async with database.transaction() as tx:
            await tx.execute(
                insert(Doc(title="draft", edited_at="2000-01-01T00:00:00.000Z")),
            )
            _ = await tx.execute(
                update(Doc).set(Doc.edited_at.to(CurrentTimestamp)).all(),
            )
            refreshed = await tx.fetch_one(select(Doc.edited_at).all())
    finally:
        await database.close()

    # Server-filled ISO-8601 UTC sorts lexicographically, so a refreshed value is
    # strictly greater than the explicit epoch-era value written on insert.
    assert_eq(refreshed > "2000-01-01T00:00:00.000Z", True)

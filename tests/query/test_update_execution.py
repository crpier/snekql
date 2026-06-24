"""Update query construction, compilation, and execution acceptance tests."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from typing import cast

from snektest import assert_eq, assert_raises, test

from snekql.sqlite import (
    PENDING_GENERATION,
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
def update_accepts_generated_and_primary_key_assignments() -> None:
    """Generated and primary key columns are update-assignable (no immutability).

    snekql models no immutable columns (ADR 0006): the update builder guards only
    that an assignment targets the queried model, so both a generated column and a
    primary key compile into ``SET`` like any other column.
    """

    class User[S = Pending](Model[S, "User[Fetched]"]):
        """Table model with a primary key and a generated column."""

        account_id: User.GenCol[int] = Integer(
            primary_key=True, default=PENDING_GENERATION
        )
        email: User.Col[str] = Text(nullable=False)
        revision: User.GenCol[int] = Integer(default=PENDING_GENERATION)

    query = update(User).set(User.account_id.to(2), User.revision.to(3)).all()

    sql, params = compile_sqlite_write_sql(query)

    assert_eq(sql, 'UPDATE "user" SET "account_id" = ?, "revision" = ?')
    assert_eq(params, (2, 3))


@test(mark="medium")
async def update_execute_returns_affected_row_count() -> None:
    """tx.execute(update(...)) returns the count of rows the statement changed."""

    class User[S = Pending](Model[S, "User[Fetched]"]):
        """Table model updated through the async runtime."""

        id: User.GenCol[int] = Integer(primary_key=True, default=PENDING_GENERATION)
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

        id: Doc.GenCol[int] = Integer(primary_key=True, default=PENDING_GENERATION)
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


@test(mark="medium")
async def update_writes_a_server_default_generated_timestamp() -> None:
    """One GenCol fills from the server clock on insert and is writable on update.

    The managed-timestamp use case (ADR 0006): ``updated_at`` is omitted on insert
    so the database fills it via ``default=CurrentTimestamp``, then the same
    generated column accepts both an explicit value and a ``CurrentTimestamp``
    refresh on update -- assignments the old immutability guard rejected.
    """

    class Memory[S = Pending](Model[S, "Memory[Fetched]"]):
        """Table model whose updated_at is server-filled yet update-writable."""

        id: Memory.GenCol[int] = Integer(primary_key=True, default=PENDING_GENERATION)
        content: Memory.Col[str] = Text(nullable=False)
        updated_at: Memory.GenCol[datetime] = Text(default=CurrentTimestamp)

    explicit = datetime(2000, 1, 1, tzinfo=UTC)
    database = await Database.initialize(database=":memory:", models=[Memory])
    try:
        async with database.transaction() as tx:
            await tx.execute(insert(Memory(content="first")))
            filled = await tx.fetch_one(select(Memory.updated_at).all())

            _ = await tx.execute(
                update(Memory).set(Memory.updated_at.to(explicit)).all(),
            )
            overwritten = await tx.fetch_one(select(Memory.updated_at).all())

            _ = await tx.execute(
                update(Memory).set(Memory.updated_at.to(CurrentTimestamp)).all(),
            )
            refreshed = await tx.fetch_one(select(Memory.updated_at).all())
    finally:
        await database.close()

    # Insert omitted the column, so the database supplied the value.
    assert isinstance(filled, datetime)
    # A generated column now accepts an explicit update value...
    assert_eq(overwritten, explicit)
    # ...and a server-clock refresh, which lands past the epoch-era value.
    assert isinstance(refreshed, datetime)
    assert_eq(refreshed > explicit, True)

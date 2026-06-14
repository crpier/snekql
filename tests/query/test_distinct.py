"""`select(...).distinct()` construction, compilation, and dedup execution tests.

`DISTINCT` collapses duplicate rows without changing the selected columns or the
result shape, so it is a single flag emitted as `SELECT DISTINCT` and shared by
every select query class. The keyword is identical in SQLite and MariaDB.
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
    sqlite,
)
from snekql.sqlite.query import compile_sqlite_select_sql
from tests.helpers import NULL_LOGGER


class User[S = Pending](sqlite.Model[S, "User[Fetched]"]):
    """Referenced table used by join distinct compilation."""

    id: User.GenCol[int] = sqlite.Integer(
        primary_key=True,
        auto_increment=True,
        default=MISSING,
    )
    email: User.Col[str] = sqlite.Text(nullable=False)


class Order[S = Pending](sqlite.Model[S, "Order[Fetched]"]):
    """Table with a foreign key to ``User``."""

    id: Order.GenCol[int] = sqlite.Integer(
        primary_key=True,
        auto_increment=True,
        default=MISSING,
    )
    user_id: Order.FKCol[User, int] = sqlite.ForeignKey(User.id)
    note: Order.Col[str] = sqlite.Text(nullable=False)


@test(mark="fast")
def distinct_model_select_emits_select_distinct() -> None:
    """A model select with distinct prefixes every column with DISTINCT."""

    sql, params = compile_sqlite_select_sql(select(User).all().distinct())

    assert_eq(sql, 'SELECT DISTINCT "id", "email" FROM "user"')
    assert_eq(params, ())


@test(mark="fast")
def distinct_single_column_select_emits_select_distinct() -> None:
    """A single-column select with distinct emits SELECT DISTINCT."""

    sql, params = compile_sqlite_select_sql(select(User.email).all().distinct())

    assert_eq(sql, 'SELECT DISTINCT "email" FROM "user"')
    assert_eq(params, ())


@test(mark="fast")
def distinct_multi_column_select_emits_select_distinct() -> None:
    """A multi-column select with distinct emits SELECT DISTINCT."""

    sql, params = compile_sqlite_select_sql(
        select(User.id, User.email).all().distinct(),
    )

    assert_eq(sql, 'SELECT DISTINCT "id", "email" FROM "user"')
    assert_eq(params, ())


@test(mark="fast")
def distinct_joined_select_emits_select_distinct() -> None:
    """A joined select with distinct prefixes the qualified column list."""

    sql, params = compile_sqlite_select_sql(
        select(User).join(Order, on=Order.user_id.references(User.id)).all().distinct(),
    )

    expected = " ".join(
        [
            'SELECT DISTINCT "user"."id", "user"."email",',
            '"order"."id", "order"."user_id", "order"."note"',
            'FROM "user"',
            'INNER JOIN "order" ON "order"."user_id" = "user"."id"',
        ],
    )
    assert_eq(sql, expected)
    assert_eq(params, ())


@test(mark="fast")
def distinct_composes_with_where_order_by_and_limit() -> None:
    """Distinct sits between SELECT and the column list, leaving clauses intact."""

    sql, params = compile_sqlite_select_sql(
        select(User.email)
        .where(User.email.in_("a@example.com", "b@example.com"))
        .order_by(User.email.asc())
        .limit(5)
        .distinct(),
    )

    expected = (
        'SELECT DISTINCT "email" FROM "user" '
        'WHERE ("email" IN (?, ?)) ORDER BY "email" ASC LIMIT ?'
    )
    assert_eq(sql, expected)
    assert_eq(params, ("a@example.com", "b@example.com", 5))


@test(mark="fast")
def distinct_is_order_independent() -> None:
    """Calling distinct before other clauses yields identical SQL."""

    before = select(User.email).distinct().where(User.email.eq("a@example.com"))
    after = select(User.email).where(User.email.eq("a@example.com")).distinct()

    assert_eq(
        compile_sqlite_select_sql(before),
        compile_sqlite_select_sql(after),
    )


@test(mark="fast")
def distinct_is_idempotent() -> None:
    """Calling distinct twice is the same as calling it once."""

    once = select(User.email).all().distinct()
    twice = select(User.email).all().distinct().distinct()

    assert_eq(
        compile_sqlite_select_sql(once),
        compile_sqlite_select_sql(twice),
    )


@test(mark="medium")
async def distinct_collapses_duplicate_rows_at_runtime() -> None:
    """An end-to-end distinct select returns each duplicated value once."""

    class Visit[S = Pending](Model[S, "Visit[Fetched]"]):
        """Table holding duplicate status values."""

        id: Visit.GenCol[int] = Integer(
            primary_key=True,
            auto_increment=True,
            default=MISSING,
        )
        status: Visit.Col[str] = Text(nullable=False)

    database = await Database.initialize(
        logger=NULL_LOGGER, database=":memory:", models=[Visit]
    )
    try:
        async with database.transaction() as tx:
            await tx.execute(insert(Visit(status="active")))
            await tx.execute(insert(Visit(status="active")))
            await tx.execute(insert(Visit(status="disabled")))
            rows = await tx.fetch_all(
                select(Visit.status).all().order_by(Visit.status.asc()).distinct(),
            )
    finally:
        await database.close()

    assert_eq(rows, ["active", "disabled"])

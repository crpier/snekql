"""Select query construction, compilation, and fetch execution tests."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from sqlite3 import connect
from tempfile import TemporaryDirectory
from typing import Any, cast

from snektest import assert_eq, assert_raises, test

from snekql.sqlite import (
    PENDING_GENERATION,
    Database,
    Fetched,
    Integer,
    Model,
    ModelValidationError,
    MultipleResultsError,
    NoResultError,
    Pending,
    QueryCompilationError,
    QueryConstructionError,
    Text,
    insert,
    select,
)
from snekql.sqlite.query import (
    compile_sqlite_select_sql,
    materialize_sqlite_select_row,
)


@test(mark="medium")
async def fetch_all_materializes_model_rows() -> None:
    """Model selects return fetched-state model instances decoded from rows."""

    class User[S = Pending](Model[S, "User[Fetched]"]):
        """Table model selected through the runtime."""

        id: User.GenCol[int] = Integer(
            primary_key=True,
            auto_increment=True,
            default=PENDING_GENERATION,
        )
        email: User.Col[str] = Text(nullable=False)
        status: User.Col[str] = Text(nullable=False, default="active")

    database = await Database.initialize(database=":memory:", models=[User])
    try:
        async with database.transaction() as tx:
            await tx.execute(insert(User(email="a@example.com")))
            await tx.execute(
                insert(User(email="b@example.com", status="disabled")),
            )
            rows = await tx.fetch_all(select(User).all())
    finally:
        await database.close()

    fetched_user: User[Fetched] = rows[0]
    assert_eq(fetched_user.id, 1)
    assert_eq(fetched_user.email, "a@example.com")
    assert_eq(fetched_user.status, "active")
    assert_eq(
        repr(fetched_user),
        "User[Fetched](id=1, email='a@example.com', status='active')",
    )
    assert_eq([row.email for row in rows], ["a@example.com", "b@example.com"])


@test(mark="medium")
async def fetch_all_returns_scalar_values_for_single_column_selects() -> None:
    """Single-column selects return decoded scalar values instead of row tuples."""

    class User[S = Pending](Model[S, "User[Fetched]"]):
        """Table model selected through the runtime."""

        id: User.GenCol[int] = Integer(
            primary_key=True,
            auto_increment=True,
            default=PENDING_GENERATION,
        )
        email: User.Col[str] = Text(nullable=False)
        status: User.Col[str] = Text(nullable=False, default="active")

    database = await Database.initialize(database=":memory:", models=[User])
    try:
        async with database.transaction() as tx:
            await tx.execute(insert(User(email="a@example.com")))
            await tx.execute(
                insert(User(email="b@example.com", status="disabled")),
            )
            emails = await tx.fetch_all(
                select(User.email)
                .where(User.status.eq("active"))
                .order_by(User.email.desc()),
            )
    finally:
        await database.close()

    assert_eq(emails, ["a@example.com"])


@test(mark="medium")
async def fetch_all_returns_tuples_for_multi_column_selects() -> None:
    """Multi-column selects return value tuples in selection order."""

    class User[S = Pending](Model[S, "User[Fetched]"]):
        """Table model selected through the runtime."""

        id: User.GenCol[int] = Integer(
            primary_key=True,
            auto_increment=True,
            default=PENDING_GENERATION,
        )
        email: User.Col[str] = Text(nullable=False)
        status: User.Col[str] = Text(nullable=False, default="active")

    database = await Database.initialize(database=":memory:", models=[User])
    try:
        async with database.transaction() as tx:
            await tx.execute(insert(User(email="a@example.com")))
            await tx.execute(
                insert(User(email="b@example.com", status="disabled")),
            )
            rows = await tx.fetch_all(
                select(User.status, User.email).all().order_by(User.id.asc()),
            )
    finally:
        await database.close()

    assert_eq(rows, [("active", "a@example.com"), ("disabled", "b@example.com")])


@test(mark="fast")
def select_rejects_mixed_model_and_field_selections() -> None:
    """V1 rejects mixed model+field selections before SQL compilation."""

    class User[S = Pending](Model[S, "User[Fetched]"]):
        """Table model used by invalid select construction checks."""

        email: User.Col[str] = Text(nullable=False)

    select_fn = cast("Callable[..., object]", select)

    with assert_raises(QueryConstructionError):
        _ = select_fn(User, User.email)


@test(mark="fast")
def select_rejects_projecting_a_table_that_is_not_joined() -> None:
    """Projecting a column whose table is never joined fails at compilation.

    A cross-table projection is constructible (joins may still be added), but
    compiling one that references a table outside the FROM/JOIN graph is
    rejected -- the runtime mirror of the static dual-union scope check.
    """

    class User[S = Pending](Model[S, "User[Fetched]"]):
        """First table model used by invalid select compilation checks."""

        email: User.Col[str] = Text(nullable=False)

    class AuditLog[S = Pending](Model[S, "AuditLog[Fetched]"]):
        """Second table model used by invalid select compilation checks."""

        message: AuditLog.Col[str] = Text(nullable=False)

    select_fn = cast("Callable[..., Any]", select)
    query = select_fn(User.email, AuditLog.message).all()

    with assert_raises(QueryCompilationError):
        _ = compile_sqlite_select_sql(query)


class _Person[S = Pending](Model[S, "_Person[Fetched]"]):
    """Table model with a nullable column for fetch cardinality tests."""

    id: _Person.GenCol[int] = Integer(
        primary_key=True,
        auto_increment=True,
        default=PENDING_GENERATION,
    )
    email: _Person.Col[str] = Text(nullable=False)
    nickname: _Person.Col[str | None] = Text(nullable=True, default=None)


@test(mark="medium")
async def fetch_one_returns_the_single_matching_row() -> None:
    """fetch_one returns the one matching row for an exactly-one select."""

    database = await Database.initialize(database=":memory:", models=[_Person])
    try:
        async with database.transaction() as tx:
            await tx.execute(insert(_Person(email="a@example.com")))

            email = await tx.fetch_one(
                select(_Person.email).where(_Person.email.eq("a@example.com")),
            )
            person = await tx.fetch_one(
                select(_Person).where(_Person.email.eq("a@example.com")),
            )
    finally:
        await database.close()

    assert_eq(email, "a@example.com")
    assert_eq(person.email, "a@example.com")


@test(mark="medium")
async def fetch_one_raises_when_no_row_matches() -> None:
    """fetch_one raises NoResultError rather than returning None for no row."""

    database = await Database.initialize(database=":memory:", models=[_Person])
    try:
        async with database.transaction() as tx:
            with assert_raises(NoResultError):
                _ = await tx.fetch_one(
                    select(_Person.email).where(_Person.email.eq("missing")),
                )
    finally:
        await database.close()


@test(mark="medium")
async def fetch_one_raises_when_more_than_one_row_matches() -> None:
    """fetch_one raises MultipleResultsError when the select matches many rows."""

    database = await Database.initialize(database=":memory:", models=[_Person])
    try:
        async with database.transaction() as tx:
            await tx.execute(insert(_Person(email="a@example.com")))
            await tx.execute(insert(_Person(email="b@example.com")))

            with assert_raises(MultipleResultsError):
                _ = await tx.fetch_one(select(_Person.email).all())

            # "first of N" is opt-in through an explicit limit.
            first = await tx.fetch_one(
                select(_Person.email).all().order_by(_Person.id.asc()).limit(1),
            )
    finally:
        await database.close()

    assert_eq(first, "a@example.com")


@test(mark="medium")
async def fetch_one_distinguishes_sql_null_from_a_missing_row() -> None:
    """A returned None from a single-value fetch_one means SQL NULL, not no row."""

    database = await Database.initialize(database=":memory:", models=[_Person])
    try:
        async with database.transaction() as tx:
            await tx.execute(insert(_Person(email="a@example.com", nickname=None)))

            nickname = await tx.fetch_one(
                select(_Person.nickname).where(_Person.email.eq("a@example.com")),
            )
            with assert_raises(NoResultError):
                _ = await tx.fetch_one(
                    select(_Person.nickname).where(_Person.email.eq("missing")),
                )
    finally:
        await database.close()

    # The row exists; its nickname is SQL NULL, surfaced unambiguously as None.
    assert_eq(nickname, None)


@test(mark="medium")
async def fetch_one_or_none_returns_none_for_a_missing_row() -> None:
    """fetch_one_or_none yields None for no row and the row when exactly one."""

    database = await Database.initialize(database=":memory:", models=[_Person])
    try:
        async with database.transaction() as tx:
            missing = await tx.fetch_one_or_none(
                select(_Person).where(_Person.email.eq("missing")),
            )
            await tx.execute(insert(_Person(email="a@example.com")))
            found = await tx.fetch_one_or_none(
                select(_Person).where(_Person.email.eq("a@example.com")),
            )
    finally:
        await database.close()

    assert_eq(missing, None)
    assert found is not None
    assert_eq(found.email, "a@example.com")


@test(mark="medium")
async def fetch_one_or_none_raises_when_more_than_one_row_matches() -> None:
    """fetch_one_or_none caps cardinality at one like fetch_one does."""

    database = await Database.initialize(database=":memory:", models=[_Person])
    try:
        async with database.transaction() as tx:
            await tx.execute(insert(_Person(email="a@example.com")))
            await tx.execute(insert(_Person(email="b@example.com")))

            with assert_raises(MultipleResultsError):
                _ = await tx.fetch_one_or_none(select(_Person).all())
    finally:
        await database.close()


@test(mark="fast")
async def fetch_one_or_none_rejects_single_value_selects() -> None:
    """fetch_one_or_none refuses the shape whose None would be ambiguous."""

    database = await Database.initialize(database=":memory:", models=[_Person])
    try:
        async with database.transaction() as tx:
            with assert_raises(QueryConstructionError):
                _ = await tx.fetch_one_or_none(
                    cast("Any", select(_Person.nickname).all()),
                )
    finally:
        await database.close()


@test(mark="medium")
async def fetch_all_validates_decoded_database_values() -> None:
    """Fetched rows are decoded and validated before model materialization."""

    class FeatureFlag[S = Pending](Model[S, "FeatureFlag[Fetched]"]):
        """Table model with a ``bool`` logical type stored as INTEGER."""

        id: FeatureFlag.GenCol[int] = Integer(
            primary_key=True, default=PENDING_GENERATION
        )
        enabled: FeatureFlag.Col[bool] = Integer(nullable=False)

    with TemporaryDirectory() as directory:
        database_path = Path(directory) / "app.db"
        database = await Database.initialize(
            database=database_path,
            models=[FeatureFlag],
        )
        await database.close()

        connection = connect(database_path)
        try:
            _ = connection.execute(
                'INSERT INTO "feature_flag" ("id", "enabled") VALUES (1, 2)',
            )
            connection.commit()
        finally:
            connection.close()

        database = await Database.initialize(
            database=database_path,
            models=[FeatureFlag],
        )
        try:
            async with database.transaction() as tx:
                with assert_raises(ModelValidationError):
                    _ = await tx.fetch_all(select(FeatureFlag).all())
        finally:
            await database.close()


@test(mark="fast")
def sqlite_select_materialization_asserts_database_row_shape() -> None:
    """SQLite select materialization treats row-shape mismatch as invariant failure."""

    class User[S = Pending](Model[S, "User[Fetched]"]):
        """Table model used by row-shape materialization checks."""

        email: User.Col[str] = Text(nullable=False)

    query = select(User.email).all()

    with assert_raises(AssertionError):
        _ = materialize_sqlite_select_row(query, ())

    with assert_raises(AssertionError):
        _ = materialize_sqlite_select_row(query, ("a@example.com", "extra"))


@test(mark="fast")
def select_compilation_requires_explicit_all_or_where() -> None:
    """Select queries must choose filtered or unfiltered operation to compile."""

    class User[S = Pending](Model[S, "User[Fetched]"]):
        """Table model used by select compilation checks."""

        email: User.Col[str] = Text(nullable=False)

    with assert_raises(QueryCompilationError):
        _ = compile_sqlite_select_sql(select(User))


@test(mark="fast")
def select_compilation_parameterizes_filters_limits_and_offsets() -> None:
    """Compiled select SQL is quoted and parameterized in observable order."""

    class User[S = Pending](Model[S, "User[Fetched]"]):
        """Table model used by select compilation checks."""

        email: User.Col[str] = Text(nullable=False)
        status: User.Col[str] = Text(nullable=False)

    query = (
        select(User.email, User.status)
        .where(User.status.in_("active", "disabled"))
        .order_by(User.email.asc())
        .offset(2)
    )

    sql, params = compile_sqlite_select_sql(query)

    expected_sql = (
        'SELECT "email", "status" FROM "user" '
        'WHERE ("status" IN (?, ?)) ORDER BY "email" ASC LIMIT -1 OFFSET ?'
    )
    assert_eq(sql, expected_sql)
    assert_eq(params, ("active", "disabled", 2))

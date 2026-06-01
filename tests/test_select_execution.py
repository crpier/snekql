"""Select query construction, compilation, and fetch execution tests."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from sqlite3 import connect
from tempfile import TemporaryDirectory
from typing import cast

from snektest import assert_eq, assert_raises, test

from snekql import (
    MISSING,
    Boolean,
    Database,
    Fetched,
    Integer,
    Model,
    ModelValidationError,
    Pending,
    QueryCompilationError,
    QueryConstructionError,
    Text,
    insert,
    select,
)
from snekql.query import compile_select_sql
from tests.logging_helpers import NULL_LOGGER


@test(mark="medium")
async def fetch_all_materializes_model_rows() -> None:
    """Model selects return fetched-state model instances decoded from rows."""

    class User[S = Pending](Model[S, "User[Fetched]"]):
        """Table model selected through the runtime."""

        id: User.GenCol[int] = Integer(
            primary_key=True,
            auto_increment=True,
            default=MISSING,
        )
        email: User.Col[str] = Text(nullable=False)
        status: User.Col[str] = Text(nullable=False, default="active")

    database = await Database.initialize(
        NULL_LOGGER, database=":memory:", models=[User]
    )
    try:
        async with database.transaction() as transaction:
            await transaction.execute(insert(User(email="a@example.com")))
            await transaction.execute(
                insert(User(email="b@example.com", status="disabled")),
            )
            rows = await transaction.fetch_all(select(User).all())
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
            default=MISSING,
        )
        email: User.Col[str] = Text(nullable=False)
        status: User.Col[str] = Text(nullable=False, default="active")

    database = await Database.initialize(
        NULL_LOGGER, database=":memory:", models=[User]
    )
    try:
        async with database.transaction() as transaction:
            await transaction.execute(insert(User(email="a@example.com")))
            await transaction.execute(
                insert(User(email="b@example.com", status="disabled")),
            )
            emails = await transaction.fetch_all(
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
            default=MISSING,
        )
        email: User.Col[str] = Text(nullable=False)
        status: User.Col[str] = Text(nullable=False, default="active")

    database = await Database.initialize(
        NULL_LOGGER, database=":memory:", models=[User]
    )
    try:
        async with database.transaction() as transaction:
            await transaction.execute(insert(User(email="a@example.com")))
            await transaction.execute(
                insert(User(email="b@example.com", status="disabled")),
            )
            rows = await transaction.fetch_all(
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
def select_rejects_fields_from_multiple_models() -> None:
    """V1 select queries do not support joins across table models."""

    class User[S = Pending](Model[S, "User[Fetched]"]):
        """First table model used by invalid select construction checks."""

        email: User.Col[str] = Text(nullable=False)

    class AuditLog[S = Pending](Model[S, "AuditLog[Fetched]"]):
        """Second table model used by invalid select construction checks."""

        message: AuditLog.Col[str] = Text(nullable=False)

    select_fn = cast("Callable[..., object]", select)

    with assert_raises(QueryConstructionError):
        _ = select_fn(User.email, AuditLog.message)


@test(mark="medium")
async def fetch_one_returns_first_row_or_none_without_cardinality_checks() -> None:
    """fetch_one returns the first selected row and treats empty results as None."""

    class User[S = Pending](Model[S, "User[Fetched]"]):
        """Table model selected through fetch_one."""

        id: User.GenCol[int] = Integer(
            primary_key=True,
            auto_increment=True,
            default=MISSING,
        )
        email: User.Col[str] = Text(nullable=False)

    database = await Database.initialize(
        NULL_LOGGER, database=":memory:", models=[User]
    )
    try:
        async with database.transaction() as transaction:
            await transaction.execute(insert(User(email="a@example.com")))
            await transaction.execute(insert(User(email="b@example.com")))

            first_email = await transaction.fetch_one(
                select(User.email).all().order_by(User.id.asc()),
            )
            no_email = await transaction.fetch_one(select(User.email).all().limit(0))
    finally:
        await database.close()

    assert_eq(first_email, "a@example.com")
    assert_eq(no_email, None)


@test(mark="medium")
async def fetch_all_validates_decoded_database_values() -> None:
    """Fetched rows are decoded and validated before model materialization."""

    class FeatureFlag[S = Pending](Model[S, "FeatureFlag[Fetched]"]):
        """Table model with a logical Boolean SQLite encoding."""

        id: FeatureFlag.GenCol[int] = Integer(primary_key=True, default=MISSING)
        enabled: FeatureFlag.Col[bool] = Boolean(nullable=False)

    with TemporaryDirectory() as directory:
        database_path = Path(directory) / "app.db"
        database = await Database.initialize(
            NULL_LOGGER,
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
            NULL_LOGGER,
            database=database_path,
            models=[FeatureFlag],
        )
        try:
            async with database.transaction() as transaction:
                with assert_raises(ModelValidationError):
                    _ = await transaction.fetch_all(select(FeatureFlag).all())
        finally:
            await database.close()


@test(mark="fast")
def select_compilation_requires_explicit_all_or_where() -> None:
    """Select queries must choose filtered or unfiltered operation to compile."""

    class User[S = Pending](Model[S, "User[Fetched]"]):
        """Table model used by select compilation checks."""

        email: User.Col[str] = Text(nullable=False)

    with assert_raises(QueryCompilationError):
        _ = compile_select_sql(select(User))


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

    sql, params = compile_select_sql(query)

    expected_sql = (
        'SELECT "email", "status" FROM "user" '
        'WHERE ("status" IN (?, ?)) ORDER BY "email" ASC LIMIT -1 OFFSET ?'
    )
    assert_eq(sql, expected_sql)
    assert_eq(params, ("active", "disabled", 2))

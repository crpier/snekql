"""Insert query construction, compilation, and execution tests."""

from __future__ import annotations

from pathlib import Path
from sqlite3 import connect
from tempfile import TemporaryDirectory

from snektest import assert_eq, assert_in, assert_is_none, assert_raises, test

from snekql import (
    MISSING,
    Database,
    ExecutionError,
    Fetched,
    Integer,
    Model,
    Pending,
    Text,
    insert,
)
from snekql.query import compile_write_sql
from tests.helpers import NULL_LOGGER


def _fetch_rows(database_path: Path, sql: str) -> list[tuple[object, ...]]:
    connection = connect(database_path)
    try:
        cursor = connection.execute(sql)
        return [tuple(row) for row in cursor.fetchall()]
    finally:
        connection.close()


@test(mark="fast")
def insert_compilation_omits_missing_and_quotes_identifiers() -> None:
    """Compiled insert SQL targets the model table and omits MISSING fields."""

    class Order[S = Pending](Model[S, "Order[Fetched]"]):
        """Table model with identifiers that must be quoted."""

        __tablename__ = "select"
        id: Order.GenCol[int] = Integer(primary_key=True, default=MISSING)
        where: Order.Col[str] = Text(nullable=False)

    sql, params = compile_write_sql(insert(Order(where="x")))

    assert_eq(sql, 'INSERT INTO "select" ("where") VALUES (?)')
    assert_eq(params, ("x",))


@test(mark="fast")
def insert_compilation_uses_default_values_when_every_field_is_missing() -> None:
    """An all-generated model compiles to SQLite DEFAULT VALUES."""

    class AuditLog[S = Pending](Model[S, "AuditLog[Fetched]"]):
        """Table model with no explicit insertable values."""

        id: AuditLog.GenCol[int] = Integer(primary_key=True, default=MISSING)

    sql, params = compile_write_sql(insert(AuditLog()))

    assert_eq(sql, 'INSERT INTO "audit_log" DEFAULT VALUES')
    assert_eq(params, ())


@test(mark="medium")
async def insert_execution_includes_defaults_and_returns_none() -> None:
    """Executing an insert persists Python defaults and default-factory values."""

    class User[S = Pending](Model[S, "User[Fetched]"]):
        """Table model with explicit, default, and generated fields."""

        id: User.GenCol[int] = Integer(primary_key=True, default=MISSING)
        email: User.Col[str] = Text(nullable=False)
        label: User.Col[str] = Text(nullable=False, default_factory=lambda: "fresh")
        status: User.Col[str] = Text(nullable=False, default="active")

    with TemporaryDirectory() as directory:
        database_path = Path(directory) / "app.db"
        database = await Database.initialize(
            logger=NULL_LOGGER, database=database_path, models=[User]
        )
        try:
            async with database.transaction() as transaction:
                result = await transaction.execute(insert(User(email="a@example.com")))
        finally:
            await database.close()

        rows = _fetch_rows(
            database_path,
            'SELECT "email", "label", "status" FROM "user"',
        )

    assert_is_none(result)
    assert_eq(rows, [("a@example.com", "fresh", "active")])


@test(mark="medium")
async def execution_errors_preserve_insert_sql_and_params() -> None:
    """SQLite insert failures are wrapped with SQL and parameter context."""

    class User[S = Pending](Model[S, "User[Fetched]"]):
        """Table model used to trigger a duplicate primary key failure."""

        id: User.GenCol[int] = Integer(primary_key=True, default=MISSING)
        email: User.Col[str] = Text(nullable=False)

    with TemporaryDirectory() as directory:
        database_path = Path(directory) / "app.db"
        database = await Database.initialize(
            logger=NULL_LOGGER, database=database_path, models=[User]
        )
        try:
            async with database.transaction() as transaction:
                await transaction.execute(insert(User(id=1, email="first@example.com")))
                with assert_raises(ExecutionError) as caught_error:
                    await transaction.execute(
                        insert(User(id=1, email="second@example.com")),
                    )
        finally:
            await database.close()

    error = caught_error.exception
    assert_in('INSERT INTO "user"', error.sql)
    assert_in("?", error.sql)
    assert_eq(error.params, (1, "second@example.com"))

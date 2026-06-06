"""Pyright-oriented public API prototypes."""

from __future__ import annotations

from contextlib import AbstractAsyncContextManager
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Literal, assert_type

from snekql import (
    MISSING,
    CurrentTimestamp,
    DateTime,
    Fetched,
    Index,
    InsertQuery,
    Integer,
    Missing,
    Model,
    Pending,
    Predicate,
    SelectModelQuery,
    SelectTupleQuery,
    SelectValueQuery,
    Text,
    Transaction,
    UpdateQuery,
    insert,
    mariadb,
    select,
    sqlite,
    update,
)
from snekql.testing import mariadb as testing_mariadb


class User[S = Pending](Model[S, "User[Fetched]"]):
    """Canonical table model used by public API typing examples."""

    id: User.GenCol[int] = Integer(
        primary_key=True,
        auto_increment=True,
        default=MISSING,
    )
    email: User.Col[str] = Text(nullable=False)
    status: User.Col[str] = Text(nullable=False, default="active")
    created_at: User.GenCol[datetime] = DateTime(
        server_default=CurrentTimestamp(),
        default=MISSING,
    )


class SqliteUser[S = Pending](sqlite.Model[S, "SqliteUser[Fetched]"]):
    """SQLite namespace table model used by public API typing examples."""

    id: SqliteUser.GenCol[int] = sqlite.Integer(
        primary_key=True,
        auto_increment=True,
        default=MISSING,
    )
    email: SqliteUser.Col[str] = sqlite.Text(nullable=False)


class MariadbUser[S = Pending](mariadb.Model[S, "MariadbUser[Fetched]"]):
    """MariaDB namespace table model used by public API typing examples."""

    id: MariadbUser.GenCol[int] = mariadb.Integer(
        primary_key=True,
        auto_increment=True,
        default=MISSING,
    )
    email: MariadbUser.Col[str] = mariadb.Text(nullable=False)


if TYPE_CHECKING:
    sqlite_config = sqlite.Config(database=Path("app.db"))
    _ = assert_type(sqlite_config, sqlite.Config)
    sqlite_index = sqlite.Index(SqliteUser.email)
    _ = assert_type(sqlite_index, Index[SqliteUser[Pending]])
    sqlite_user = SqliteUser(email="alice@example.com")
    _ = assert_type(sqlite_user, SqliteUser[Pending])
    _ = assert_type(
        select(SqliteUser), SelectModelQuery[SqliteUser[Pending], SqliteUser[Fetched]]
    )

    _ = assert_type(mariadb.Model.__snekql_backend__, Literal["mariadb"])
    _ = assert_type(sqlite.Model.__snekql_backend__, Literal["sqlite"])

    mariadb_config = mariadb.Config(database="app", user="snekql")
    _ = assert_type(mariadb_config, mariadb.Config)
    test_server_context = testing_mariadb.temporary_mariadb_server(
        reset_database=True,
    )
    _ = assert_type(
        test_server_context,
        AbstractAsyncContextManager[testing_mariadb.TemporaryMariaDBServer],
    )
    test_server = testing_mariadb.TemporaryMariaDBServer(
        auth="insecure",
        database="test",
        data_directory=Path("data"),
        error_log_path=Path("mariadb.err"),
        host=None,
        password="",
        pid_path=Path("mariadb.pid"),
        port=None,
        socket_path=Path("mariadb.sock"),
        transports=frozenset({"unix_socket"}),
        user="root",
    )
    _ = assert_type(test_server.config(), mariadb.Config)

    async def check_test_server_sql_helper() -> None:
        """The public SQL helper is async and returns command output."""

        command_result = await test_server.run_sql("SELECT 1", check=False)
        _ = assert_type(command_result, testing_mariadb.MariaDBCommandResult)
        _ = assert_type(await test_server.reset_database(), None)

    mariadb_index = mariadb.Index(MariadbUser.email)
    _ = assert_type(mariadb_index, Index[MariadbUser[Pending]])
    mariadb_user = MariadbUser(email="alice@example.com")
    _ = assert_type(mariadb_user, MariadbUser[Pending])
    _ = assert_type(
        select(MariadbUser),
        SelectModelQuery[MariadbUser[Pending], MariadbUser[Fetched]],
    )

    pending_user = User(email="alice@example.com")
    _ = assert_type(pending_user, User[Pending])
    _ = assert_type(pending_user.id, int | Missing)
    _ = assert_type(pending_user.email, str)
    _ = assert_type(pending_user.created_at, datetime | Missing)

    def check_fetched_user(fetched_user: User[Fetched]) -> None:
        """Fetched-state generated values are narrowed by descriptor overloads."""

        _ = assert_type(fetched_user.id, int)
        _ = assert_type(fetched_user.email, str)
        _ = assert_type(fetched_user.created_at, datetime)

    _ = assert_type(select(User), SelectModelQuery[User[Pending], User[Fetched]])
    _ = assert_type(
        select(User.email).where(User.email.eq("alice@example.com")).all(),
        SelectValueQuery[User[Pending], str],
    )
    _ = assert_type(
        select(User.email, User.status),
        SelectTupleQuery[User[Pending], str, str],
    )
    _ = assert_type(User.email.eq("alice@example.com"), Predicate[User[Pending]])
    _ = assert_type(User.email.ne("alice@example.com"), Predicate[User[Pending]])
    _ = assert_type(User.email.is_null(), Predicate[User[Pending]])
    _ = assert_type(User.email.is_not_null(), Predicate[User[Pending]])
    _ = assert_type(User.email.in_("a@example.com"), Predicate[User[Pending]])
    _ = assert_type(
        User.email.not_in("a@example.com", "b@example.com"),
        Predicate[User[Pending]],
    )
    _ = assert_type(User.email.like("%@example.com"), Predicate[User[Pending]])
    _ = assert_type(User.email.not_like("%@example.com"), Predicate[User[Pending]])
    _ = assert_type(
        User.email.eq("alice@example.com") & User.status.eq("active"),
        Predicate[User[Pending]],
    )
    _ = assert_type(Index(User.email), Index[User[Pending]])
    _ = assert_type(Index(User.email, unique=True), Index[User[Pending]])
    _ = assert_type(insert(pending_user), InsertQuery[User[Pending]])
    _ = assert_type(
        update(User).set(User.email.to("new@example.com")),
        UpdateQuery[User[Pending]],
    )

    async def check_fetch_types(transaction: Transaction) -> None:
        """Runtime fetch overloads preserve selected result shapes."""

        _ = assert_type(
            await transaction.fetch_all(select(User).all()),
            list[User[Fetched]],
        )
        _ = assert_type(
            await transaction.fetch_all(select(User.email).all()),
            list[str],
        )
        _ = assert_type(
            await transaction.fetch_all(select(User.email, User.status).all()),
            list[tuple[str, str]],
        )
        _ = assert_type(
            await transaction.fetch_one(select(User.email).all()),
            str | None,
        )

"""Pyright-oriented public API prototypes."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, assert_type

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
    select,
    sqlite,
    update,
)


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

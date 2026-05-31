"""Pyright-oriented examples for snekql's public typing surface."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, assert_type

from snekql import (
    MISSING,
    CurrentTimestamp,
    DateTime,
    Fetched,
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
    update,
)


class Account[S = Pending](Model[S, "Account[Fetched]"]):
    """Example model focused on static result-shape inference."""

    id: Account.GenCol[int] = Integer(
        primary_key=True,
        auto_increment=True,
        default=MISSING,
    )
    email: Account.Col[str] = Text(nullable=False)
    status: Account.Col[str] = Text(nullable=False, default="active")
    created_at: Account.GenCol[datetime] = DateTime(
        server_default=CurrentTimestamp(),
        default=MISSING,
    )


if TYPE_CHECKING:
    pending_account = Account(email="alice@example.com")
    _ = assert_type(pending_account, Account[Pending])
    _ = assert_type(pending_account.id, int | Missing)
    _ = assert_type(pending_account.created_at, datetime | Missing)

    def check_fetched_account(fetched_account: Account[Fetched]) -> None:
        """Fetched generated columns are narrowed to concrete values."""

        _ = assert_type(fetched_account.id, int)
        _ = assert_type(fetched_account.created_at, datetime)

    _ = assert_type(
        select(Account),
        SelectModelQuery[Account[Pending], Account[Fetched]],
    )
    _ = assert_type(select(Account.email), SelectValueQuery[Account[Pending], str])
    _ = assert_type(
        select(Account.email, Account.status),
        SelectTupleQuery[Account[Pending], str, str],
    )
    _ = assert_type(Account.email.eq("alice@example.com"), Predicate[Account[Pending]])
    _ = assert_type(insert(pending_account), InsertQuery[Account[Pending]])
    _ = assert_type(
        update(Account).set(Account.status.to("disabled")),
        UpdateQuery[Account[Pending]],
    )

    async def check_runtime_shapes(transaction: Transaction) -> None:
        """Runtime overloads preserve selected result shapes."""

        _ = assert_type(
            await transaction.fetch_all(select(Account).all()),
            list[Account[Fetched]],
        )
        _ = assert_type(
            await transaction.fetch_all(select(Account.email).all()),
            list[str],
        )
        _ = assert_type(
            await transaction.fetch_all(select(Account.email, Account.status).all()),
            list[tuple[str, str]],
        )
        _ = assert_type(
            await transaction.fetch_one(select(Account.email).all()),
            str | None,
        )

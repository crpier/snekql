"""ty-oriented examples for snekql's public typing surface."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, assert_type

from snekql import sqlite
from snekql.sqlite import (
    Fetched,
    Pending,
    PendingGeneration,
    Predicate,
    Select,
    Transaction,
    Write,
    insert,
    select,
    update,
)


class Account[S = Pending](sqlite.Model[S, "Account[Fetched]"]):
    """Example model focused on static result-shape inference."""

    id: sqlite.GenCol[int] = sqlite.Integer(
        primary_key=True,
        auto_increment=True,
        default=sqlite.PENDING_GENERATION,
    )
    email: sqlite.Col[str] = sqlite.Text()
    status: sqlite.Col[str] = sqlite.Text(default="active")
    created_at: sqlite.GenCol[datetime] = sqlite.Text(
        default=sqlite.CurrentTimestamp,
    )

    def insert_payload(self: Account[Pending]) -> dict[str, str]:
        """Pending-state helper for writes."""

        return {"email": self.email, "status": self.status}

    def cache_key(self: Account[Fetched]) -> str:
        """Fetched-state helper that can rely on generated ids."""

        return f"account:{self.id}"


if TYPE_CHECKING:
    pending_account = Account(email="alice@example.com")
    _ = assert_type(pending_account, Account[Pending])
    _ = assert_type(pending_account.id, int | PendingGeneration)
    _ = assert_type(pending_account.created_at, datetime | PendingGeneration)
    _ = assert_type(pending_account.insert_payload(), dict[str, str])

    def check_fetched_account(fetched_account: Account[Fetched]) -> None:
        """Fetched generated columns are narrowed to concrete values."""

        _ = assert_type(fetched_account.id, int)
        _ = assert_type(fetched_account.created_at, datetime)
        _ = assert_type(fetched_account.cache_key(), str)

    model_query: Select[Account[Fetched]] = select(Account).all()
    value_query: Select[str] = select(Account.email).all()
    tuple_query: Select[tuple[str, str]] = select(Account.email, Account.status).all()
    _ = assert_type(Account.email.eq("alice@example.com"), Predicate[Account[Pending]])
    insert_query: Write[None] = insert(pending_account)
    update_query: Write[int] = update(Account).set(Account.status.to("disabled")).all()

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
        # fetch_one is exactly-one (raises on zero or many rows), so the value
        # is never absent: a single-value result keeps the column read type.
        _ = assert_type(
            await transaction.fetch_one(select(Account.email).all()),
            str,
        )
        # fetch_one_or_none is zero-or-one for model/tuple/join selects, where a
        # None result can only mean a missing row.
        _ = assert_type(
            await transaction.fetch_one_or_none(select(Account).all()),
            Account[Fetched] | None,
        )

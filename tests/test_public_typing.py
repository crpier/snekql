"""Pyright-oriented public API prototypes."""

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
    SelectModelQuery,
    SelectValueQuery,
    Text,
    UpdateQuery,
    insert,
    select,
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


if TYPE_CHECKING:
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
    _ = assert_type(insert(pending_user), InsertQuery[User[Pending]])
    _ = assert_type(
        update(User).set(User.email.to("new@example.com")),
        UpdateQuery[User[Pending]],
    )

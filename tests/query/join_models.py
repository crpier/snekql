"""SQLite join declarations shared by compilation, scope, and alias checks.

These are one related pair of Table Models, not a canonical schema for all tests.
Other groups may deliberately declare different models with the same SQL names;
keep those identities separate. This module owns no fixtures or database state.
"""

from __future__ import annotations

from typing import ClassVar

from snekql import sqlite
from snekql.sqlite import PENDING_GENERATION, Pending, Row


class User[S = Pending](sqlite.Model[S]):
    """Referenced table."""

    __row_type__: ClassVar[sqlite.ReadType[User[Row]]]

    id: User.GenCol[int] = sqlite.Integer(
        primary_key=True,
        auto_increment=True,
        default=PENDING_GENERATION,
    )
    email: User.Col[str] = sqlite.Text(nullable=False)


class Order[S = Pending](sqlite.Model[S]):
    """Table with a foreign key to ``User``."""

    __row_type__: ClassVar[sqlite.ReadType[Order[Row]]]

    id: Order.GenCol[int] = sqlite.Integer(
        primary_key=True,
        auto_increment=True,
        default=PENDING_GENERATION,
    )
    user_id: Order.FKCol[User, int] = sqlite.ForeignKey(User.id)
    note: Order.Col[str] = sqlite.Text(nullable=False)

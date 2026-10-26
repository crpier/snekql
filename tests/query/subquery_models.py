"""Shared subquery declaration inputs; no runtime or fixture state."""

from __future__ import annotations

from typing import ClassVar

from snekql import mariadb, sqlite
from snekql.sqlite import PENDING_GENERATION, Pending, Row


class User[S = Pending](sqlite.Model[S]):
    """Outer table for subquery tests."""

    __row_type__: ClassVar[sqlite.ReadType[User[Row]]]

    id: User.GenCol[int] = sqlite.Integer(
        primary_key=True,
        auto_increment=True,
        default=PENDING_GENERATION,
    )
    country: User.Col[str] = sqlite.Text(nullable=False)


class Order[S = Pending](sqlite.Model[S]):
    """Inner table with a foreign key back to ``User``."""

    __row_type__: ClassVar[sqlite.ReadType[Order[Row]]]

    id: Order.GenCol[int] = sqlite.Integer(
        primary_key=True,
        auto_increment=True,
        default=PENDING_GENERATION,
    )
    user_id: Order.FKCol[User, int] = sqlite.ForeignKey(User.id)
    amount: Order.Col[int] = sqlite.Integer(nullable=False)


class MariaUser[S = mariadb.Pending](mariadb.Model[S]):
    """MariaDB outer source for public subquery compilation, not execution."""

    __tablename__ = "user"
    __row_type__: ClassVar[mariadb.ReadType[MariaUser[mariadb.Row]]]

    id: MariaUser.Col[int] = mariadb.Integer(primary_key=True)
    country: MariaUser.Col[str] = mariadb.Text(nullable=False)


class MariaOrder[S = mariadb.Pending](mariadb.Model[S]):
    """MariaDB inner source with its own backend-correct foreign key."""

    __tablename__ = "order"
    __row_type__: ClassVar[mariadb.ReadType[MariaOrder[mariadb.Row]]]

    user_id: MariaOrder.FKCol[MariaUser, int] = mariadb.ForeignKey(MariaUser.id)
    amount: MariaOrder.Col[int] = mariadb.Integer(nullable=False)

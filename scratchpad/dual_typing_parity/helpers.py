"""Application helpers that expose the difference without erasing value types."""

from typing import Any, Literal, Protocol

from snekql import sqlite
from snekql.query import InsertableModel

from scratchpad.dual_typing_parity import current, dual


class Contact(Protocol):
    @property
    def email(self) -> str: ...

    @property
    def nickname(self) -> str | None: ...


def dual_label(user: dual.User) -> str:
    return user.nickname or user.email


def current_label(
    user: current.User[sqlite.Pending] | current.User[sqlite.Fetched],
) -> str:
    return user.nickname or user.email


def structural_label(user: Contact) -> str:
    return user.nickname or user.email


def native_insert[Owner: sqlite.Model[Any, Any], Result: sqlite.Model[Any, Any]](
    user: InsertableModel[Literal["sqlite"], Owner, Result],
) -> sqlite.Write[Result]:
    return sqlite.insert(user).returning()


async def read[Result](
    transaction: sqlite.Transaction, query: sqlite.Select[Result]
) -> list[Result]:
    return await transaction.fetch_all(query)

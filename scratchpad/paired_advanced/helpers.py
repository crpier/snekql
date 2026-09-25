"""Value and insertion helpers, giving each declaration its best checked spelling."""

from typing import Any, Literal, Protocol

from snekql import sqlite
from snekql.query import InsertableModel

from scratchpad.dual_pairing.sqlite import Paired
from scratchpad.dual_typing_parity.bridge import Row, insert
from scratchpad.paired_advanced import body, dual


class Contact(Protocol):
    @property
    def email(self) -> str: ...

    @property
    def nickname(self) -> str | None: ...


def contact_label(user: Contact) -> str:
    return user.nickname or user.email


def body_checked[Account: body.User[sqlite.Pending] | body.User[sqlite.Fetched]](
    user: Account,
) -> Account:
    if not contact_label(user):
        raise sqlite.ModelValidationError("An account needs a label")
    return user


def dual_checked[Account: dual.User](user: Account) -> Account:
    if not contact_label(user):
        raise sqlite.ModelValidationError("An account needs a label")
    return user


def body_insert[Owner: sqlite.Model[Any, Any], Result: sqlite.Model[Any, Any]](
    pending: InsertableModel[Literal["sqlite"], Owner, Result],
) -> sqlite.Write[Result]:
    return sqlite.insert(pending).returning()


def dual_insert[Result: Row](pending: Paired[Result]) -> sqlite.Write[Result]:
    return insert(pending).returning()

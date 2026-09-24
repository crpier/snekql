"""Callable physical references preserve the target and value contract."""

from typing import TYPE_CHECKING, assert_type

from snekql import mariadb, sqlite


class Other[S = sqlite.Pending](sqlite.Model[S, "Other[sqlite.Fetched]"]):
    account_id: sqlite.Col[int] = sqlite.Integer(primary_key=True)
    label: sqlite.Col[str] = sqlite.Text(unique=True)


class Account[S = sqlite.Pending](sqlite.Model[S, "Account[sqlite.Fetched]"]):
    account_id: sqlite.GenCol[int] = sqlite.Integer(
        primary_key=True, auto_increment=True, default=sqlite.PENDING_GENERATION
    )
    manager_id: sqlite.FKCol[Account, int | None] = sqlite.ForeignKey(
        lambda: Account.account_id, default=None
    )
    defaulted: sqlite.FKCol[Other, int] = sqlite.ForeignKey(
        lambda: Other.account_id, default=1
    )
    nullable_defaulted: sqlite.FKCol[Other, int | None] = sqlite.ForeignKey(
        lambda: Other.account_id, default=1, nullable=True
    )


assert_type(Account().manager_id, int | None)
assert_type(Account().defaulted, int)
Account.manager_id.references(Account.account_id)
Account.defaulted.references(Other.account_id)


def fetched_values(account: Account[sqlite.Fetched]) -> None:
    """Generated reads and defaulted relation values retain their types."""
    assert_type(account.account_id, int)
    assert_type(account.manager_id, int | None)
    assert_type(account.defaulted, int)


if TYPE_CHECKING:

    class WrongTarget[S = sqlite.Pending](
        sqlite.Model[S, "WrongTarget[sqlite.Fetched]"]
    ):
        manager_id: sqlite.FKCol[Account, int | None] = sqlite.ForeignKey(
            lambda: Other.account_id, default=None
        )  # ty: ignore[invalid-assignment]

    class WrongValue[S = sqlite.Pending](sqlite.Model[S, "WrongValue[sqlite.Fetched]"]):
        manager_id: sqlite.FKCol[Other, int | None] = sqlite.ForeignKey(
            lambda: Other.label, default=None
        )  # ty: ignore[invalid-assignment]

    class Required[S = sqlite.Pending](sqlite.Model[S, "Required[sqlite.Fetched]"]):
        manager_id: sqlite.FKCol[Account, int] = sqlite.ForeignKey(
            lambda: Account.account_id  # ty: ignore[invalid-argument-type]
        )

    class NullableRequired[S = sqlite.Pending](
        sqlite.Model[S, "NullableRequired[sqlite.Fetched]"]
    ):
        manager_id: sqlite.FKCol[Account, int | None] = sqlite.ForeignKey(
            lambda: Account.account_id, nullable=True
        )  # ty: ignore[no-matching-overload]

    class WrongDefault[S = sqlite.Pending](
        sqlite.Model[S, "WrongDefault[sqlite.Fetched]"]
    ):
        manager_id: sqlite.FKCol[Account, int] = sqlite.ForeignKey(
            lambda: Account.account_id, default="bad"
        )  # ty: ignore[no-matching-overload]

    Account(manager_id="bad")  # ty: ignore[invalid-argument-type]
    Account.manager_id.references(Other.account_id)  # ty: ignore[no-matching-overload]


if TYPE_CHECKING:

    class OtherBackend[S = mariadb.Pending](
        mariadb.Model[S, "OtherBackend[mariadb.Fetched]"]
    ):
        account_id: mariadb.Col[int] = mariadb.Integer(primary_key=True)

    class WrongBackend[S = sqlite.Pending](
        sqlite.Model[S, "WrongBackend[sqlite.Fetched]"]
    ):
        manager_id: sqlite.FKCol[Account, int | None] = sqlite.ForeignKey(  # ty: ignore[invalid-assignment]
            lambda: OtherBackend.account_id,
            default=None,
        )

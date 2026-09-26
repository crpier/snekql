"""Callable physical references preserve the target and value contract."""

from typing import TYPE_CHECKING, ClassVar, assert_type

from snekql import mariadb, sqlite


class Other[S = mariadb.Pending](mariadb.Model[S]):
    __row_type__: ClassVar[mariadb.ReadType[Other[mariadb.Row]]]
    account_id: mariadb.Col[int] = mariadb.Integer(primary_key=True)
    label: mariadb.Col[str] = mariadb.Text(unique=True)


class Account[S = mariadb.Pending](mariadb.Model[S]):
    __row_type__: ClassVar[mariadb.ReadType[Account[mariadb.Row]]]
    account_id: mariadb.GenCol[int] = mariadb.Integer(
        primary_key=True, auto_increment=True, default=mariadb.PENDING_GENERATION
    )
    manager_id: mariadb.FKCol[Account, int | None] = mariadb.ForeignKey(
        lambda: Account.account_id, default=None
    )
    defaulted: mariadb.FKCol[Other, int] = mariadb.ForeignKey(
        lambda: Other.account_id, default=1
    )
    nullable_defaulted: mariadb.FKCol[Other, int | None] = mariadb.ForeignKey(
        lambda: Other.account_id, default=1, nullable=True
    )


assert_type(Account().manager_id, int | None)
assert_type(Account().defaulted, int)
Account.manager_id.references(Account.account_id)
Account.defaulted.references(Other.account_id)


def fetched_values(account: Account[mariadb.Row]) -> None:
    """Generated reads and defaulted relation values retain their types."""
    assert_type(account.account_id, int)
    assert_type(account.manager_id, int | None)
    assert_type(account.defaulted, int)


if TYPE_CHECKING:

    class WrongTarget[S = mariadb.Pending](mariadb.Model[S]):
        __row_type__: ClassVar[mariadb.ReadType[WrongTarget[mariadb.Row]]]
        manager_id: mariadb.FKCol[Account, int | None] = mariadb.ForeignKey(
            lambda: Other.account_id, default=None
        )  # ty: ignore[invalid-assignment]

    class WrongValue[S = mariadb.Pending](mariadb.Model[S]):
        __row_type__: ClassVar[mariadb.ReadType[WrongValue[mariadb.Row]]]
        manager_id: mariadb.FKCol[Other, int | None] = mariadb.ForeignKey(
            lambda: Other.label, default=None
        )  # ty: ignore[invalid-assignment]

    class Required[S = mariadb.Pending](mariadb.Model[S]):
        __row_type__: ClassVar[mariadb.ReadType[Required[mariadb.Row]]]
        manager_id: mariadb.FKCol[Account, int] = mariadb.ForeignKey(
            lambda: Account.account_id  # ty: ignore[invalid-argument-type]
        )

    class NullableRequired[S = mariadb.Pending](mariadb.Model[S]):
        __row_type__: ClassVar[mariadb.ReadType[NullableRequired[mariadb.Row]]]
        manager_id: mariadb.FKCol[Account, int | None] = mariadb.ForeignKey(
            lambda: Account.account_id, nullable=True
        )  # ty: ignore[no-matching-overload]

    class WrongDefault[S = mariadb.Pending](mariadb.Model[S]):
        __row_type__: ClassVar[mariadb.ReadType[WrongDefault[mariadb.Row]]]
        manager_id: mariadb.FKCol[Account, int] = mariadb.ForeignKey(
            lambda: Account.account_id, default="bad"
        )  # ty: ignore[no-matching-overload]

    Account(manager_id="bad")  # ty: ignore[invalid-argument-type]
    Account.manager_id.references(Other.account_id)  # ty: ignore[no-matching-overload]


if TYPE_CHECKING:

    class OtherBackend[S = sqlite.Pending](sqlite.Model[S]):
        __row_type__: ClassVar[sqlite.ReadType[OtherBackend[sqlite.Row]]]
        account_id: sqlite.Col[int] = sqlite.Integer(primary_key=True)

    class WrongBackend[S = mariadb.Pending](mariadb.Model[S]):
        __row_type__: ClassVar[mariadb.ReadType[WrongBackend[mariadb.Row]]]
        manager_id: mariadb.FKCol[Account, int | None] = mariadb.ForeignKey(  # ty: ignore[invalid-assignment]
            lambda: OtherBackend.account_id,
            default=None,
        )

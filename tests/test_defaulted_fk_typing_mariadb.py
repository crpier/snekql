"""Defaulted typed foreign keys retain target and constructor contracts."""

from typing import TYPE_CHECKING, ClassVar, assert_type

from snekql import mariadb


class Account[S = mariadb.Pending](mariadb.Model[S, "Account[mariadb.Fetched]"]):
    account_id: mariadb.GenCol[int] = mariadb.Integer(
        primary_key=True, auto_increment=True, default=mariadb.PENDING_GENERATION
    )
    name: mariadb.Col[str] = mariadb.Text(default="")
    manager_id: mariadb.FKCol[Account, int | None] = mariadb.Integer(default=None)
    __foreign_keys__: ClassVar = [
        mariadb.ForeignKeyConstraint(manager_id, references=(account_id,))
    ]


if TYPE_CHECKING:
    assert_type(Account().manager_id, int | None)
    Account.manager_id.references(Account.account_id)


class Other[S = mariadb.Pending](mariadb.Model[S, "Other[mariadb.Fetched]"]):
    account_id: mariadb.Col[int] = mariadb.Integer(primary_key=True)


class Defaults[S = mariadb.Pending](mariadb.Model[S, "Defaults[mariadb.Fetched]"]):
    account_id: mariadb.Col[int] = mariadb.Integer(primary_key=True, default=1)
    literal: mariadb.FKCol[Account, int] = mariadb.Integer(default=1)
    factory: mariadb.FKCol[Account, int] = mariadb.Integer(default_factory=lambda: 1)
    null_factory: mariadb.FKCol[Account, int | None] = mariadb.Integer(
        default_factory=lambda: None
    )


class Required[S = mariadb.Pending](mariadb.Model[S, "Required[mariadb.Fetched]"]):
    account_id: mariadb.Col[int] = mariadb.Integer(primary_key=True)
    reference: mariadb.FKCol[Account, int | None] = mariadb.Integer()


if TYPE_CHECKING:
    assert_type(Defaults().literal, int)
    assert_type(Defaults().factory, int)
    assert_type(Defaults().null_factory, int | None)
    Required(account_id=1)  # ty: ignore[missing-argument]
    Required(account_id=1, reference=None)
    Account(manager_id="wrong")  # ty: ignore[invalid-argument-type]
    Defaults(literal=None)  # ty: ignore[invalid-argument-type]
    Account.manager_id.references(Other.account_id)  # ty: ignore[no-matching-overload]
    Account.account_id.references(Account.account_id)  # ty: ignore[unresolved-attribute]

    class WrongDefault[S = mariadb.Pending](
        mariadb.Model[S, "WrongDefault[mariadb.Fetched]"]
    ):
        account_id: mariadb.Col[int] = mariadb.Integer(primary_key=True)
        reference: mariadb.FKCol[Account, int] = mariadb.Integer(default="wrong")  # ty: ignore[invalid-assignment]

    def fetched(row: Defaults[mariadb.Fetched]) -> None:
        assert_type(row.literal, int)
        assert_type(row.null_factory, int | None)


if TYPE_CHECKING:
    Account.manager_id.references(Account.name)  # ty: ignore[no-matching-overload]

    class WrongFactory[S = mariadb.Pending](
        mariadb.Model[S, "WrongFactory[mariadb.Fetched]"]
    ):
        reference: mariadb.FKCol[Account, int] = mariadb.Integer(
            default_factory=lambda: "wrong"
        )  # ty: ignore[invalid-assignment]

    class NonNullableDefault[S = mariadb.Pending](
        mariadb.Model[S, "NonNullableDefault[mariadb.Fetched]"]
    ):
        reference: mariadb.FKCol[Account, int] = mariadb.Integer(default=None)  # ty: ignore[invalid-assignment]

    class DirectSelf[S = mariadb.Pending](
        mariadb.Model[S, "DirectSelf[mariadb.Fetched]"]
    ):
        account_id: mariadb.GenCol[int] = mariadb.Integer(
            primary_key=True, auto_increment=True, default=mariadb.PENDING_GENERATION
        )
        manager_id: mariadb.FKCol[DirectSelf, int | None] = mariadb.ForeignKey(
            account_id, default=None
        )  # ty: ignore[no-matching-overload]

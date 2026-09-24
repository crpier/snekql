"""Defaulted typed foreign keys retain target and constructor contracts."""

from typing import TYPE_CHECKING, ClassVar, assert_type

from snekql import sqlite


class Account[S = sqlite.Pending](sqlite.Model[S, "Account[sqlite.Fetched]"]):
    account_id: sqlite.GenCol[int] = sqlite.Integer(
        primary_key=True, auto_increment=True, default=sqlite.PENDING_GENERATION
    )
    name: sqlite.Col[str] = sqlite.Text(default="")
    manager_id: sqlite.FKCol[Account, int | None] = sqlite.Integer(default=None)
    __foreign_keys__: ClassVar = [
        sqlite.ForeignKeyConstraint(manager_id, references=(account_id,))
    ]


if TYPE_CHECKING:
    assert_type(Account().manager_id, int | None)
    Account.manager_id.references(Account.account_id)


class Other[S = sqlite.Pending](sqlite.Model[S, "Other[sqlite.Fetched]"]):
    account_id: sqlite.Col[int] = sqlite.Integer(primary_key=True)


class Defaults[S = sqlite.Pending](sqlite.Model[S, "Defaults[sqlite.Fetched]"]):
    account_id: sqlite.Col[int] = sqlite.Integer(primary_key=True, default=1)
    literal: sqlite.FKCol[Account, int] = sqlite.Integer(default=1)
    factory: sqlite.FKCol[Account, int] = sqlite.Integer(default_factory=lambda: 1)
    null_factory: sqlite.FKCol[Account, int | None] = sqlite.Integer(
        default_factory=lambda: None
    )


class Required[S = sqlite.Pending](sqlite.Model[S, "Required[sqlite.Fetched]"]):
    account_id: sqlite.Col[int] = sqlite.Integer(primary_key=True)
    reference: sqlite.FKCol[Account, int | None] = sqlite.Integer()


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

    class WrongDefault[S = sqlite.Pending](
        sqlite.Model[S, "WrongDefault[sqlite.Fetched]"]
    ):
        account_id: sqlite.Col[int] = sqlite.Integer(primary_key=True)
        reference: sqlite.FKCol[Account, int] = sqlite.Integer(default="wrong")  # ty: ignore[invalid-assignment]

    def fetched(row: Defaults[sqlite.Fetched]) -> None:
        assert_type(row.literal, int)
        assert_type(row.null_factory, int | None)


if TYPE_CHECKING:
    Account.manager_id.references(Account.name)  # ty: ignore[no-matching-overload]

    class WrongFactory[S = sqlite.Pending](
        sqlite.Model[S, "WrongFactory[sqlite.Fetched]"]
    ):
        reference: sqlite.FKCol[Account, int] = sqlite.Integer(
            default_factory=lambda: "wrong"
        )  # ty: ignore[invalid-assignment]

    class NonNullableDefault[S = sqlite.Pending](
        sqlite.Model[S, "NonNullableDefault[sqlite.Fetched]"]
    ):
        reference: sqlite.FKCol[Account, int] = sqlite.Integer(default=None)  # ty: ignore[invalid-assignment]

    class DirectSelf[S = sqlite.Pending](sqlite.Model[S, "DirectSelf[sqlite.Fetched]"]):
        account_id: sqlite.GenCol[int] = sqlite.Integer(
            primary_key=True, auto_increment=True, default=sqlite.PENDING_GENERATION
        )
        manager_id: sqlite.FKCol[DirectSelf, int | None] = sqlite.ForeignKey(
            account_id, default=None
        )  # ty: ignore[no-matching-overload]

"""Derived native storage remains subject to declaration validation."""

from typing import ClassVar

from snektest import assert_eq, assert_raises, test

from snekql import mariadb


@test(mark="fast")
async def text_reference_retains_capacity_and_collation() -> None:
    """The resolved FK copies the exact storage contract of its target."""

    class Account[S = mariadb.Pending](mariadb.Model[S, "Account[mariadb.Fetched]"]):
        account_id: mariadb.Col[str] = mariadb.Text(
            length=32, collation="utf8mb4_bin", primary_key=True
        )
        manager_id: mariadb.FKCol[Account, str | None] = mariadb.ForeignKey(
            lambda: Account.account_id, default=None
        )

    assert_eq(Account.manager_id.text_length, 32)
    assert_eq(Account.manager_id.text_collation, "utf8mb4_bin")


@test(mark="fast")
async def deferred_prefix_index_checks_real_capacity() -> None:
    """Class-body prefix declarations are checked against resolved text dimensions."""

    class Account[S = mariadb.Pending](mariadb.Model[S, "Account[mariadb.Fetched]"]):
        account_id: mariadb.Col[str] = mariadb.Text(length=32, primary_key=True)
        manager_id: mariadb.FKCol[Account, str | None] = mariadb.ForeignKey(
            lambda: Account.account_id, default=None
        )
        __indexes__: ClassVar = [mariadb.Index(manager_id, prefix_lengths=(33,))]

    with assert_raises(mariadb.ModelDeclarationError):
        mariadb.scaffold([Account])


@test(mark="fast")
async def non_keyable_storage_is_rejected_when_resolved() -> None:
    """A callback cannot turn native long text into a scalar reference key."""

    class Account[S = mariadb.Pending](mariadb.Model[S, "Account[mariadb.Fetched]"]):
        account_id: mariadb.Col[str] = mariadb.LongText()
        manager_id: mariadb.FKCol[Account, str | None] = mariadb.ForeignKey(
            lambda: Account.account_id, default=None
        )

    with assert_raises(mariadb.ModelDeclarationError):
        mariadb.scaffold([Account])

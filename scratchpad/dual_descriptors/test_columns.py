"""Direct class attributes are native-query expressions; instances remain values."""

from typing import ClassVar, assert_type

from snekql import sqlite as native
from snektest import assert_eq, test

from scratchpad.dual_descriptors import sqlite


@test(mark="fast")
def inline_scalar_projection_compiles() -> None:
    class User(sqlite.Model):
        __row__: ClassVar[type[UserRow]]
        balance: sqlite.Col[int] = sqlite.Integer()

    class UserRow(User, sqlite.Row):
        table_name = "users"

    query = native.select(UserRow.balance.add(3)).all()
    assert_eq(query.compile().params, (3,))


async def scalar_caller(transaction: sqlite.Transaction) -> None:
    class User(sqlite.Model):
        balance: sqlite.Col[int] = sqlite.Integer()

    class UserRow(User, sqlite.Row):
        table_name = "users"

    assert_type(
        await transaction.fetch_all(native.select(UserRow.balance).all()), list[int]
    )


@test(mark="fast")
def self_foreign_key_defers_binding() -> None:
    class User(sqlite.Model):
        identity: sqlite.Col[int] = sqlite.Integer(primary_key=True)
        manager_id: sqlite.FKCol[UserRow, int | None] = sqlite.ForeignKey(
            lambda: UserRow.identity, default=None
        )

    class UserRow(User, sqlite.Row):
        table_name = "users"

    query = native.select(UserRow.manager_id).where(UserRow.manager_id.is_null())
    assert_eq(query.compile().params, ())


@test(mark="fast")
def repeated_class_access_preserves_column_identity() -> None:
    from snektest import assert_is

    class Input(sqlite.Model):
        balance: sqlite.Col[int] = sqlite.Integer()

    class Row(Input, sqlite.Row):
        table_name = "identity"

    assert_is(Row.balance, Row.balance)


@test(mark="fast")
def canonical_column_metadata_remains_frozen() -> None:
    from typing import Any

    from snektest import assert_raises

    class User(sqlite.Model):
        balance: sqlite.Col[int] = sqlite.Integer()

    class UserRow(User, sqlite.Row):
        table_name = "users"

    column: Any = UserRow.balance
    native.select(UserRow.balance).all().compile()
    with assert_raises(native.FrozenModelError):
        column.default = 42

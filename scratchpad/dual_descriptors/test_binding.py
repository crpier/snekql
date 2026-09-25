"""Descriptor identity survives lazy binding, aliasing, and terminal graph failure."""

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from typing import Any, ClassVar

from anyio import to_thread
from snekql import sqlite as native
from snektest import assert_eq, assert_is, assert_raises, test

from scratchpad.dual_descriptors import sqlite
from scratchpad.dual_storage.interface import Index


@test(mark="fast")
def column_captured_before_binding_works_with_alias() -> None:
    class User(sqlite.Model):
        balance: sqlite.Col[int] = sqlite.Integer()

    class UserRow(User, sqlite.Row):
        table_name = "users"

    class Role:
        pass

    balance = UserRow.balance
    role = native.alias(sqlite.table(UserRow), Role, name="u")
    query = native.select(role.column(balance)).all()
    assert_eq(query.compile().sql, 'SELECT "balance" FROM "users" AS "u"')


@test(mark="fast")
def input_column_cannot_be_a_query_source_after_erasure() -> None:
    class User(sqlite.Model):
        balance: sqlite.Col[int] = sqlite.Integer()

    source: Any = User.balance
    with assert_raises(native.QueryConstructionError):
        native.select(source)


@test(mark="fast")
def inherited_columns_have_distinct_row_owners() -> None:
    class Input(sqlite.Model):
        balance: sqlite.Col[int] = sqlite.Integer()

    class First(Input, sqlite.Row):
        table_name = "first"

    class Second(Input, sqlite.Row):
        table_name = "second"

    assert_eq(
        native.select(First.balance).all().compile().sql,
        'SELECT "balance" FROM "first"',
    )
    assert_eq(
        native.select(Second.balance).all().compile().sql,
        'SELECT "balance" FROM "second"',
    )


@test(mark="fast")
def constructed_input_does_not_evaluate_foreign_targets() -> None:
    attempts = []

    def target() -> sqlite.Column[UserRow, int]:
        attempts.append("called")
        return UserRow.identity

    class User(sqlite.Model):
        identity: sqlite.Col[int] = sqlite.Integer(primary_key=True)
        parent: sqlite.FKCol[UserRow, int | None] = sqlite.ForeignKey(
            target, default=None
        )

    User(identity=1)
    assert_eq(attempts, [])

    class UserRow(User, sqlite.Row):
        table_name = "users"


@test(mark="fast")
def partially_built_columns_stay_unreadable_after_failure() -> None:
    class User(sqlite.Model):
        balance: sqlite.Col[int] = sqlite.Integer()
        __indexes__: ClassVar = [Index("missing")]

    class UserRow(User, sqlite.Row):
        table_name = "users"

    balance = UserRow.balance
    with assert_raises(native.ModelDeclarationError):
        sqlite.table(UserRow)
    with assert_raises(native.ModelDeclarationError):
        balance.eq(1)


@test(mark="fast")
def mutual_table_graph_does_not_require_declaration_order_binding() -> None:
    class Department(sqlite.Model):
        identity: sqlite.Col[int] = sqlite.Integer(primary_key=True)
        leader: sqlite.FKCol[EmployeeRow, int | None] = sqlite.ForeignKey(
            lambda: EmployeeRow.identity, default=None
        )

    class DepartmentRow(Department, sqlite.Row):
        table_name = "departments"

    department_key = DepartmentRow.identity

    class Employee(sqlite.Model):
        identity: sqlite.Col[int] = sqlite.Integer(primary_key=True)
        department: sqlite.FKCol[DepartmentRow, int] = sqlite.ForeignKey(department_key)

    class EmployeeRow(Employee, sqlite.Row):
        table_name = "employees"

    query = (
        native.select(sqlite.table(EmployeeRow))
        .join(
            sqlite.table(DepartmentRow),
            on=EmployeeRow.department.references(department_key),
        )
        .all()
    )
    assert_eq(query.compile().params, ())


@test(mark="fast")
def reentrant_foreign_access_poisons_the_graph() -> None:
    def target() -> sqlite.Column[UserRow, int]:
        with assert_raises(native.ModelDeclarationError):
            UserRow.identity.eq(1)
        return UserRow.identity

    class User(sqlite.Model):
        identity: sqlite.Col[int] = sqlite.Integer(primary_key=True)
        parent: sqlite.FKCol[UserRow, int | None] = sqlite.ForeignKey(
            target, default=None
        )

    class UserRow(User, sqlite.Row):
        table_name = "users"

    with assert_raises(native.ModelDeclarationError):
        sqlite.table(UserRow)


@test(mark="medium")
async def concurrent_queries_share_one_bound_column() -> None:
    attempts = []

    def target() -> sqlite.Column[UserRow, int]:
        attempts.append("called")
        return UserRow.identity

    class User(sqlite.Model):
        identity: sqlite.Col[int] = sqlite.Integer(primary_key=True)
        parent: sqlite.FKCol[UserRow, int | None] = sqlite.ForeignKey(
            target, default=None
        )

    class UserRow(User, sqlite.Row):
        table_name = "users"

    def concurrent() -> list[sqlite.Column[UserRow, int]]:
        barrier = Barrier(2)

        def query() -> sqlite.Column[UserRow, int]:
            column = UserRow.identity
            barrier.wait(timeout=5)
            native.select(column).all().compile()
            return column

        with ThreadPoolExecutor(max_workers=2) as pool:
            first = pool.submit(query)
            second = pool.submit(query)
            return [first.result(timeout=10), second.result(timeout=10)]

    columns = await to_thread.run_sync(concurrent)
    assert_eq(attempts, ["called"])
    assert_is(columns[0], columns[1])


@test(mark="fast")
def composite_foreign_targets_accept_direct_columns() -> None:
    from scratchpad.dual_storage.interface import ForeignKeyConstraint

    class Parent(sqlite.Model):
        tenant: sqlite.Col[int] = sqlite.Integer()
        number: sqlite.Col[int] = sqlite.Integer()
        __indexes__: ClassVar = [Index(tenant, number, unique=True)]

    class ParentRow(Parent, sqlite.Row):
        table_name = "parents"

    class Child(sqlite.Model):
        tenant: sqlite.Col[int] = sqlite.Integer()
        number: sqlite.Col[int] = sqlite.Integer()
        __foreign_keys__: ClassVar = [
            ForeignKeyConstraint(
                tenant, number, references=lambda: (ParentRow.tenant, ParentRow.number)
            )
        ]

    class ChildRow(Child, sqlite.Row):
        table_name = "children"

    from snektest import assert_in

    assert_in('REFERENCES "parents"', sqlite.scaffold(ChildRow))


@test(mark="fast")
def erased_foreign_targets_cannot_cross_backend_families() -> None:
    from scratchpad.dual_descriptors.maria_models import ProductRow

    foreign: Any = sqlite.ForeignKey

    class Input(sqlite.Model):
        price: sqlite.FKCol[Any, int] = foreign(ProductRow.identity)

    class Row(Input, sqlite.Row):
        table_name = "wrong_family"

    with assert_raises(native.ModelDeclarationError):
        sqlite.table(Row)


@test(mark="fast")
def required_foreign_target_mismatch_is_runtime_validated() -> None:
    from scratchpad.dual_descriptors.application import PostRow, UserRow
    from scratchpad.paired_advanced.contracts import UserId

    class Wrong(sqlite.Model):
        parent: sqlite.FKCol[PostRow, UserId] = sqlite.ForeignKey(UserRow.user_id)

    class WrongRow(Wrong, sqlite.Row):
        table_name = "wrong"

    with assert_raises(native.ModelDeclarationError):
        sqlite.table(WrongRow)

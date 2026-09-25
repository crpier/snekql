"""Input-first costs and guards, separate from successful application stories."""

from typing import Any, ClassVar

from snekql import sqlite as native
from snektest import assert_eq, assert_in, assert_raises, test

from scratchpad.paired_situations import body, dual


@test(mark="fast")
def local_self_reference_matches_native_scaffold() -> None:
    assert_eq(dual.local_comment_schema(), body.local_comment_schema())


@test(mark="fast")
def complete_constructor_rejects_erased_missing_identity() -> None:
    constructor: Any = dual.CounterRow
    with assert_raises(native.ModelValidationError):
        constructor(count=3)


@test(mark="fast")
def complete_rows_inherit_input_behavior() -> None:
    assert_eq(isinstance(dual.complete_counter(42, 3), dual.Counter), True)


@test(mark="fast")
def nullable_datetime_retains_native_binding_failure() -> None:
    with assert_raises(native.ModelDeclarationError):
        dual.nullable_datetime_default()


@test(mark="fast")
def decimal_foreign_key_retains_storage_precision() -> None:
    assert_in("`amount` DECIMAL(12,2)", dual.decimal_fk_schema())


@test(mark="fast")
def input_class_cannot_be_an_erased_query_source() -> None:
    source: Any = dual.User
    with assert_raises(native.ModelDeclarationError):
        dual.sqlite.select(source)


@test(mark="fast")
def input_column_cannot_be_an_erased_query_source() -> None:
    column: Any = dual.User.email
    with assert_raises(native.ModelDeclarationError):
        dual.sqlite.select(column)


@test(mark="fast")
def wrong_maria_pair_rejects_insertion() -> None:
    class Wrong(dual.mariadb.Model):
        __row__: ClassVar[type[dual.ProductRow]]
        price: dual.mariadb.Col[int] = dual.mariadb.Integer()

    with assert_raises(dual.native_maria.ModelDeclarationError):
        dual.mariadb.insert(Wrong(price=1))


@test(mark="fast")
def maria_pair_cannot_be_replaced() -> None:
    with assert_raises(native.FrozenModelError):
        dual.Product.__row__ = dual.ProductRow


@test(mark="fast")
def absent_generated_refinement_rejects_at_binding() -> None:
    class Event(dual.sqlite.Model):
        event_id: dual.sqlite.Col[int | dual.sqlite.Omitted] = dual.sqlite.Integer(
            primary_key=True, auto_increment=True, default=dual.sqlite.OMIT
        )

    class EventRow(Event, dual.sqlite.Row):
        table_name = "events"

    with assert_raises(native.ModelDeclarationError):
        dual.sqlite.scaffold(EventRow)


@test(mark="fast")
def premature_binding_stays_failed_after_other_class_arrives() -> None:
    class Department(dual.sqlite.Model):
        department_id: dual.sqlite.Col[int] = dual.sqlite.Integer(primary_key=True)
        manager_id: dual.sqlite.FKCol[EmployeeRow, int | None] = dual.sqlite.ForeignKey(
            lambda: EmployeeRow.employee_id, default=None
        )

    class DepartmentRow(Department, dual.sqlite.Row):
        table_name = "early_departments"

    with assert_raises(native.ModelDeclarationError):
        dual.sqlite.scaffold(DepartmentRow)

    class Employee(dual.sqlite.Model):
        employee_id: dual.sqlite.Col[int] = dual.sqlite.Integer(primary_key=True)

    class EmployeeRow(Employee, dual.sqlite.Row):
        table_name = "early_employees"

    with assert_raises(native.ModelDeclarationError):
        dual.sqlite.scaffold(DepartmentRow)

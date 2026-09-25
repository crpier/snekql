"""Accepted static counterexamples must not be mistaken for runtime guarantees."""

from typing import Any, ClassVar, assert_type

from snekql import sqlite
from snektest import assert_eq, assert_in, assert_is, assert_raises, test

from scratchpad.paired_situations import body as b
from scratchpad.paired_situations import nested as n


@test(mark="fast")
def body_complete_constructor_retains_missing_identity_hole() -> None:
    counter = b.Counter[sqlite.Fetched](count=3)
    assert_type(counter.counter_id, int)
    assert_is(counter.counter_id, sqlite.PENDING_GENERATION)


@test(mark="fast")
def body_unchecked_constructor_retains_missing_identity_hole() -> None:
    counter = b.Counter[sqlite.Fetched].construct(count=3)
    assert_type(counter.counter_id, int)
    assert_is(counter.counter_id, sqlite.PENDING_GENERATION)


@test(mark="fast")
def nested_complete_constructor_rejects_missing_identity_after_erasure() -> None:
    constructor: Any = n.Counter
    with assert_raises(sqlite.ModelValidationError):
        constructor(count=3)


@test(mark="fast")
def nested_pending_is_not_complete_even_when_populated() -> None:
    pending = n.Counter.Pending(counter_id=42, count=3)
    assert_eq(isinstance(pending, n.Counter), False)


@test(mark="fast")
def body_specialized_query_source_rejects_at_runtime() -> None:
    with assert_raises(sqlite.QueryConstructionError):
        sqlite.select(b.User[sqlite.Fetched]).all()


@test(mark="fast")
def nested_nullable_datetime_sql_default_rejects_at_binding() -> None:
    with assert_raises(sqlite.ModelDeclarationError):
        n.nullable_datetime_default()


@test(mark="fast")
def body_nullable_datetime_sql_default_rejects() -> None:
    with assert_raises(sqlite.ModelDeclarationError):
        b.nullable_datetime_default()


@test(mark="fast")
def nested_decimal_fk_preserves_precision() -> None:
    assert_in("`amount` DECIMAL(12,2)", n.decimal_fk_schema())


@test(mark="fast")
def body_decimal_fk_retains_native_precision_failure() -> None:
    with assert_raises(b.mariadb.SchemaError):
        b.decimal_fk_schema()


@test(mark="fast")
def nested_wrong_row_witness_rejects_at_declaration() -> None:
    with assert_raises(sqlite.ModelDeclarationError):

        class Wrong(n.sqlite.Row):
            count: n.sqlite.Col[int] = n.sqlite.Integer()

            class Pending(n.sqlite.Pending):
                __row__: ClassVar[type[n.Counter]]
                count: n.sqlite.Col[int]


@test(mark="fast")
def body_wrong_result_witness_rejects_at_declaration() -> None:
    with assert_raises(sqlite.ModelDeclarationError):

        class Wrong[State = sqlite.Pending](b.Model[State]):
            __read_type__: ClassVar[b.ReadType[b.Counter[sqlite.Fetched]]]
            count: sqlite.Col[int] = sqlite.Integer()


@test(mark="fast")
def nested_fk_owner_disagreement_rejects_only_at_schema_binding() -> None:
    class Wrong(n.sqlite.Row):
        table_name = "wrong_owner"
        parent: n.sqlite.FKCol[n.User, n.UserId] = n.sqlite.ForeignKey(n.User.user_id)

        class Pending(n.sqlite.Pending):
            __row__: ClassVar[type[Wrong]]
            parent: n.sqlite.FKCol[n.Post, n.UserId]

    Wrong.Pending(parent=n.UserId(1))
    with assert_raises(sqlite.ModelDeclarationError):
        n.sqlite.scaffold(Wrong)


@test(mark="fast")
def nested_fk_value_domain_rejects_at_schema_binding() -> None:
    class Wrong(n.sqlite.Row):
        table_name = "wrong_domain"
        parent: n.sqlite.FKCol[n.User, str] = n.sqlite.ForeignKey(n.User.user_id)

        class Pending(n.sqlite.Pending):
            __row__: ClassVar[type[Wrong]]
            parent: n.sqlite.FKCol[n.User, str]

    with assert_raises(sqlite.ModelDeclarationError):
        n.sqlite.scaffold(Wrong)


@test(mark="fast")
def nested_json_kind_drift_rejects_at_declaration() -> None:
    with assert_raises(sqlite.ModelDeclarationError):

        class Wrong(n.mariadb.Row):
            payload: n.mariadb.JsonCol[dict[str, int]] = n.mariadb.Json()

            class Pending(n.mariadb.Pending):
                __row__: ClassVar[type[Wrong]]
                payload: n.mariadb.Col[dict[str, int]]


@test(mark="fast")
def premature_mutual_binding_remains_failed_after_target_arrives() -> None:
    class Department(n.sqlite.Row):
        table_name = "early_departments"
        department_id: n.sqlite.Col[int] = n.sqlite.Integer(primary_key=True)
        manager: n.sqlite.FKCol[Employee, int | None] = n.sqlite.ForeignKey(
            lambda: Employee.employee_id
        )

        class Pending(n.sqlite.Pending):
            __row__: ClassVar[type[Department]]
            department_id: n.sqlite.Col[int]
            manager: n.sqlite.FKCol[Employee, int | None] = n.sqlite.default(None)

    with assert_raises(sqlite.ModelDeclarationError):
        n.sqlite.scaffold(Department)

    class Employee(n.sqlite.Row):
        table_name = "early_employees"
        employee_id: n.sqlite.Col[int] = n.sqlite.Integer(primary_key=True)

        class Pending(n.sqlite.Pending):
            __row__: ClassVar[type[Employee]]
            employee_id: n.sqlite.Col[int]

    with assert_raises(sqlite.ModelDeclarationError):
        n.sqlite.scaffold(Department)


@test(mark="fast")
def body_statically_accepted_assignment_rejects_at_runtime() -> None:
    counter = b.complete_counter(42, 3)
    with assert_raises(sqlite.FrozenModelError):
        counter.count = 4


@test(mark="fast")
def nested_erased_assignment_rejects_at_runtime() -> None:
    from scratchpad.dual_features.records import ModelError

    counter: Any = n.complete_counter(42, 3)
    with assert_raises(ModelError):
        counter.count = 4

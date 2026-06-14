"""Shared schema plan tests."""

from __future__ import annotations

from typing import Any, ClassVar

from snektest import assert_eq, assert_raises, test

from snekql import (
    MISSING,
    Fetched,
    Index,
    Integer,
    Model,
    Pending,
    SchemaError,
    Text,
)
from snekql._schema_plan import PlannedForeignKey, build_schema_plan


@test(mark="fast")
def schema_plan_preserves_model_order_and_normalizes_indexes() -> None:
    """Schema startup derives table names and managed indexes once per model."""

    class User[S = Pending](Model[S, "User[Fetched]"]):
        """First table model in a schema plan."""

        email: User.Col[str] = Text(nullable=False, unique=True)
        status: User.Col[str] = Text(nullable=False)

        __indexes__: ClassVar[list[Index[Any]]] = [Index(status)]

    class AuditLog[S = Pending](Model[S, "AuditLog[Fetched]"]):
        """Second table model in a schema plan."""

        message: AuditLog.Col[str] = Text(nullable=False)

    plan = build_schema_plan([User, AuditLog])

    assert_eq([model.table_name for model in plan.models], ["user", "audit_log"])
    assert_eq(
        [index.name for index in plan.models[0].indexes],
        ["ux_user_email", "ix_user_status"],
    )
    assert_eq([index.name for index in plan.models[1].indexes], [])


@test(mark="fast")
def schema_plan_rejects_duplicate_resolved_names() -> None:
    """Schema startup validates duplicate table and index names in one plan."""

    class First[S = Pending](Model[S, "First[Fetched]"]):
        """First table model using a duplicate index name."""

        email: First.Col[str] = Text(nullable=False)
        __indexes__: ClassVar[list[Index[Any]]] = [Index(email, name="ix_duplicate")]

    class Second[S = Pending](Model[S, "Second[Fetched]"]):
        """Second table model using a duplicate index name."""

        email: Second.Col[str] = Text(nullable=False)
        __indexes__: ClassVar[list[Index[Any]]] = [Index(email, name="ix_duplicate")]

    class DuplicateFirst[S = Pending](Model[S, "DuplicateFirst[Fetched]"]):
        """First table model using a duplicate table name."""

        __tablename__ = "duplicate"
        email: DuplicateFirst.Col[str] = Text(nullable=False)

    class DuplicateSecond[S = Pending](Model[S, "DuplicateSecond[Fetched]"]):
        """Second table model using a duplicate table name."""

        __tablename__ = "duplicate"
        email: DuplicateSecond.Col[str] = Text(nullable=False)

    with assert_raises(SchemaError):
        _ = build_schema_plan([First, Second])

    with assert_raises(SchemaError):
        _ = build_schema_plan([DuplicateFirst, DuplicateSecond])


@test(mark="fast")
def schema_plan_resolves_foreign_key_constraints_from_annotations() -> None:
    """`foreign_key=True` columns resolve to the target table's primary key.

    A typed-only reference (an ``FKCol`` without ``foreign_key=True``) declares a
    relationship for joins but emits no constraint, so it is absent from the
    resolved foreign keys.
    """

    class User[S = Pending](Model[S, "User[Fetched]"]):
        """Referenced table whose primary key anchors the constraint."""

        id: User.GenCol[int] = Integer(
            primary_key=True,
            auto_increment=True,
            default=MISSING,
        )
        email: User.Col[str] = Text(nullable=False)

    class Order[S = Pending](Model[S, "Order[Fetched]"]):
        """Table carrying an enforced and a typed-only reference to ``User``."""

        id: Order.GenCol[int] = Integer(
            primary_key=True,
            auto_increment=True,
            default=MISSING,
        )
        user_id: Order.FKCol[User, int] = Integer(foreign_key=True)
        soft_user_id: Order.FKCol[User, int] = Integer()
        note: Order.Col[str] = Text(nullable=False)

    plan = build_schema_plan([User, Order])

    assert_eq(plan.models[0].foreign_keys, ())
    assert_eq(
        plan.models[1].foreign_keys,
        (
            PlannedForeignKey(
                column_name="user_id",
                target_table="user",
                target_column="id",
            ),
        ),
    )


@test(mark="fast")
def schema_plan_rejects_foreign_key_without_a_target_annotation() -> None:
    """A ``foreign_key=True`` column must declare a target via ``FKCol``."""

    class Order[S = Pending](Model[S, "Order[Fetched]"]):
        """Table flagging a plain column as a foreign key without a target."""

        user_id: Order.Col[int] = Integer(foreign_key=True)
        note: Order.Col[str] = Text(nullable=False)

    with assert_raises(SchemaError):
        _ = build_schema_plan([Order])


@test(mark="fast")
def schema_plan_rejects_foreign_key_to_a_target_without_one_primary_key() -> None:
    """The target of an enforced foreign key must have exactly one primary key."""

    class Keyless[S = Pending](Model[S, "Keyless[Fetched]"]):
        """Referenced table that declares no primary key."""

        name: Keyless.Col[str] = Text(nullable=False)

    class Order[S = Pending](Model[S, "Order[Fetched]"]):
        """Table referencing a primary-keyless target."""

        ref: Order.FKCol[Keyless, str] = Text(foreign_key=True)

    with assert_raises(SchemaError):
        _ = build_schema_plan([Keyless, Order])

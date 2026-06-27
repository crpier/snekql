"""Shared schema plan tests."""

from __future__ import annotations

from typing import Any, ClassVar

from snektest import assert_eq, assert_raises, test

from snekql._schema_plan import PlannedForeignKey, build_schema_plan
from snekql.sqlite import (
    PENDING_GENERATION,
    Fetched,
    ForeignKey,
    Index,
    Integer,
    Model,
    Pending,
    SchemaError,
    Text,
)


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
def schema_plan_resolves_a_primary_key_target_named_explicitly() -> None:
    """`ForeignKey(User.id)` resolves to the named primary-key target column.

    A typed-only reference (an ``FKCol`` declared with a plain storage specifier)
    records no target, so it declares a relationship for joins but emits no
    constraint and is absent from the resolved foreign keys.
    """

    class User[S = Pending](Model[S, "User[Fetched]"]):
        """Referenced table whose primary key anchors the constraint."""

        id: User.GenCol[int] = Integer(
            primary_key=True,
            auto_increment=True,
            default=PENDING_GENERATION,
        )
        email: User.Col[str] = Text(nullable=False)

    class Order[S = Pending](Model[S, "Order[Fetched]"]):
        """Table carrying an enforced and a typed-only reference to ``User``."""

        id: Order.GenCol[int] = Integer(
            primary_key=True,
            auto_increment=True,
            default=PENDING_GENERATION,
        )
        user_id: Order.FKCol[User, int] = ForeignKey(User.id)
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
def schema_plan_resolves_a_non_primary_key_unique_target_column() -> None:
    """`ForeignKey(User.email)` resolves to a unique non-PK target column."""

    class User[S = Pending](Model[S, "User[Fetched]"]):
        """Referenced table whose unique email is a non-PK target."""

        id: User.GenCol[int] = Integer(primary_key=True, default=PENDING_GENERATION)
        email: User.Col[str] = Text(nullable=False, unique=True)

    class Order[S = Pending](Model[S, "Order[Fetched]"]):
        """Table referencing the target's unique email column."""

        owner_email: Order.FKCol[User, str] = ForeignKey(User.email, nullable=False)

    plan = build_schema_plan([User, Order])

    assert_eq(
        plan.models[1].foreign_keys,
        (
            PlannedForeignKey(
                column_name="owner_email",
                target_table="user",
                target_column="email",
            ),
        ),
    )


@test(mark="fast")
def schema_plan_rejects_a_foreign_key_to_a_non_unique_target_column() -> None:
    """An FK target column must be a primary key or carry a unique constraint."""

    class User[S = Pending](Model[S, "User[Fetched]"]):
        """Referenced table whose name column is neither PK nor unique."""

        id: User.GenCol[int] = Integer(primary_key=True, default=PENDING_GENERATION)
        name: User.Col[str] = Text(nullable=False)

    class Order[S = Pending](Model[S, "Order[Fetched]"]):
        """Table referencing a non-unique target column."""

        owner_name: Order.FKCol[User, str] = ForeignKey(User.name)

    with assert_raises(SchemaError):
        _ = build_schema_plan([User, Order])


@test(mark="fast")
def schema_plan_rejects_a_foreign_key_whose_target_is_not_on_the_annotated_model() -> (
    None
):
    """The recorded target column must belong to the annotation's target model."""

    class User[S = Pending](Model[S, "User[Fetched]"]):
        """Table owning the column the foreign key actually points at."""

        email: User.Col[str] = Text(nullable=False, unique=True)

    class Region[S = Pending](Model[S, "Region[Fetched]"]):
        """Unrelated table named as the annotated target."""

        code: Region.Col[str] = Text(nullable=False, unique=True)

    class Order[S = Pending](Model[S, "Order[Fetched]"]):
        """Table whose annotation and recorded target disagree."""

        owner: Order.FKCol[Region, str] = ForeignKey(User.email)  # type: ignore[arg-type]

    with assert_raises(SchemaError):
        _ = build_schema_plan([User, Region, Order])

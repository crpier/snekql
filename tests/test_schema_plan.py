"""Shared schema plan tests."""

from __future__ import annotations

from typing import Any, ClassVar

from snektest import assert_eq, assert_raises, test

from snekql import Index, Model, Pending, SchemaError, Text
from snekql._schema_plan import build_schema_plan


@test(mark="fast")
def schema_plan_preserves_model_order_and_normalizes_indexes() -> None:
    """Schema startup derives table names and managed indexes once per model."""

    class User[S = Pending](Model[S, "User[object]"]):
        """First table model in a schema plan."""

        email: User.Col[str] = Text(nullable=False, unique=True)
        status: User.Col[str] = Text(nullable=False)

        __indexes__: ClassVar[list[Index[Any]]] = [Index(status)]

    class AuditLog[S = Pending](Model[S, "AuditLog[object]"]):
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

    class First[S = Pending](Model[S, "First[object]"]):
        """First table model using a duplicate index name."""

        email: First.Col[str] = Text(nullable=False)
        __indexes__: ClassVar[list[Index[Any]]] = [Index(email, name="ix_duplicate")]

    class Second[S = Pending](Model[S, "Second[object]"]):
        """Second table model using a duplicate index name."""

        email: Second.Col[str] = Text(nullable=False)
        __indexes__: ClassVar[list[Index[Any]]] = [Index(email, name="ix_duplicate")]

    class DuplicateFirst[S = Pending](Model[S, "DuplicateFirst[object]"]):
        """First table model using a duplicate table name."""

        __tablename__ = "duplicate"
        email: DuplicateFirst.Col[str] = Text(nullable=False)

    class DuplicateSecond[S = Pending](Model[S, "DuplicateSecond[object]"]):
        """Second table model using a duplicate table name."""

        __tablename__ = "duplicate"
        email: DuplicateSecond.Col[str] = Text(nullable=False)

    with assert_raises(SchemaError):
        _ = build_schema_plan([First, Second])

    with assert_raises(SchemaError):
        _ = build_schema_plan([DuplicateFirst, DuplicateSecond])

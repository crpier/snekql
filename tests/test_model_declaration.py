"""Table model declaration and value semantics tests."""

from __future__ import annotations

from collections.abc import Callable
from typing import ClassVar, cast

from snektest import assert_eq, assert_false, assert_is, assert_raises, test

from snekql import (
    MISSING,
    Fetched,
    FrozenModelError,
    Integer,
    Model,
    ModelDeclarationError,
    ModelValidationError,
    Pending,
    Text,
)


@test()
def pending_model_construction_applies_defaults_and_missing() -> None:
    """Constructed table models expose provided values, defaults, and MISSING."""

    class User[S = Pending](Model[S, "User[Fetched]"]):
        """Table model with normal and generated columns."""

        id: User.GenCol[int] = Integer(default=MISSING)
        email: User.Col[str] = Text(nullable=False)
        status: User.Col[str] = Text(default="active")

    user = User(email="alice@example.com")

    assert_is(user.id, MISSING)
    assert_eq(user.email, "alice@example.com")
    assert_eq(user.status, "active")


@test()
def model_construction_rejects_missing_and_unknown_values() -> None:
    """Constructing pending models validates constructor field names."""

    class User[S = Pending](Model[S, "User[Fetched]"]):
        """Table model with one required field."""

        email: User.Col[str] = Text(nullable=False)

    user_constructor = cast(Callable[..., User[Pending]], User)

    with assert_raises(ModelValidationError):
        _ = user_constructor()

    with assert_raises(ModelValidationError):
        _ = user_constructor(email="alice@example.com", nickname="alice")


@test()
def model_construction_calls_default_factories_per_instance() -> None:
    """Default factories create real values independently for each model."""

    class Event[S = Pending](Model[S, "Event[Fetched]"]):
        """Table model with a default factory."""

        tags: Event.Col[list[str]] = Text(default_factory=list)

    first = Event()
    second = Event()

    first.tags.append("first")

    assert_eq(first.tags, ["first"])
    assert_eq(second.tags, [])


@test()
def model_instances_are_frozen_after_construction() -> None:
    """Post-construction column assignment raises the domain frozen error."""

    class User[S = Pending](Model[S, "User[Fetched]"]):
        """Table model with one mutable-looking field."""

        email: User.Col[str] = Text(nullable=False)

    user = User(email="alice@example.com")

    with assert_raises(FrozenModelError):
        user.email = "eve@example.com"


@test()
def model_repr_equality_and_hashing_are_value_based() -> None:
    """Models compare by field values, omit MISSING in repr, and are unhashable."""

    class User[S = Pending](Model[S, "User[Fetched]"]):
        """Table model for deterministic value semantics."""

        id: User.GenCol[int] = Integer(default=MISSING)
        email: User.Col[str] = Text(nullable=False)

    first = User(email="alice@example.com")
    second = User(email="alice@example.com")
    third = User(email="bob@example.com")

    assert_eq(repr(first), "User[Pending](email='alice@example.com')")
    assert_eq(first, second)
    assert_false(first == third)
    with assert_raises(TypeError):
        _ = hash(first)


@test()
def table_names_are_inferred_or_overridden_and_validated() -> None:
    """Model class creation resolves stable table names from public rules."""

    class AuditLog[S = Pending](Model[S, "AuditLog[Fetched]"]):
        """Table model using inferred table name."""

        message: AuditLog.Col[str] = Text(nullable=False)

    class User[S = Pending](Model[S, "User[Fetched]"]):
        """Table model using explicit table name."""

        __tablename__ = "users"
        email: User.Col[str] = Text(nullable=False)

    assert_eq(AuditLog.__tablename__, "audit_log")
    assert_eq(User.__tablename__, "users")

    with assert_raises(ModelDeclarationError):
        class InvalidName[S = Pending](Model[S, "InvalidName[Fetched]"]):
            """Table model with invalid table name."""

            __tablename__ = "not valid"
            email: InvalidName.Col[str] = Text(nullable=False)


@test()
def unsupported_model_body_members_raise_declaration_errors() -> None:
    """V1 model bodies reject non-column annotations and computed properties."""

    with assert_raises(ModelDeclarationError):
        class PlainAnnotation[S = Pending](Model[S, "PlainAnnotation[Fetched]"]):
            """Invalid table model with a plain instance annotation."""

            email: str

    class WithClassVar[S = Pending](Model[S, "WithClassVar[Fetched]"]):
        """Valid table model with an allowed class-level constant."""

        category: ClassVar[str] = "users"
        email: WithClassVar.Col[str] = Text(nullable=False)

    assert_eq(WithClassVar.category, "users")

    with assert_raises(ModelDeclarationError):
        class ComputedProperty[S = Pending](Model[S, "ComputedProperty[Fetched]"]):
            """Invalid table model with a computed property."""

            email: ComputedProperty.Col[str] = Text(nullable=False)

            @property
            def normalized_email(self) -> str:
                return "computed"


@test()
def non_direct_model_declarations_are_rejected() -> None:
    """V1 table models reject concrete subclasses and mixin bases."""

    class User[S = Pending](Model[S, "User[Fetched]"]):
        """Concrete table model."""

        email: User.Col[str] = Text(nullable=False)

    class EmailMixin:
        """Mixin that is intentionally unsupported for v1 models."""

    with assert_raises(ModelDeclarationError):
        _ = type("AdminUser", (User,), {})

    with assert_raises(ModelDeclarationError):
        _ = type("MixedUser", (EmailMixin, Model), {})

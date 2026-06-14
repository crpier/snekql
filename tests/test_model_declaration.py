"""Table model declaration and value semantics tests."""

from __future__ import annotations

from abc import abstractmethod
from collections.abc import Callable
from typing import TYPE_CHECKING, Any, ClassVar, cast

from pydantic import PositiveInt
from snektest import (
    assert_eq,
    assert_false,
    assert_is,
    assert_isinstance,
    assert_raises,
    test,
)

from snekql import (
    MISSING,
    FrozenModelError,
    Index,
    Integer,
    Json,
    Model,
    ModelDeclarationError,
    ModelValidationError,
    Pending,
    Real,
    Text,
)

if TYPE_CHECKING:
    from snekql import Fetched


@test(mark="fast")
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


@test(mark="fast")
def model_construction_rejects_missing_and_unknown_values() -> None:
    """Constructing pending models validates constructor field names."""

    class User[S = Pending](Model[S, "User[Fetched]"]):
        """Table model with one required field."""

        email: User.Col[str] = Text(nullable=False)

    user_constructor = cast("Callable[..., User[Pending]]", User)

    with assert_raises(ModelValidationError):
        _ = user_constructor()

    with assert_raises(ModelValidationError):
        _ = user_constructor(email="alice@example.com", nickname="alice")


@test(mark="fast")
def model_construction_calls_default_factories_per_instance() -> None:
    """Default factories create real values independently for each model."""

    class Event[S = Pending](Model[S, "Event[Fetched]"]):
        """Table model with a default factory."""

        tags: Event.Col[list[str]] = Json(default_factory=list)

    first = Event()
    second = Event()

    first.tags.append("first")

    assert_eq(first.tags, ["first"])
    assert_eq(second.tags, [])


@test(mark="fast")
def model_instances_are_frozen_after_construction() -> None:
    """Post-construction assignment raises the domain frozen error."""

    class User[S = Pending](Model[S, "User[Fetched]"]):
        """Table model with one mutable-looking field."""

        email: User.Col[str] = Text(nullable=False)

    user = User(email="alice@example.com")

    with assert_raises(FrozenModelError):
        user.email = "eve@example.com"

    with assert_raises(FrozenModelError):
        user.nickname = "alice"


@test(mark="fast")
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


@test(mark="fast")
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

    with assert_raises(ModelDeclarationError):
        _ = type("InvalidColumn", (Model,), {"not valid": Text(nullable=False)})


@test(mark="fast")
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

    with assert_raises(ModelDeclarationError):

        class AbstractModel[S = Pending](Model[S, "AbstractModel[Fetched]"]):
            """Invalid abstract table model."""

            email: AbstractModel.Col[str] = Text(nullable=False)

            @abstractmethod
            def normalize(self) -> str:
                """Abstract behavior is intentionally unsupported for v1."""


@test(mark="fast")
def index_declarations_are_validated_in_model_bodies() -> None:
    """Model declarations reject malformed or duplicate index metadata."""

    with assert_raises(ModelDeclarationError):
        _unused_empty_index: object = Index[Any]()

    with assert_raises(ModelDeclarationError):
        _unused_invalid_index: object = Index(cast("Any", "email"))

    with assert_raises(ModelDeclarationError):

        class PrimaryKeyUnique[S = Pending](Model[S, "PrimaryKeyUnique[Fetched]"]):
            """Invalid redundant primary key unique declaration."""

            id: PrimaryKeyUnique.GenCol[int] = Integer(
                primary_key=True,
                unique=True,
                default=MISSING,
            )

    with assert_raises(ModelDeclarationError):

        class TupleIndexes[S = Pending](Model[S, "TupleIndexes[Fetched]"]):
            """Invalid tuple index collection."""

            email: TupleIndexes.Col[str] = Text(nullable=False)
            __indexes__ = (Index(email),)

    with assert_raises(ModelDeclarationError):

        class DuplicateIndexColumns[S = Pending](
            Model[S, "DuplicateIndexColumns[Fetched]"],
        ):
            """Invalid duplicate exact ordered column list."""

            email: DuplicateIndexColumns.Col[str] = Text(nullable=False)
            __indexes__: ClassVar[list[Index[Any]]] = [
                Index(email),
                Index(email, name="ix_duplicate_email"),
            ]


@test(mark="fast")
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


@test(mark="fast")
def model_construction_validates_logical_types_with_pydantic() -> None:
    """Constructing a pending model validates field values against the logical type."""

    class Event[S = Pending](Model[S, "Event[Fetched]"]):
        """Table model with a constrained integer column."""

        receipt: Event.Col[PositiveInt] = Integer(nullable=False)

    event = Event(receipt=5)

    assert_eq(event.receipt, 5)

    with assert_raises(ModelValidationError):
        _ = Event(receipt=-1)


@test(mark="fast")
def construct_builds_pending_models_without_validation() -> None:
    """The construct classmethod skips logical validation as an escape hatch."""

    class Event[S = Pending](Model[S, "Event[Fetched]"]):
        """Table model with a constrained integer column."""

        receipt: Event.Col[PositiveInt] = Integer(nullable=False)

    event = Event.construct(receipt=-1)

    assert_eq(event.receipt, -1)


@test(mark="fast")
def integer_columns_reject_non_int_in_strict_mode() -> None:
    """Strict validation rejects bool and float for Integer columns."""

    class Counter[S = Pending](Model[S, "Counter[Fetched]"]):
        """Table model with an integer column."""

        value: Counter.Col[int] = Integer(nullable=False)

    with assert_raises(ModelValidationError):
        _ = Counter(value=cast("int", True))

    with assert_raises(ModelValidationError):
        _ = Counter(value=cast("int", 1.0))


@test(mark="fast")
def json_columns_validate_annotated_shape() -> None:
    """Json columns validate the annotated container shape, not just dict-ness."""

    class Settings[S = Pending](Model[S, "Settings[Fetched]"]):
        """Table model with a typed JSON column."""

        options: Settings.Col[dict[str, int]] = Json(nullable=False)

    settings = Settings(options={"retries": 3})

    assert_eq(settings.options, {"retries": 3})

    with assert_raises(ModelValidationError):
        _ = Settings(options=cast("dict[str, int]", {"retries": "many"}))


@test(mark="fast")
def real_columns_widen_int_to_float() -> None:
    """Real columns accept int and widen it to float, matching pydantic defaults."""

    class Reading[S = Pending](Model[S, "Reading[Fetched]"]):
        """Table model with a real column."""

        value: Reading.Col[float] = Real(nullable=False)

    reading = Reading(value=cast("float", 1))

    assert_eq(reading.value, 1.0)
    assert_isinstance(reading.value, float)

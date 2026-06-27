"""Table model declaration and value semantics tests."""

from __future__ import annotations

from abc import abstractmethod
from collections.abc import Callable
from datetime import datetime
from typing import Annotated, Any, ClassVar, cast

from pydantic import BaseModel, Json, PositiveInt
from snektest import (
    assert_eq,
    assert_false,
    assert_is,
    assert_isinstance,
    assert_raises,
    assert_true,
    test,
)

from snekql.sqlite import (
    PENDING_GENERATION,
    Blob,
    Fetched,
    ForeignKey,
    FrozenModelError,
    Index,
    Integer,
    Model,
    ModelDeclarationError,
    ModelValidationError,
    Pending,
    Real,
    Text,
)
from tests.fixtures.model_without_future_annotations import Memory


@test(mark="fast")
def generated_columns_detected_without_future_annotations_import() -> None:
    """Generated-column detection works under PEP 649 deferred annotations.

    The fixture module omits `from __future__ import annotations`, so its class
    namespace carries a deferred `__annotate__` function rather than a
    materialized `__annotations__` dict (issue #143). A `CurrentTimestamp`
    server default must still be recognized as a generated column.
    """

    assert_true(Memory.__snekql_columns__["created_at"].is_generated)


@test(mark="fast")
def pending_model_construction_applies_defaults_and_pending_generation() -> None:
    """Constructed models expose values, defaults, and PENDING_GENERATION."""

    class User[S = Pending](Model[S, "User[Fetched]"]):
        """Table model with normal and generated columns."""

        id: User.GenCol[int] = Integer(default=PENDING_GENERATION)
        email: User.Col[str] = Text(nullable=False)
        status: User.Col[str] = Text(default="active")

    user = User(email="alice@example.com")

    assert_is(user.id, PENDING_GENERATION)
    assert_eq(user.email, "alice@example.com")
    assert_eq(user.status, "active")


@test(mark="fast")
def model_construction_rejects_absent_and_unknown_values() -> None:
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

    def new_tags() -> Json[list[str]]:
        return []

    class Event[S = Pending](Model[S, "Event[Fetched]"]):
        """Table model with a default factory."""

        tags: Event.Col[Json[list[str]]] = Text(default_factory=new_tags)

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
    """Models compare by field values, omit PENDING_GENERATION in repr, and are unhashable."""

    class User[S = Pending](Model[S, "User[Fetched]"]):
        """Table model for deterministic value semantics."""

        id: User.GenCol[int] = Integer(default=PENDING_GENERATION)
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
                default=PENDING_GENERATION,
            )

    with assert_raises(ModelDeclarationError):

        class IndexUnique[S = Pending](Model[S, "IndexUnique[Fetched]"]):
            """Invalid redundant column index and unique declaration."""

            email: IndexUnique.Col[str] = Text(
                nullable=False,
                index=True,
                unique=True,
            )

    with assert_raises(ModelDeclarationError):

        class IndexPrimaryKey[S = Pending](Model[S, "IndexPrimaryKey[Fetched]"]):
            """Invalid redundant column index on a primary key."""

            id: IndexPrimaryKey.GenCol[int] = Integer(
                primary_key=True,
                index=True,
                default=PENDING_GENERATION,
            )

    with assert_raises(ModelDeclarationError):

        class IndexCollision[S = Pending](Model[S, "IndexCollision[Fetched]"]):
            """Invalid duplicate of a column index and a table-level index."""

            email: IndexCollision.Col[str] = Text(nullable=False, index=True)
            __indexes__: ClassVar[list[Index[Any]]] = [Index(email)]

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

        options: Settings.Col[Json[dict[str, int]]] = Text(nullable=False)

    settings = Settings(options={"retries": 3})

    assert_eq(settings.options, {"retries": 3})

    with assert_raises(ModelValidationError):
        _ = Settings(options=cast("dict[str, int]", {"retries": "many"}))


@test(mark="fast")
def storage_classes_pair_with_their_logical_types() -> None:
    """A Column Type pairs with whatever Logical Type the annotation names; the
    constructor records only the SQLite storage class."""

    class Sample[S = Pending](Model[S, "Sample[Fetched]"]):
        """Table model pairing storage classes with their logical types."""

        count: Sample.Col[int] = Integer(nullable=False)
        amount: Sample.Col[float] = Real(nullable=False)
        label: Sample.Col[str] = Text(nullable=False)
        payload: Sample.Col[bytes] = Blob(nullable=False)
        enabled: Sample.Col[bool] = Integer(nullable=False)
        created_at: Sample.Col[datetime] = Text(nullable=False)
        optional_count: Sample.Col[int | None] = Integer(nullable=True)
        constrained: Sample.Col[Annotated[int, "meta"]] = Integer(nullable=False)

    assert_eq(Sample.__snekql_columns__["count"].storage_type_name, "Integer")
    assert_eq(Sample.__snekql_columns__["created_at"].storage_type_name, "Text")
    assert_eq(Sample.__snekql_columns__["created_at"].sqlite_storage_class, "TEXT")


@test(mark="fast")
def foreign_key_annotation_storage_pairs_are_accepted() -> None:
    """A foreign-key column's key annotation is checked against derived storage."""

    class User[S = Pending](Model[S, "User[Fetched]"]):
        """Referenced table with an integer primary key."""

        id: User.GenCol[int] = Integer(primary_key=True, default=PENDING_GENERATION)

    class Order[S = Pending](Model[S, "Order[Fetched]"]):
        """Table carrying an integer foreign key to ``User``."""

        user_id: Order.FKCol[User, int] = ForeignKey(User.id, nullable=False)

    assert_eq(Order.__snekql_columns__["user_id"].storage_type_name, "Integer")


@test(mark="fast")
def storage_logical_pairs_are_not_constrained_at_declaration() -> None:
    """There is no declaration-time storage/logical compatibility guard: the
    annotation is the single source of truth and any pairing declares, with
    errors deferred to pydantic at encode/decode (ADR 0005)."""

    class Wide[S = Pending](Model[S, "Wide[Fetched]"]):
        """Pairings the old exact-pair guard would have rejected."""

        ratio: Wide.Col[float] = Integer(nullable=False)
        flag: Wide.Col[bool] = Integer(nullable=False)
        label: Wide.Col[str] = Text(nullable=False)
        maybe_count: Wide.Col[int | None] = Text(nullable=True)

    columns = Wide.__snekql_columns__
    assert_eq(columns["ratio"].sqlite_storage_class, "INTEGER")
    assert_eq(columns["flag"].sqlite_storage_class, "INTEGER")
    assert_eq(columns["maybe_count"].sqlite_storage_class, "TEXT")


@test(mark="fast")
def json_marker_columns_accept_any_payload_type() -> None:
    """The ``pydantic.Json[T]`` marker opts a ``Text()`` column into JSON storage
    for any payload type, resolved through the column's logical adapter."""

    class Document[S = Pending](Model[S, "Document[Fetched]"]):
        """Json marker columns accept any payload annotation."""

        when: Document.Col[Json[datetime]] = Text(nullable=False)
        items: Document.Col[Json[list[int]]] = Text(nullable=False)

    columns = Document.__snekql_columns__
    assert_eq(columns["when"].sqlite_storage_class, "TEXT")
    assert_eq(columns["items"].sqlite_storage_class, "TEXT")


@test(mark="fast")
def forward_ref_json_payload_does_not_block_declaration() -> None:
    """A forward-referenced JSON payload type binds without resolving it eagerly
    at declaration time."""

    class Mixed[S = Pending](Model[S, "Mixed[Fetched]"]):
        """A forward-ref Json sibling must not block binding the scalar column."""

        count: Mixed.Col[int] = Integer(nullable=False)
        blob: Mixed.Col[Json[Payload]] = Text(nullable=False)
        either: Mixed.Col[int | str] = Integer(nullable=False)

    class Payload(BaseModel):
        """Logical type defined only after the model that annotates it."""

        x: int

    assert_eq(Mixed.__snekql_columns__["count"].storage_type_name, "Integer")

    class Reading[S = Pending](Model[S, "Reading[Fetched]"]):
        """Table model with a real column."""

        value: Reading.Col[float] = Real(nullable=False)

    reading = Reading(value=cast("float", 1))

    assert_eq(reading.value, 1.0)
    assert_isinstance(reading.value, float)

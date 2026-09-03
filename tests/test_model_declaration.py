"""Table model declaration and value semantics tests."""

from __future__ import annotations

import warnings
from abc import abstractmethod
from collections.abc import Callable
from datetime import datetime, timedelta
from decimal import Decimal
from typing import TYPE_CHECKING, Annotated, Any, ClassVar, cast

from pydantic import AwareDatetime, BaseModel, Json, PositiveInt
from snektest import (
    Param,
    assert_eq,
    assert_false,
    assert_is,
    assert_isinstance,
    assert_raises,
    assert_true,
    test,
)

from snekql import mariadb
from snekql.model import require_model_columns
from snekql.sqlite import (
    PENDING_GENERATION,
    Blob,
    Canonical,
    CanonicalDecimal,
    Duration,
    Fetched,
    ForeignKey,
    FrozenModelError,
    Index,
    Integer,
    LexicalDatetimeWarning,
    LexicalDecimalWarning,
    LexicalDurationWarning,
    Model,
    ModelDeclarationError,
    ModelValidationError,
    OrderPreserving,
    Pending,
    Real,
    Text,
    UtcDatetime,
)
from snekql.sqlite import GenCol as GeneratedColumn
from tests.fixtures.model_without_future_annotations import Memory

type SafeOrderPreservingDatetime = Annotated[datetime, OrderPreserving]
type SafeCanonicalTextDecimal = Annotated[Decimal, Canonical]
type SafeOrderPreservingTextDecimal = Annotated[Decimal, OrderPreserving]
SqliteModelBase = Model


class DeferredPayloadRow[S = Pending](Model[S, "DeferredPayloadRow[Fetched]"]):
    """Model whose logical payload type is defined later in the module."""

    optional: DeferredPayloadRow.Col[int | None] = Integer(default=None)
    payload: DeferredPayloadRow.Col[DeferredPayload] = Text()


class DeferredPayload(BaseModel):
    """Logical payload defined after the table model that references it."""

    value: str


@test(mark="fast")
def deferred_payload_hint_retries_after_module_population() -> None:
    """A partial forward-reference result is not cached permanently."""

    row = DeferredPayloadRow(payload=DeferredPayload(value="ready"))

    assert_is(DeferredPayloadRow.optional.nullable, True)
    assert_eq(row.payload, DeferredPayload(value="ready"))


@test(mark="fast")
def generated_column_alias_preserves_lifecycle_behavior() -> None:
    """An import alias cannot change whether a column is database-generated."""

    class AliasedGenerated[S = Pending](Model[S, "AliasedGenerated[Fetched]"]):
        """Model using an ordinary import alias for its generated column type."""

        id: GeneratedColumn[int] = Integer(default=PENDING_GENERATION)

    pending = AliasedGenerated()

    assert_true(AliasedGenerated.id.is_generated)
    assert_is(pending.id, PENDING_GENERATION)


@test(mark="fast")
def application_model_named_model_is_a_concrete_table() -> None:
    """The public class name Model does not bypass table declaration behavior."""

    class Model[S = Pending](SqliteModelBase[S, "Model[Fetched]"]):
        """Application table whose domain name happens to be Model."""

        value: Model.Col[str] = Text()

    row = Model(value="ready")

    assert_eq(Model.__tablename__, "model")
    assert_eq(row.value, "ready")


@test(mark="fast")
def framework_base_marker_cannot_be_forged_with_a_boolean() -> None:
    """Only the internal identity marker bypasses concrete-table setup."""

    class Pretender[S = Pending](SqliteModelBase[S, "Pretender[Fetched]"]):
        """Application model with a colliding private-looking class variable."""

        __snekql_framework_base__: ClassVar[bool] = True
        value: Pretender.Col[str] = Text()

    assert_eq(Pretender.__tablename__, "pretender")


@test(mark="fast")
def column_default_and_factory_are_mutually_exclusive() -> None:
    """A field cannot declare two competing Python default sources."""

    with assert_raises(ModelDeclarationError):
        _ = Integer(  # ty: ignore[no-matching-overload]
            default=1, default_factory=lambda: 2
        )


@test(mark="fast")
def column_descriptor_cannot_be_reused_across_models() -> None:
    """One descriptor object cannot be rebound to another model field."""

    class Source[S = Pending](Model[S, "Source[Fetched]"]):
        """Model owning the original descriptor."""

        value: Source.Col[str] = Text()

    descriptor = Source.value

    with assert_raises(ModelDeclarationError):

        class Reused[S = Pending](Model[S, "Reused[Fetched]"]):
            """Model attempting to steal a bound descriptor."""

            copied: Reused.Col[str] = descriptor  # ty: ignore[invalid-assignment]


@test(mark="fast")
def text_decimal_columns_warn_without_canonical_wire_form() -> None:
    """Text decimal columns warn on both backends unless canonicalized."""

    with warnings.catch_warnings(record=True) as caught_warnings:
        warnings.simplefilter("always", LexicalDecimalWarning)

        class SqlitePrice[S = Pending](Model[S, "SqlitePrice[Fetched]"]):
            """SQLite model with decimal text columns."""

            unsafe_amount: SqlitePrice.Col[Decimal] = Text(nullable=False)
            curated_amount: SqlitePrice.Col[CanonicalDecimal] = Text(nullable=False)
            safe_amount: SqlitePrice.Col[SafeCanonicalTextDecimal] = Text(
                nullable=False
            )
            ordered_amount: SqlitePrice.Col[SafeOrderPreservingTextDecimal] = Text(
                nullable=False
            )

        class MariaPrice[S = mariadb.Pending](
            mariadb.Model[S, "MariaPrice[mariadb.Fetched]"],
        ):
            """MariaDB model with a decimal Text column."""

            unsafe_amount: MariaPrice.Col[Decimal] = mariadb.Text(nullable=False)

    assert_eq(len(caught_warnings), 2)
    assert_true(all(item.category is LexicalDecimalWarning for item in caught_warnings))
    assert_true("unsafe_amount" in str(caught_warnings[0].message))
    assert_true("unsafe_amount" in str(caught_warnings[1].message))


@test(mark="fast")
def sqlite_datetime_text_columns_warn_without_order_preserving_wire_form() -> None:
    """SQLite Text datetime columns warn unless their logical type self-certifies."""

    with warnings.catch_warnings(record=True) as caught_warnings:
        warnings.simplefilter("always", LexicalDatetimeWarning)

        class UnsafeAudit[S = Pending](Model[S, "UnsafeAudit[Fetched]"]):
            """Model with datetime text that compares lexically."""

            occurred_at: UnsafeAudit.Col[datetime] = Text(nullable=False)
            displayed_at: UnsafeAudit.Col[AwareDatetime] = Text(nullable=False)
            stored_at: UnsafeAudit.Col[UtcDatetime] = Text(nullable=False)
            safe_at: UnsafeAudit.Col[SafeOrderPreservingDatetime] = Text(nullable=False)

    assert_eq(len(caught_warnings), 2)
    assert_true(
        all(item.category is LexicalDatetimeWarning for item in caught_warnings)
    )
    assert_true("occurred_at" in str(caught_warnings[0].message))
    assert_true("displayed_at" in str(caught_warnings[1].message))


@test(mark="fast")
def text_duration_columns_warn_without_order_preserving_wire_form() -> None:
    """Text duration columns warn on both backends unless they use Duration."""

    with warnings.catch_warnings(record=True) as caught_warnings:
        warnings.simplefilter("always", LexicalDurationWarning)

        class SqliteTimer[S = Pending](Model[S, "SqliteTimer[Fetched]"]):
            """SQLite model with duration text columns."""

            unsafe_elapsed: SqliteTimer.Col[timedelta] = Text(nullable=False)
            curated_elapsed: SqliteTimer.Col[Duration] = Integer(nullable=False)

        class MariaTimer[S = mariadb.Pending](
            mariadb.Model[S, "MariaTimer[mariadb.Fetched]"],
        ):
            """MariaDB model with duration Text and Integer columns."""

            unsafe_elapsed: MariaTimer.Col[timedelta] = mariadb.Text(nullable=False)
            curated_elapsed: MariaTimer.Col[mariadb.Duration] = mariadb.Integer(
                nullable=False
            )

    assert_eq(len(caught_warnings), 2)
    assert_true(
        all(item.category is LexicalDurationWarning for item in caught_warnings)
    )
    assert_true("unsafe_elapsed" in str(caught_warnings[0].message))
    assert_true("unsafe_elapsed" in str(caught_warnings[1].message))


@test(mark="fast")
def duration_over_text_warns_because_integer_wire_form_sorts_lexically() -> None:
    """Duration over Text() warns; its integer wire form is not text-order safe."""

    with warnings.catch_warnings(record=True) as caught_warnings:
        warnings.simplefilter("always", LexicalDurationWarning)

        class LexicalTimer[S = Pending](Model[S, "LexicalTimer[Fetched]"]):
            """SQLite model declaring Duration over lexical Text storage."""

            elapsed: LexicalTimer.Col[Duration] = Text(nullable=False)

    assert_eq(len(caught_warnings), 1)
    assert_true(caught_warnings[0].category is LexicalDurationWarning)
    assert_true("elapsed" in str(caught_warnings[0].message))


@test(mark="fast")
def lexical_datetime_warning_is_suppressible_by_category() -> None:
    """The datetime storage warning uses a category callers can silence."""

    with warnings.catch_warnings(record=True) as caught_warnings:
        warnings.simplefilter("error", LexicalDatetimeWarning)
        warnings.simplefilter("ignore", LexicalDatetimeWarning)

        class SuppressedAudit[S = Pending](Model[S, "SuppressedAudit[Fetched]"]):
            """Model whose unsafe datetime warning is deliberately suppressed."""

            occurred_at: SuppressedAudit.Col[datetime] = Text(nullable=False)

    assert_eq(caught_warnings, [])


@test(mark="fast")
def mariadb_native_datetime_columns_do_not_warn_about_lexical_text() -> None:
    """MariaDB native DateTime storage is not SQLite Text storage."""

    with warnings.catch_warnings(record=True) as caught_warnings:
        warnings.simplefilter("always", LexicalDatetimeWarning)

        class NativeAudit[S = mariadb.Pending](
            mariadb.Model[S, "NativeAudit[mariadb.Fetched]"],
        ):
            """MariaDB model with native datetime storage."""

            occurred_at: NativeAudit.Col[datetime] = mariadb.DateTime(nullable=False)

    assert_eq(caught_warnings, [])


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


@test(
    [
        Param(value=("owner", object), name="owner"),
        Param(value=("name", "renamed"), name="name"),
        Param(value=("nullable", True), name="nullable"),
        Param(value=("default", "inactive"), name="default"),
        Param(value=("primary_key", True), name="primary-key"),
        Param(value=("unique", True), name="unique"),
        Param(value=("storage_class", "BLOB"), name="storage-class"),
        Param(value=("storage_type_name", "Blob"), name="storage-type"),
    ],
    mark="fast",
)
def bound_column_metadata_is_immutable(
    metadata_change: tuple[str, object],
) -> None:
    """A model's finalized column metadata rejects public mutation."""

    class User[S = Pending](Model[S, "User[Fetched]"]):
        """Table model with runtime schema metadata."""

        email: User.Col[str] = Text(nullable=False)

    metadata_name, replacement = metadata_change
    original = getattr(User.email, metadata_name)

    with assert_raises(FrozenModelError) as frozen_error:
        setattr(User.email, metadata_name, replacement)

    assert_eq(
        str(frozen_error.exception),
        f"column metadata for User.email is immutable: {metadata_name}",
    )
    assert_is(getattr(User.email, metadata_name), original)


@test(mark="fast")
def bound_column_metadata_cannot_be_deleted() -> None:
    """Removing finalized metadata raises the same deliberate package error."""

    class User[S = Pending](Model[S, "User[Fetched]"]):
        """Table model with default metadata."""

        status: User.Col[str] = Text(default="active")

    with assert_raises(FrozenModelError) as frozen_error:
        del User.status.default

    assert_eq(
        str(frozen_error.exception),
        "column metadata for User.status is immutable: default",
    )
    assert_eq(User.status.default, "active")


@test(mark="fast")
def finalized_column_metadata_preserves_declaration_facts() -> None:
    """Model finalization freezes metadata only after deriving declaration facts."""

    class Account[S = Pending](Model[S, "Account[Fetched]"]):
        """Table model with derived and explicit column metadata."""

        id: Account.GenCol[int] = Integer(
            primary_key=True,
            default=PENDING_GENERATION,
        )
        nickname: Account.Col[str | None] = Text(default=None, unique=True)

    assert_is(Account.id.owner, Account)
    assert_eq(Account.id.name, "id")
    assert_true(Account.id.is_generated)
    assert_true(Account.id.primary_key)
    assert_is(Account.id.default, PENDING_GENERATION)
    assert_eq(Account.id.storage_class, "INTEGER")
    assert_eq(Account.id.storage_type_name, "Integer")
    assert_true(Account.nickname.nullable)
    assert_is(Account.nickname.default, None)
    assert_true(Account.nickname.unique)


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
def optional_annotation_requires_nullable_true() -> None:
    """A ``| None`` read type must agree with a runtime-nullable column."""

    with assert_raises(ModelDeclarationError):

        class MissingNullable[S = Pending](Model[S, "MissingNullable[Fetched]"]):
            """A `| None` annotation without nullable=True is a contradiction."""

            maybe: MissingNullable.Col[str | None] = Text(nullable=False)


@test(mark="fast")
def optional_annotation_derives_nullable_when_unset() -> None:
    """An unset ``nullable=`` derives from the field's logical annotation."""

    class DerivedNullable[S = Pending](Model[S, "DerivedNullable[Fetched]"]):
        """A `| None` annotation is the source of truth for SQL nullability."""

        maybe: DerivedNullable.Col[str | None] = Text(default=None)

    assert_is(DerivedNullable.maybe.nullable, True)


@test(mark="fast")
def unset_nullable_defaults_to_not_null() -> None:
    """Omitting ``nullable=`` produces a NOT NULL column (#203 F9).

    The column's static read type is non-optional, so the runtime column must be
    NOT NULL; the F2 cross-check accepts the declaration and the stored
    nullability is ``False``, not the old tri-state ``None``.
    """

    class Account[S = Pending](Model[S, "Account[Fetched]"]):
        """A non-optional column declared without nullable= is NOT NULL."""

        id: Account.GenCol[int] = Integer(
            primary_key=True,
            auto_increment=True,
            default=PENDING_GENERATION,
        )
        name: Account.Col[str] = Text()

    assert_is(Account.name.nullable, False)


@test(mark="fast")
def optional_primary_key_annotation_is_rejected() -> None:
    """A primary key cannot promise ``None`` even when nullability is derived."""

    with assert_raises(ModelDeclarationError):

        class OptionalKey[S = Pending](Model[S, "OptionalKey[Fetched]"]):
            """Invalid table with an optional primary-key read type."""

            id: OptionalKey.Col[int | None] = Integer(primary_key=True)


@test(mark="fast")
def non_optional_annotation_rejects_nullable_true() -> None:
    """A non-optional read type must not be declared runtime-nullable."""

    with assert_raises(ModelDeclarationError):

        class NullableNonOptional[S = Pending](
            Model[S, "NullableNonOptional[Fetched]"]
        ):
            """nullable=True without `| None` would decode None into a `str`."""

            value: NullableNonOptional.Col[str] = Text(nullable=True)


@test(mark="fast")
def consistent_nullability_is_accepted() -> None:
    """Matching annotation and ``nullable=`` flag declare without objection."""

    class Profile[S = Pending](Model[S, "Profile[Fetched]"]):
        """Every column's annotation agrees with its nullable flag."""

        id: Profile.GenCol[int] = Integer(
            primary_key=True,
            auto_increment=True,
            default=PENDING_GENERATION,
        )
        email: Profile.Col[str] = Text(nullable=False)
        nickname: Profile.Col[str | None] = Text(nullable=True, default=None)

    assert_eq(Profile(email="a@example.com").nickname, None)


@test(mark="fast")
def integer_columns_reject_float_in_strict_mode() -> None:
    """Strict validation rejects float for Integer columns."""

    class Counter[S = Pending](Model[S, "Counter[Fetched]"]):
        """Table model with an integer column."""

        value: Counter.Col[int] = Integer(nullable=False)

    with assert_raises(ModelValidationError):
        _ = Counter(value=cast("int", 1.0))


@test(mark="fast")
def integer_columns_coerce_bool_to_int() -> None:
    """A bool type-checks where an int column is expected (bool <: int), so the
    runtime coerces it to int rather than rejecting what the type already admits.
    """

    class Counter[S = Pending](Model[S, "Counter[Fetched]"]):
        """Table model with an integer column."""

        value: Counter.Col[int] = Integer(nullable=False)

    counter = Counter(value=True)

    assert_eq(counter.value, 1)
    assert_eq(type(counter.value), int)


@test(mark="fast")
def bool_columns_keep_bool_values() -> None:
    """A Col[bool] keeps a bool logical type, so its values are not coerced."""

    class Flagged[S = Pending](Model[S, "Flagged[Fetched]"]):
        """Table model with a boolean column stored as INTEGER."""

        flag: Flagged.Col[bool] = Integer(nullable=False)

    flagged = Flagged(flag=True)

    assert_eq(flagged.flag, True)
    assert_eq(type(flagged.flag), bool)


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

    with warnings.catch_warnings():
        warnings.simplefilter("ignore", LexicalDatetimeWarning)

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
    assert_eq(Sample.__snekql_columns__["created_at"].storage_class, "TEXT")


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
    assert_eq(columns["ratio"].storage_class, "INTEGER")
    assert_eq(columns["flag"].storage_class, "INTEGER")
    assert_eq(columns["maybe_count"].storage_class, "TEXT")


@test(mark="fast")
def json_marker_columns_accept_any_payload_type() -> None:
    """The ``pydantic.Json[T]`` marker opts a ``Text()`` column into JSON storage
    for any payload type, resolved through the column's logical adapter."""

    with warnings.catch_warnings():
        warnings.simplefilter("ignore", LexicalDatetimeWarning)

        class Document[S = Pending](Model[S, "Document[Fetched]"]):
            """Json marker columns accept any payload annotation."""

            when: Document.Col[Json[datetime]] = Text(nullable=False)
            items: Document.Col[Json[list[int]]] = Text(nullable=False)

    columns = Document.__snekql_columns__
    assert_eq(columns["when"].storage_class, "TEXT")
    assert_eq(columns["items"].storage_class, "TEXT")


@test(mark="fast")
def later_function_local_payload_is_rejected_at_declaration() -> None:
    """A local payload must exist before a model can capture its namespace."""

    if TYPE_CHECKING:

        class Payload(BaseModel):
            """Typing-only stand-in absent from the runtime local namespace."""

            value: str

    with assert_raises(ModelDeclarationError):

        class Mixed[S = Pending](Model[S, "Mixed[Fetched]"]):
            """Model referring to a function-local payload declared later."""

            blob: Mixed.Col[Json[Payload]] = Text(nullable=False)


@test(mark="fast")
def defined_function_local_payload_resolves_normally() -> None:
    """Function-local logical types work when defined before the table model."""

    class Payload(BaseModel):
        """Logical payload type defined before its table model."""

        value: str

    class Mixed[S = Pending](Model[S, "Mixed[Fetched]"]):
        """Optional scalar beside an already-defined local payload."""

        optional: Mixed.Col[int | None] = Integer(default=None)
        payload: Mixed.Col[Payload] = Text()

    assert_is(Mixed.optional.nullable, True)
    mixed = Mixed(payload=Payload(value="ready"))
    assert_eq(mixed.payload, Payload(value="ready"))

    class Reading[S = Pending](Model[S, "Reading[Fetched]"]):
        """Table model with a real column."""

        value: Reading.Col[float] = Real(nullable=False)

    reading = Reading(value=cast("float", 1))

    assert_eq(reading.value, 1.0)
    assert_isinstance(reading.value, float)


@test(mark="fast")
def require_model_columns_rejects_non_model_classes() -> None:
    """Column metadata access fails as a declaration error off table models."""

    class NotAModel:
        """Plain class without snekql column metadata."""

    with assert_raises(ModelDeclarationError) as missing_error:
        _ = require_model_columns(NotAModel)
    assert_eq(str(missing_error.exception), "schema setup requires snekql table models")

    class FakeColumns:
        """Plain class whose ``__snekql_columns__`` is not column metadata."""

        __snekql_columns__ = "not a mapping"

    with assert_raises(ModelDeclarationError) as shape_error:
        _ = require_model_columns(FakeColumns)
    assert_eq(str(shape_error.exception), "schema setup requires snekql table models")

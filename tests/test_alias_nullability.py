"""Field nullability follows named aliases without replacing logical annotations."""

from __future__ import annotations

from typing import Annotated

from pydantic import BeforeValidator, Field, Json
from snektest import assert_eq, assert_raises, test

from snekql import sqlite
from snekql.errors import ModelDeclarationError, ModelValidationError

type OptionalInteger = int | None


@test(mark="fast")
def optional_alias_accepts_none_default() -> None:
    """A named optional integer behaves like the expanded union."""

    class Entry[S = sqlite.Pending](sqlite.Model[S, "Entry[sqlite.Fetched]"]):
        """A None default must agree with inferred nullable storage."""

        value: Entry.Col[OptionalInteger] = sqlite.Integer(default=None)

    assert_eq(Entry().value, None)


type IntegerAlias = int
type ChainedOptional = OptionalInteger
type Maybe[T] = T | None
type Identity[T] = T
type DefaultOptional[T = int | None] = T
type OptionalItems = list[int | None]
type RecursiveItems = list[RecursiveItems]
# Deliberately cyclic/unresolved declarations exercise the unknown policy.
type Cycle = Cycle  # ty: ignore[cyclic-type-alias-definition]
type Unresolved = NotDeclared  # noqa: F821  # ty: ignore[unresolved-reference]


@test(mark="fast")
def optional_alias_forms_accept_matching_flags() -> None:
    """Chaining, wrappers and specialization retain field-level None membership."""

    class Entry[S = sqlite.Pending](sqlite.Model[S, "Entry[sqlite.Fetched]"]):
        """Each spelling promises the same nullable field contract."""

        chained: Entry.Col[ChainedOptional] = sqlite.Integer(
            nullable=True, default=None
        )
        wrapped: Entry.Col[Annotated[OptionalInteger, Field(ge=0)]] = sqlite.Integer(
            default=None
        )
        generic: Entry.Col[Maybe[int]] = sqlite.Integer(default=None)
        forwarded: Entry.Col[Identity[int | None]] = sqlite.Integer(default=None)
        nested: Entry.Col[Identity[Identity[int | None]]] = sqlite.Integer(default=None)
        defaulted: Entry.Col[DefaultOptional] = sqlite.Integer(default=None)

    row = Entry()

    assert_eq(
        (
            row.chained,
            row.wrapped,
            row.generic,
            row.forwarded,
            row.nested,
            row.defaulted,
        ),
        (None,) * 6,
    )


@test(mark="fast")
def nonoptional_aliases_remain_not_null() -> None:
    """Specialized aliases do not infer nullability from arbitrary arguments."""

    class Entry[S = sqlite.Pending](sqlite.Model[S, "Entry[sqlite.Fetched]"]):
        """Nonnullable aliases and containers keep NOT NULL storage."""

        plain: Entry.Col[IntegerAlias] = sqlite.Integer(nullable=False)
        generic: Entry.Col[Identity[int]] = sqlite.Integer(nullable=False)
        items: Entry.Col[Json[OptionalItems]] = sqlite.Text(nullable=False)
        recursive: Entry.Col[Json[RecursiveItems]] = sqlite.Text(nullable=False)
        only_null_items: Entry.Col[Json[list[None]]] = sqlite.Text(nullable=False)

    assert_eq(
        (
            Entry.plain.nullable,
            Entry.generic.nullable,
            Entry.items.nullable,
            Entry.recursive.nullable,
            Entry.only_null_items.nullable,
        ),
        (False,) * 5,
    )


@test(mark="fast")
def optional_alias_rejects_not_null_flag() -> None:
    """An alias does not bypass explicit nullable=False cross-checking."""

    with assert_raises(ModelDeclarationError):

        class Entry[S = sqlite.Pending](sqlite.Model[S, "Entry[sqlite.Fetched]"]):
            """A contradictory assertion must fail before schema creation."""

            value: Entry.Col[OptionalInteger] = sqlite.Integer(nullable=False)


@test(mark="fast")
def nonoptional_alias_rejects_nullable_flag() -> None:
    """An int specialization cannot claim nullable storage."""

    with assert_raises(ModelDeclarationError):

        class Entry[S = sqlite.Pending](sqlite.Model[S, "Entry[sqlite.Fetched]"]):
            """A generic alias must use its actual argument."""

            value: Entry.Col[Identity[int]] = sqlite.Integer(nullable=True)


@test(mark="fast")
def cyclic_alias_requires_explicit_nullability() -> None:
    """A field-level alias cycle is unknown, not silently NOT NULL."""

    with assert_raises(ModelDeclarationError) as error:

        class Entry[S = sqlite.Pending](sqlite.Model[S, "Entry[sqlite.Fetched]"]):
            """Cycles terminate under the existing unresolved-field policy."""

            value: Entry.Col[Cycle] = sqlite.Integer()

    assert_eq(
        str(error.exception),
        "column 'value' annotation cannot be resolved; declare nullable=True or nullable=False explicitly",
    )


@test(mark="fast")
def unresolved_alias_requires_explicit_nullability() -> None:
    """Lazy alias evaluation can fail without turning unknown into False."""

    with assert_raises(ModelDeclarationError) as error:

        class Entry[S = sqlite.Pending](sqlite.Model[S, "Entry[sqlite.Fetched]"]):
            """Undefined alias targets need an explicit flag."""

            value: Entry.Col[Unresolved] = sqlite.Integer()

    assert_eq(
        str(error.exception),
        "column 'value' annotation cannot be resolved; declare nullable=True or nullable=False explicitly",
    )


@test(mark="fast")
def deferred_alias_retains_explicit_nullability() -> None:
    """An explicit flag permits a forward alias to resolve before value use."""

    type Late = Later

    class Entry[S = sqlite.Pending](sqlite.Model[S, "Entry[sqlite.Fetched]"]):
        """Annotation resolution may legitimately wait for its declaring scope."""

        value: Entry.Col[Late] = sqlite.Integer(nullable=True)

    type Later = int | None

    assert_eq(Entry(value=7).value, 7)


@test(mark="fast")
def alias_inspection_does_not_call_validators() -> None:
    """Metadata stays with Pydantic; None is never synthesized for a probe."""

    calls: list[object] = []

    def observe(value: object) -> object:
        """Record real validation, never annotation inspection."""
        calls.append(value)
        return value

    type Validated = Annotated[int | None, BeforeValidator(observe), Field(ge=0)]

    class Entry[S = sqlite.Pending](sqlite.Model[S, "Entry[sqlite.Fetched]"]):
        """The logical alias still owns its validators."""

        value: Entry.Col[Validated] = sqlite.Integer(default=None)

    assert_eq(calls, [])
    with assert_raises(ModelValidationError):
        Entry(value=-1)
    assert_eq(calls, [-1])


# Unresolved type-parameter defaults are lazy too.
type UnresolvedDefault[T = NotDeclared] = T  # noqa: F821  # ty: ignore[unresolved-reference]
type Growing[T] = Growing[list[T]]  # ty: ignore[cyclic-type-alias-definition]
type First[T, U] = T
type Reordered[T, U] = First[U, T]


@test(mark="fast")
def unresolved_alias_default_requires_explicit_nullability() -> None:
    """Lazy parameter-default errors follow the same unknown policy as alias values."""

    with assert_raises(ModelDeclarationError):

        class Entry[S = sqlite.Pending](sqlite.Model[S, "Entry[sqlite.Fetched]"]):
            """Missing generic defaults must not leak raw NameError."""

            value: Entry.Col[UnresolvedDefault] = sqlite.Integer()


@test(mark="fast")
def recursive_generic_alias_terminates() -> None:
    """Growing recursive arguments do not evade the cycle guard."""

    with assert_raises(ModelDeclarationError):

        class Entry[S = sqlite.Pending](sqlite.Model[S, "Entry[sqlite.Fetched]"]):
            """Unknown nullability requires an explicit assertion."""

            value: Entry.Col[Growing[int]] = sqlite.Integer()


@test(mark="fast")
def generic_argument_order_controls_nullability() -> None:
    """Nested aliases retain their caller's bindings instead of guessing from args."""

    class Entry[S = sqlite.Pending](sqlite.Model[S, "Entry[sqlite.Fetched]"]):
        """The same alias can specialize to opposite nullability contracts."""

        optional: Entry.Col[Reordered[int, int | None]] = sqlite.Integer(default=None)
        required: Entry.Col[Reordered[int | None, int]] = sqlite.Integer(nullable=False)

    assert_eq((Entry.optional.nullable, Entry.required.nullable), (True, False))


@test(mark="fast")
def optional_alias_cannot_be_primary_key() -> None:
    """Alias expansion must preserve the prohibition on nullable primary keys."""

    with assert_raises(ModelDeclarationError):

        class Entry[S = sqlite.Pending](sqlite.Model[S, "Entry[sqlite.Fetched]"]):
            """A primary key cannot admit None through an alias."""

            value: Entry.Col[OptionalInteger] = sqlite.Integer(primary_key=True)

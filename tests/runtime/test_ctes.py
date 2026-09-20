"""Named CTE consumption through real transactions."""

from collections.abc import AsyncGenerator
from typing import assert_type
from uuid import UUID

from pydantic import BaseModel, field_validator
from snektest import assert_eq, fixture, load_fixture, test

from snekql import mariadb, sqlite
from tests.query.test_ctes import ActiveRole, FilteredRole, Identifier, Person
from tests.runtime.test_arithmetic import MariaInventory, provide_mariadb_inventory
from tests.runtime.test_named_codecs import (
    DocumentResult,
    LocalDocument,
    MariaDocument,
    provide_mariadb_documents,
    provide_sqlite_documents,
)


@fixture
async def provide_cte_people() -> AsyncGenerator[sqlite.Database]:
    """Seed one physical source for query-only definitions."""
    async with await sqlite.Database.initialize(database=":memory:") as database:
        await database.migrate({"001_people": sqlite.scaffold([Person])})
        async with database.transaction() as transaction:
            await transaction.execute(sqlite.insert(Person(id=1)))
        yield database


@test(mark="medium")
async def cte_whole_row_materializes_its_named_contract() -> None:
    """The consumer yields a Pydantic result, not a synthetic Table Model."""
    database = await load_fixture(provide_cte_people())
    identifier = Person.id.label("id")
    active = (
        sqlite.select(Person)
        .all()
        .project(Identifier, id=identifier)
        .cte(ActiveRole, name="active")
    )

    async with database.transaction() as transaction:
        row = await transaction.fetch_one(sqlite.select(active).all())

    assert_type(row, Identifier)
    assert_eq(row, Identifier(id=1))


@test(mark="medium")
async def cte_whole_row_validates_only_the_final_result() -> None:
    """Crossing the definition boundary does not run Python result validators."""
    database = await load_fixture(provide_cte_people())

    class Adjusted(BaseModel):
        id: int

        @field_validator("id")
        @classmethod
        def increment(cls, value: int) -> int:
            return value + 10

    active = (
        sqlite.select(Person)
        .all()
        .project(Adjusted, id=Person.id.label("id"))
        .cte(ActiveRole, name="active")
    )

    async with database.transaction() as transaction:
        row = await transaction.fetch_one(sqlite.select(active).all())

    assert_type(row, Adjusted)
    assert_eq(row.id, 11)


@test(mark="medium")
async def cte_column_comparison_preserves_uuid_encoding() -> None:
    """An output predicate binds the source's wire value, not a raw UUID object."""
    database = await load_fixture(provide_sqlite_documents())
    key = LocalDocument.id.label("key")
    documents = (
        sqlite.select(LocalDocument)
        .all()
        .project(DocumentResult, key=key, values=LocalDocument.payload)
        .cte(ActiveRole, name="documents")
    )
    query = sqlite.select(documents).where(documents.column(key).eq(UUID(int=1)))

    async with database.transaction() as transaction:
        row = await transaction.fetch_one(query)

    assert_type(row, DocumentResult)
    assert_eq(row, DocumentResult(key=UUID(int=1), values=[2, 3]))


@test(mark="medium")
async def cte_column_selection_has_the_source_value_type() -> None:
    """A typed output reference is a scalar projection, not a result model."""
    database = await load_fixture(provide_cte_people())
    identifier = Person.id.label("id")
    active = (
        sqlite.select(Person)
        .all()
        .project(Identifier, id=identifier)
        .cte(ActiveRole, name="active")
    )

    async with database.transaction() as transaction:
        values = await transaction.fetch_all(
            sqlite.select(active.column(identifier)).all()
        )

    assert_type(values, list[int])
    assert_eq(values, [1])


@test(mark="slow")
async def mariadb_cte_preserves_native_uuid_and_json_codecs() -> None:
    """Native definition outputs retain comparison encoding and logical decoding."""
    database = await load_fixture(provide_mariadb_documents())
    key = MariaDocument.id.label("key")
    documents = (
        mariadb.select(MariaDocument)
        .all()
        .project(DocumentResult, key=key, values=MariaDocument.payload)
        .cte(ActiveRole, name="documents")
    )
    query = mariadb.select(documents).where(documents.column(key).eq(UUID(int=1)))

    async with database.transaction() as transaction:
        row = await transaction.fetch_one(query)

    assert_type(row, DocumentResult)
    assert_eq(row, DocumentResult(key=UUID(int=1), values=[2, 3]))


@test(mark="medium")
async def cte_scalar_preserves_disabled_column_validation() -> None:
    """The explicit raw-value escape hatch still reaches the original codec."""
    database = await load_fixture(provide_sqlite_documents())
    key = LocalDocument.id.label("key")
    documents = (
        sqlite.select(LocalDocument)
        .all()
        .project(DocumentResult, key=key, values=LocalDocument.payload)
        .cte(ActiveRole, name="documents")
    )

    async with database.transaction() as transaction:
        wire_value = await transaction.fetch_one(
            sqlite.select(documents.column(key)).all(), validate=False
        )

    assert_eq(wire_value, str(UUID(int=1)))


@test(mark="medium")
async def left_join_definition_retains_nullable_output_columns() -> None:
    """Missing definition-local rows stay NULL across the named SQL boundary."""
    database = await load_fixture(provide_cte_people())

    class PeerRole:
        pass

    class Pair(BaseModel):
        id: int
        other: int | None

    peer = sqlite.alias(Person, PeerRole, name="peer")
    identifier = Person.id.label("id")
    other = peer.column(Person.id).label("other")
    definition = (
        sqlite.select(Person)
        .left_join(
            peer,
            on=Person.id.eq_col(peer.column(Person.id)) & peer.column(Person.id).eq(-1),
        )
        .project(Pair, id=identifier, other=other)
        .all()
        .cte(ActiveRole, name="pairs")
    )

    async with database.transaction() as transaction:
        row = await transaction.fetch_one(sqlite.select(definition).all())
        values = await transaction.fetch_all(
            sqlite.select(definition.column(other)).all()
        )

    assert_type(row, Pair)
    assert_type(values, list[int | None])
    assert_eq(row, Pair(id=1, other=None))
    assert_eq(values, [None])


@test(mark="slow")
async def mariadb_joined_definition_preserves_nullable_computation() -> None:
    """Native NULL extension survives a computed, labeled CTE output."""
    database = await load_fixture(provide_mariadb_inventory())

    class PeerRole:
        pass

    class OptionalValue(BaseModel):
        value: int | None

    peer = mariadb.alias(MariaInventory, PeerRole, name="peer")
    value = peer.column(MariaInventory.quantity).add(1).label("value")
    definition = (
        mariadb.select(MariaInventory)
        .left_join(
            peer,
            on=MariaInventory.id.eq_col(peer.column(MariaInventory.id))
            & peer.column(MariaInventory.id).eq(-1),
        )
        .all()
        .project(OptionalValue, value=value)
        .cte(ActiveRole, name="quantities")
    )

    async with database.transaction() as transaction:
        values = await transaction.fetch_all(
            mariadb.select(definition.column(value)).all()
        )

    assert_type(values, list[int | None])
    assert_eq(values, [None])


@test(mark="medium")
async def nullable_owner_count_remains_nonnullable_through_a_definition() -> None:
    """COUNT of an absent joined owner is zero rather than a null-extended column."""
    database = await load_fixture(provide_cte_people())

    class PeerRole:
        pass

    peer = sqlite.alias(Person, PeerRole, name="peer")
    count = peer.column(Person.id).count().label("id")
    definition = (
        sqlite.select(Person)
        .left_join(
            peer,
            on=Person.id.eq_col(peer.column(Person.id)) & peer.column(Person.id).eq(-1),
        )
        .all()
        .project(Identifier, id=count)
        .cte(ActiveRole, name="counts")
    )

    async with database.transaction() as transaction:
        value = await transaction.fetch_one(
            sqlite.select(definition.column(count)).all()
        )

    assert_type(value, int)
    assert_eq(value, 0)


@test(mark="medium")
async def cte_alias_preserves_sqlite_logical_codecs() -> None:
    """A reference rename changes neither the UUID encoder nor JSON decoder."""
    database = await load_fixture(provide_sqlite_documents())
    key = LocalDocument.id.label("key")
    documents = (
        sqlite.select(LocalDocument)
        .all()
        .project(DocumentResult, key=key, values=LocalDocument.payload)
        .cte(ActiveRole, name="documents")
    )
    peer = sqlite.alias(documents, FilteredRole, name="peer")

    async with database.transaction() as transaction:
        row = await transaction.fetch_one(
            sqlite.select(peer).where(peer.column(key).eq(UUID(int=1)))
        )

    assert_type(row, DocumentResult)
    assert_eq(row, DocumentResult(key=UUID(int=1), values=[2, 3]))


@test(mark="slow")
async def cte_alias_preserves_mariadb_logical_codecs() -> None:
    """Native comparison bindings and materialization still use the definition."""
    database = await load_fixture(provide_mariadb_documents())
    key = MariaDocument.id.label("key")
    documents = (
        mariadb.select(MariaDocument)
        .all()
        .project(DocumentResult, key=key, values=MariaDocument.payload)
        .cte(ActiveRole, name="documents")
    )
    peer = mariadb.alias(documents, FilteredRole, name="peer")

    async with database.transaction() as transaction:
        row = await transaction.fetch_one(
            mariadb.select(peer).where(peer.column(key).eq(UUID(int=1)))
        )

    assert_type(row, DocumentResult)
    assert_eq(row, DocumentResult(key=UUID(int=1), values=[2, 3]))

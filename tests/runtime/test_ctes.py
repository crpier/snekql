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


@test(mark="medium")
async def inner_join_consumes_a_cte_as_a_named_row() -> None:
    """A query-only source appends its named result rather than a schema model."""
    database = await load_fixture(provide_cte_people())
    identifier = Person.id.label("id")
    active = (
        sqlite.select(Person)
        .all()
        .project(Identifier, id=identifier)
        .cte(ActiveRole, name="active")
    )
    query = (
        sqlite.select(Person)
        .join(active, on=Person.id.eq_col(active.column(identifier)))
        .all()
    )

    async with database.transaction() as transaction:
        rows = await transaction.fetch_all(query)

    assert_type(rows, list[tuple[Person[sqlite.Fetched], Identifier]])
    assert_eq(len(rows), 1)
    assert_eq(rows[0][0].id, 1)
    assert_eq(rows[0][1], Identifier(id=1))


@test(mark="medium")
async def inner_join_reuses_one_definition_for_two_named_rows() -> None:
    """Each role materializes its own named result while sharing definition SQL."""
    database = await load_fixture(provide_cte_people())
    identifier = Person.id.label("id")
    active = (
        sqlite.select(Person)
        .all()
        .project(Identifier, id=identifier)
        .cte(ActiveRole, name="active")
    )
    peer = sqlite.alias(active, FilteredRole, name="peer")
    query = (
        sqlite.select(active)
        .join(peer, on=active.column(identifier).eq_col(peer.column(identifier)))
        .all()
    )

    async with database.transaction() as transaction:
        rows = await transaction.fetch_all(query)

    assert_type(rows, list[tuple[Identifier, Identifier]])
    assert_eq(rows, [(Identifier(id=1), Identifier(id=1))])
    assert_eq(query.compile().sql.count('"active" AS ('), 1)


@test(mark="slow")
async def native_inner_join_materializes_a_cte_alias() -> None:
    """Native query-only joined rows retain UUID/JSON decoding and result shape."""
    database = await load_fixture(provide_mariadb_documents())
    key = MariaDocument.id.label("key")
    documents = (
        mariadb.select(MariaDocument)
        .all()
        .project(DocumentResult, key=key, values=MariaDocument.payload)
        .cte(ActiveRole, name="documents")
    )
    peer = mariadb.alias(documents, FilteredRole, name="peer")
    query = (
        mariadb.select(MariaDocument)
        .join(peer, on=MariaDocument.id.eq_col(peer.column(key)))
        .all()
    )

    async with database.transaction() as transaction:
        rows = await transaction.fetch_all(query)

    assert_type(rows, list[tuple[MariaDocument[mariadb.Fetched], DocumentResult]])
    assert_eq(len(rows), 1)
    assert_eq(rows[0][0].id, UUID(int=1))
    assert_eq(rows[0][1], DocumentResult(key=UUID(int=1), values=[2, 3]))


@test(mark="medium")
async def left_join_distinguishes_a_matched_all_null_cte_row() -> None:
    """NULL visible outputs do not mean a query-only row was absent."""
    database = await load_fixture(provide_cte_people())

    class OptionalIdentifier(BaseModel):
        id: int | None

    identifier = sqlite.scalar(sqlite.select(Person.id).where(Person.id.eq(-1))).label(
        "id"
    )
    nullable = (
        sqlite.select(Person)
        .all()
        .project(OptionalIdentifier, id=identifier)
        .cte(ActiveRole, name="nullable_rows")
    )
    query = sqlite.select(Person).left_join(nullable, on=Person.id.gt(0)).all()

    async with database.transaction() as transaction:
        rows = await transaction.fetch_all(query)

    assert_type(rows, list[tuple[Person[sqlite.Fetched], OptionalIdentifier | None]])
    assert_eq(len(rows), 1)
    assert_eq(rows[0][1], OptionalIdentifier(id=None))


@test(mark="slow")
async def native_left_alias_distinguishes_null_output_from_missing_row() -> None:
    """Private presence survives aliasing and is NULL only for an absent match."""
    database = await load_fixture(provide_mariadb_documents())

    class OptionalKey(BaseModel):
        id: UUID | None

    key = mariadb.scalar(
        mariadb.select(MariaDocument.id).where(MariaDocument.id.eq(UUID(int=0)))
    ).label("id")
    nullable = (
        mariadb.select(MariaDocument)
        .all()
        .project(OptionalKey, id=key)
        .cte(ActiveRole, name="nullable_rows")
    )
    peer = mariadb.alias(nullable, FilteredRole, name="peer")
    matched = (
        mariadb.select(MariaDocument)
        .left_join(peer, on=MariaDocument.id.eq(UUID(int=1)))
        .all()
    )
    missing = (
        mariadb.select(MariaDocument)
        .left_join(peer, on=MariaDocument.id.eq(UUID(int=2)))
        .all()
    )

    async with database.transaction() as transaction:
        present = await transaction.fetch_one(matched)
        absent = await transaction.fetch_one(missing)

    assert_type(present, tuple[MariaDocument[mariadb.Fetched], OptionalKey | None])
    assert_eq(present[1], OptionalKey(id=None))
    assert_eq(absent[1], None)


@test(mark="medium")
async def cte_output_count_counts_nonnull_values() -> None:
    """Readonly COUNT uses the derived output rather than its defining expression."""
    database = await load_fixture(provide_cte_people())
    identifier = Person.id.label("id")
    active = (
        sqlite.select(Person)
        .all()
        .project(Identifier, id=identifier)
        .cte(ActiveRole, name="active")
    )

    async with database.transaction() as transaction:
        count = await transaction.fetch_one(
            sqlite.select(active.column(identifier).count()).all()
        )

    assert_type(count, int)
    assert_eq(count, 1)


@test(mark="slow")
async def native_cte_alias_count_supports_having_and_empty_inputs() -> None:
    """COUNT over a UUID output is an integer, including an empty consumer."""
    database = await load_fixture(provide_mariadb_documents())
    key = MariaDocument.id.label("key")
    documents = (
        mariadb.select(MariaDocument)
        .all()
        .project(DocumentResult, key=key, values=MariaDocument.payload)
        .cte(ActiveRole, name="documents")
    )
    peer = mariadb.alias(documents, FilteredRole, name="peer")
    count = peer.column(key).count()

    async with database.transaction() as transaction:
        present = await transaction.fetch_one(
            mariadb.select(count).all().having(count.gt(0)).order_by(count.desc())
        )
        empty = await transaction.fetch_one(
            mariadb.select(count).where(peer.column(key).eq(UUID(int=0)))
        )

    assert_type(present, int)
    assert_type(empty, int)
    assert_eq(present, 1)
    assert_eq(empty, 0)


@test(mark="medium")
async def cte_output_count_ignores_matched_null_values() -> None:
    """The private presence column must not turn COUNT(output) into COUNT(*)."""
    database = await load_fixture(provide_cte_people())

    class OptionalIdentifier(BaseModel):
        id: int | None

    identifier = sqlite.scalar(sqlite.select(Person.id).where(Person.id.eq(-1))).label(
        "id"
    )
    nullable = (
        sqlite.select(Person)
        .all()
        .project(OptionalIdentifier, id=identifier)
        .cte(ActiveRole, name="nullable_rows")
    )

    async with database.transaction() as transaction:
        count = await transaction.fetch_one(
            sqlite.select(nullable.column(identifier).count()).all()
        )

    assert_type(count, int)
    assert_eq(count, 0)


@test(mark="medium")
async def cte_count_can_be_labeled_into_a_downstream_definition() -> None:
    """An aggregate over an output retains the stable integer result contract."""
    database = await load_fixture(provide_cte_people())
    identifier = Person.id.label("id")
    active = (
        sqlite.select(Person)
        .all()
        .project(Identifier, id=identifier)
        .cte(ActiveRole, name="active")
    )
    count = active.column(identifier).count().label("id")
    counted = (
        sqlite.select(active)
        .all()
        .project(Identifier, id=count)
        .cte(FilteredRole, name="counted")
    )

    async with database.transaction() as transaction:
        result = await transaction.fetch_one(sqlite.select(counted.column(count)).all())

    assert_type(result, int)
    assert_eq(result, 1)


@test(mark="medium")
async def cte_output_groups_and_filters_its_derived_values() -> None:
    """Grouping keys use the derived source, including freshly retrieved tokens."""
    database = await load_fixture(provide_cte_people())
    identifier = Person.id.label("id")
    active = (
        sqlite.select(Person)
        .all()
        .project(Identifier, id=identifier)
        .cte(ActiveRole, name="active")
    )
    column = active.column(identifier)
    query = (
        sqlite.select(column, column.count())
        .all()
        .group_by(active.column(identifier))
        .having(column.gt(0))
    )

    async with database.transaction() as transaction:
        rows = await transaction.fetch_all(query)

    assert_type(rows, list[tuple[int, int]])
    assert_eq(rows, [(1, 1)])


@test(mark="slow")
async def native_cte_alias_grouping_preserves_uuid_named_results() -> None:
    """Named grouped queries use readonly keys and preserve native decoding."""
    database = await load_fixture(provide_mariadb_documents())

    class GroupResult(BaseModel):
        key: UUID
        count: int

    key = MariaDocument.id.label("key")
    documents = (
        mariadb.select(MariaDocument)
        .all()
        .project(DocumentResult, key=key, values=MariaDocument.payload)
        .cte(ActiveRole, name="documents")
    )
    peer = mariadb.alias(documents, FilteredRole, name="peer")
    column = peer.column(key)
    count = column.count()
    query = (
        mariadb.select(peer)
        .all()
        .project(GroupResult, key=column, count=count)
        .group_by(peer.column(key))
        .having(count.gt(0))
    )

    async with database.transaction() as transaction:
        rows = await transaction.fetch_all(query)

    assert_type(rows, list[GroupResult])
    assert_eq(rows, [GroupResult(key=UUID(int=1), count=1)])

"""Named projection results through transaction fetches."""

from collections.abc import AsyncGenerator
from typing import Annotated, ClassVar, Literal, Self, assert_type

from annotated_types import MaxLen
from pydantic import BaseModel, model_validator
from snektest import assert_eq, assert_raises, fixture, load_fixture, test

from snekql import mariadb, sqlite
from tests.helpers import provide_mariadb_server
from tests.query.test_named_projection import (
    OptionalPersonSummary,
    PeerRole,
    Person,
    PersonSummary,
    WidePerson,
)


@fixture
async def provide_people() -> AsyncGenerator[sqlite.Database]:
    """Seed a row for named result materialization."""
    async with await sqlite.Database.initialize(database=":memory:") as database:
        await database.migrate({"001_people": sqlite.scaffold([Person])})
        async with database.transaction() as transaction:
            await transaction.execute(sqlite.insert(Person(id=1, name="Ada")))
        yield database


@test(mark="medium")
async def named_projection_materializes_declared_result() -> None:
    """Binding order does not change which named field receives a value."""
    database = await load_fixture(provide_people())
    query = (
        sqlite.select(Person)
        .project(PersonSummary, name=Person.name, id=Person.id)
        .all()
    )

    async with database.transaction() as transaction:
        rows = await transaction.fetch_all(query)

    assert_type(rows, list[PersonSummary])
    assert_eq(rows, [PersonSummary(id=1, name="Ada")])


@test(mark="medium")
async def named_projection_preserves_unmatched_alias_null() -> None:
    """A projected alias column may be absent despite non-null physical storage."""
    database = await load_fixture(provide_people())
    peer = sqlite.alias(Person, PeerRole, name="peer")
    query = (
        sqlite.select(Person)
        .left_join(
            peer,
            on=Person.id.eq_col(peer.column(Person.id)) & peer.column(Person.id).eq(2),
        )
        .project(OptionalPersonSummary, id=Person.id, name=peer.column(Person.name))
        .all()
    )

    async with database.transaction() as transaction:
        rows = await transaction.fetch_all(query)

    assert_type(rows, list[OptionalPersonSummary])
    assert_eq(rows, [OptionalPersonSummary(id=1, name=None)])


@test(mark="medium")
async def named_projection_fetches_more_than_eight_values() -> None:
    """Wide named rows do not depend on positional overload generation."""
    database = await load_fixture(provide_people())
    query = (
        sqlite.select(Person)
        .project(
            WidePerson,
            first=Person.id,
            second=Person.id,
            third=Person.id,
            fourth=Person.id,
            fifth=Person.id,
            sixth=Person.id,
            seventh=Person.id,
            eighth=Person.id,
            ninth=Person.id,
        )
        .all()
    )

    async with database.transaction() as transaction:
        row = await transaction.fetch_one(query)

    assert_type(row, WidePerson)
    assert_eq(
        row,
        WidePerson(
            first=1,
            second=1,
            third=1,
            fourth=1,
            fifth=1,
            sixth=1,
            seventh=1,
            eighth=1,
            ninth=1,
        ),
    )


@test(mark="medium")
async def named_result_constraints_survive_disabled_column_validation() -> None:
    """Disabling source validators does not waive the named result contract."""
    database = await load_fixture(provide_people())

    class ShortName(BaseModel):
        name: Annotated[str, MaxLen(2)]

    query = sqlite.select(Person).project(ShortName, name=Person.name).all()

    async with database.transaction() as transaction:
        with assert_raises(sqlite.ModelValidationError):
            await transaction.fetch_all(query, validate=False)


class MariaPerson[S = mariadb.Pending](mariadb.Model[S]):
    """The same logical input schema on MariaDB."""

    __row_type__: ClassVar[mariadb.ReadType[MariaPerson[mariadb.Row]]]

    id: MariaPerson.Col[int] = mariadb.Integer(primary_key=True)
    name: MariaPerson.Col[str] = mariadb.Text()


@fixture
async def provide_maria_people() -> AsyncGenerator[mariadb.Database]:
    """Seed a real MariaDB table for named result materialization."""
    server = await load_fixture(provide_mariadb_server())
    async with await mariadb.Database.initialize(server.config()) as database:
        await database.migrate({"001_people": mariadb.scaffold([MariaPerson])})
        async with database.transaction() as transaction:
            await transaction.execute(mariadb.insert(MariaPerson(id=1, name="Ada")))
        yield database


@test(mark="slow")
async def mariadb_named_projection_fetches_more_than_eight_values() -> None:
    """Wide named rows do not depend on positional overload generation."""
    database = await load_fixture(provide_maria_people())
    query = (
        mariadb.select(MariaPerson)
        .project(
            WidePerson,
            first=MariaPerson.id,
            second=MariaPerson.id,
            third=MariaPerson.id,
            fourth=MariaPerson.id,
            fifth=MariaPerson.id,
            sixth=MariaPerson.id,
            seventh=MariaPerson.id,
            eighth=MariaPerson.id,
            ninth=MariaPerson.id,
        )
        .all()
    )

    async with database.transaction() as transaction:
        row = await transaction.fetch_one(query)

    assert_type(row, WidePerson)
    assert_eq(
        row,
        WidePerson(
            first=1,
            second=1,
            third=1,
            fourth=1,
            fifth=1,
            sixth=1,
            seventh=1,
            eighth=1,
            ninth=1,
        ),
    )


@test(mark="slow")
async def mariadb_named_projection_preserves_unmatched_alias_null() -> None:
    """A projected alias column may be absent despite non-null physical storage."""
    database = await load_fixture(provide_maria_people())
    peer = mariadb.alias(MariaPerson, PeerRole, name="peer")
    query = (
        mariadb.select(MariaPerson)
        .left_join(
            peer,
            on=MariaPerson.id.eq_col(peer.column(MariaPerson.id))
            & peer.column(MariaPerson.id).eq(2),
        )
        .project(
            OptionalPersonSummary, id=MariaPerson.id, name=peer.column(MariaPerson.name)
        )
        .all()
    )

    async with database.transaction() as transaction:
        rows = await transaction.fetch_all(query)

    assert_type(rows, list[OptionalPersonSummary])
    assert_eq(rows, [OptionalPersonSummary(id=1, name=None)])


@test(mark="medium")
async def named_literal_contract_checks_values_after_decoding() -> None:
    """Literal is a value constraint, not an incompatible storage domain."""
    database = await load_fixture(provide_people())

    class AdaOnly(BaseModel):
        name: Literal["Ada"]

    query = sqlite.select(Person).project(AdaOnly, name=Person.name).all()

    async with database.transaction() as transaction:
        row = await transaction.fetch_one(query)

    assert_eq(row, AdaOnly(name="Ada"))


@test(mark="medium")
async def named_scalar_projection_preserves_empty_subquery_null() -> None:
    """An empty scalar SELECT produces None inside the named row contract."""
    database = await load_fixture(provide_people())

    class OptionalId(BaseModel):
        value: int | None

    query = (
        sqlite.select(Person)
        .project(
            OptionalId,
            value=sqlite.scalar(sqlite.select(Person.id).where(Person.id.eq(2))),
        )
        .all()
    )

    async with database.transaction() as transaction:
        row = await transaction.fetch_one(query)

    assert_eq(row, OptionalId(value=None))


@test(mark="medium")
async def named_grouped_projection_supports_having() -> None:
    """Named results preserve aggregate grouping and row-scope readiness."""
    database = await load_fixture(provide_people())

    class NameCount(BaseModel):
        name: str
        count: int

    query = (
        sqlite.select(Person)
        .project(NameCount, name=Person.name, count=Person.id.count())
        .group_by(Person.name)
        .having(Person.id.count().gt(0))
        .all()
    )

    async with database.transaction() as transaction:
        rows = await transaction.fetch_all(query)

    assert_eq(rows, [NameCount(name="Ada", count=1)])


@test(mark="medium")
async def named_result_rejects_validator_replacement() -> None:
    """A custom validator must not replace a promised row object with None."""
    database = await load_fixture(provide_people())

    class Discarded(BaseModel):
        id: int

        @model_validator(mode="after")
        def discard(self) -> Self:
            return None  # ty: ignore[invalid-return-type]

    query = sqlite.select(Person).project(Discarded, id=Person.id).all()

    async with database.transaction() as transaction:
        with assert_raises(sqlite.ModelValidationError):
            await transaction.fetch_all(query)


@test(mark="medium")
async def named_chunks_materialize_contract_instances() -> None:
    """Streaming uses the same named result validation as eager fetches."""
    database = await load_fixture(provide_people())
    query = (
        sqlite.select(Person)
        .project(PersonSummary, id=Person.id, name=Person.name)
        .all()
    )

    async with (
        database.transaction() as transaction,
        transaction.fetch_chunks(query, size=1) as stream,
    ):
        rows = [row async for chunk in stream for row in chunk]

    assert_type(rows, list[PersonSummary])
    assert_eq(rows, [PersonSummary(id=1, name="Ada")])


@test(mark="medium")
async def optional_fetch_distinguishes_named_null_field_from_no_row() -> None:
    """A present object containing None is distinct from the absence of a row."""
    database = await load_fixture(provide_people())

    class MaybeName(BaseModel):
        name: str | None

    peer = sqlite.alias(Person, PeerRole, name="peer")
    query = (
        sqlite.select(Person)
        .left_join(peer, on=peer.column(Person.id).eq(2))
        .project(MaybeName, name=peer.column(Person.name))
        .all()
    )

    async with database.transaction() as transaction:
        row = await transaction.fetch_one_or_none(query)

    assert_type(row, MaybeName | None)
    assert_eq(row, MaybeName(name=None))


@test(mark="medium")
async def named_optional_fetch_returns_none_for_no_row() -> None:
    """An absent row retains the existing optional-fetch cardinality contract."""
    database = await load_fixture(provide_people())
    query = (
        sqlite.select(Person)
        .where(Person.id.eq(2))
        .project(PersonSummary, id=Person.id, name=Person.name)
    )

    async with database.transaction() as transaction:
        row = await transaction.fetch_one_or_none(query)

    assert_type(row, PersonSummary | None)
    assert_eq(row, None)

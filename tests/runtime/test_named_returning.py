"""Named write results through real backend transactions."""

from typing import assert_type

from snektest import assert_eq, load_fixture, test

from snekql import mariadb, sqlite
from tests.query.test_named_projection import Person, PersonSummary, WidePerson
from tests.runtime.test_named_projection import (
    MariaPerson,
    provide_maria_people,
    provide_people,
)


@test(mark="medium")
async def named_insert_returns_one_contract_instance() -> None:
    """Single INSERT preserves its one-row result cardinality."""
    database = await load_fixture(provide_people())
    query = sqlite.insert(Person(id=2, name="Grace")).returning_as(
        PersonSummary, name=Person.name, id=Person.id
    )

    async with database.transaction() as transaction:
        row = await transaction.execute(query)

    assert_type(row, PersonSummary)
    assert_eq(row, PersonSummary(id=2, name="Grace"))


@test(mark="medium")
async def sqlite_named_bulk_insert_keeps_cardinality() -> None:
    """Named bulk results preserve the write's list cardinality."""
    database = await load_fixture(provide_people())
    query = sqlite.insert(
        [Person(id=2, name="Grace"), Person(id=3, name="Lin")]
    ).returning_as(PersonSummary, id=Person.id, name=Person.name)

    async with database.transaction() as transaction:
        rows = await transaction.execute(query)

    assert_type(rows, list[PersonSummary])
    assert_eq(
        rows, [PersonSummary(id=2, name="Grace"), PersonSummary(id=3, name="Lin")]
    )


@test(mark="medium")
async def sqlite_named_empty_bulk_insert_keeps_cardinality() -> None:
    """Named bulk results preserve the write's list cardinality."""
    database = await load_fixture(provide_people())
    query = sqlite.insert([]).returning_as(
        PersonSummary, id=Person.id, name=Person.name
    )

    async with database.transaction() as transaction:
        rows = await transaction.execute(query)

    assert_type(rows, list[PersonSummary])
    assert_eq(rows, [])


@test(mark="slow")
async def mariadb_named_bulk_insert_keeps_cardinality() -> None:
    """Named bulk results preserve the write's list cardinality."""
    database = await load_fixture(provide_maria_people())
    query = mariadb.insert(
        [MariaPerson(id=2, name="Grace"), MariaPerson(id=3, name="Lin")]
    ).returning_as(PersonSummary, id=MariaPerson.id, name=MariaPerson.name)

    async with database.transaction() as transaction:
        rows = await transaction.execute(query)

    assert_type(rows, list[PersonSummary])
    assert_eq(
        rows, [PersonSummary(id=2, name="Grace"), PersonSummary(id=3, name="Lin")]
    )


@test(mark="slow")
async def mariadb_named_empty_bulk_insert_keeps_cardinality() -> None:
    """Named bulk results preserve the write's list cardinality."""
    database = await load_fixture(provide_maria_people())
    query = mariadb.insert([]).returning_as(
        PersonSummary, id=MariaPerson.id, name=MariaPerson.name
    )

    async with database.transaction() as transaction:
        rows = await transaction.execute(query)

    assert_type(rows, list[PersonSummary])
    assert_eq(rows, [])


@test(mark="slow")
async def mariadb_named_insert_returns_one_contract_instance() -> None:
    """MariaDB INSERT RETURNING materializes the same named result contract."""
    database = await load_fixture(provide_maria_people())
    query = mariadb.insert(MariaPerson(id=2, name="Grace")).returning_as(
        PersonSummary, name=MariaPerson.name, id=MariaPerson.id
    )

    async with database.transaction() as transaction:
        row = await transaction.execute(query)

    assert_type(row, PersonSummary)
    assert_eq(row, PersonSummary(id=2, name="Grace"))


@test(mark="medium")
async def named_update_preserves_result_through_readiness_transitions() -> None:
    """Choosing a result before SET and WHERE does not erase it."""
    database = await load_fixture(provide_people())
    query = (
        sqlite.update(Person)
        .returning_as(PersonSummary, id=Person.id, name=Person.name)
        .set(Person.name.to("Grace"))
        .where(Person.id.eq(1))
    )

    async with database.transaction() as transaction:
        rows = await transaction.execute(query)

    assert_type(rows, list[PersonSummary])
    assert_eq(rows, [PersonSummary(id=1, name="Grace")])


@test(mark="medium")
async def named_delete_returns_deleted_values() -> None:
    """DELETE RETURNING preserves its list shape and pre-delete column values."""
    database = await load_fixture(provide_people())
    query = (
        sqlite.delete(Person)
        .returning_as(PersonSummary, id=Person.id, name=Person.name)
        .where(Person.id.eq(1))
    )

    async with database.transaction() as transaction:
        rows = await transaction.execute(query)

    assert_type(rows, list[PersonSummary])
    assert_eq(rows, [PersonSummary(id=1, name="Ada")])


@test(mark="medium")
async def positional_returning_replaces_named_result() -> None:
    """Changing RETURNING back to a scalar clears the named contract."""
    database = await load_fixture(provide_people())
    query = (
        sqlite.update(Person)
        .set(Person.name.to("Grace"))
        .all()
        .returning_as(PersonSummary, id=Person.id, name=Person.name)
        .returning(Person.name)
    )

    async with database.transaction() as transaction:
        rows = await transaction.execute(query)

    assert_type(rows, list[str])
    assert_eq(rows, ["Grace"])


@test(mark="medium")
async def sqlite_named_returning_exceeds_eight_columns() -> None:
    """Wide RETURNING rows use the same named result contract as SELECT."""
    database = await load_fixture(provide_people())
    query = sqlite.insert(Person(id=2, name="Grace")).returning_as(
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

    async with database.transaction() as transaction:
        row = await transaction.execute(query)

    assert_type(row, WidePerson)
    assert_eq(
        row,
        WidePerson(
            first=2,
            second=2,
            third=2,
            fourth=2,
            fifth=2,
            sixth=2,
            seventh=2,
            eighth=2,
            ninth=2,
        ),
    )


@test(mark="medium")
async def sqlite_named_upsert_returns_conflict_update() -> None:
    """A conflict update returns its computed stored row through the named shape."""
    database = await load_fixture(provide_people())
    query = (
        sqlite.insert(Person(id=1, name="Grace"))
        .on_conflict(Person.id, action=sqlite.DoUpdate(Person.name.to_inserted()))
        .returning_as(PersonSummary, id=Person.id, name=Person.name)
    )

    async with database.transaction() as transaction:
        row = await transaction.execute(query)

    assert_type(row, PersonSummary)
    assert_eq(row, PersonSummary(id=1, name="Grace"))


@test(mark="slow")
async def mariadb_named_returning_exceeds_eight_columns() -> None:
    """Wide RETURNING rows use the same named result contract as SELECT."""
    database = await load_fixture(provide_maria_people())
    query = mariadb.insert(MariaPerson(id=2, name="Grace")).returning_as(
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

    async with database.transaction() as transaction:
        row = await transaction.execute(query)

    assert_type(row, WidePerson)
    assert_eq(
        row,
        WidePerson(
            first=2,
            second=2,
            third=2,
            fourth=2,
            fifth=2,
            sixth=2,
            seventh=2,
            eighth=2,
            ninth=2,
        ),
    )


@test(mark="slow")
async def mariadb_named_upsert_returns_conflict_update() -> None:
    """A conflict update returns its computed stored row through the named shape."""
    database = await load_fixture(provide_maria_people())
    query = (
        mariadb.insert(MariaPerson(id=1, name="Grace"))
        .on_conflict(
            MariaPerson.id, action=mariadb.DoUpdate(MariaPerson.name.to_inserted())
        )
        .returning_as(PersonSummary, id=MariaPerson.id, name=MariaPerson.name)
    )

    async with database.transaction() as transaction:
        row = await transaction.execute(query)

    assert_type(row, PersonSummary)
    assert_eq(row, PersonSummary(id=1, name="Grace"))

"""Named RETURNING contracts through public query compilation."""

from typing import TYPE_CHECKING, assert_type

from snektest import assert_eq, assert_raises, test

from snekql import mariadb, sqlite
from tests.query.test_named_projection import Person, PersonSummary


@test(mark="fast")
def named_insert_returning_compiles_labels() -> None:
    """Named write results use explicit aliases rather than positional tuples."""
    compiled = (
        sqlite.insert(Person(id=1, name="Ada"))
        .returning_as(PersonSummary, name=Person.name, id=Person.id)
        .compile()
    )

    assert_eq(
        compiled.sql,
        'INSERT INTO "person" ("id", "name") VALUES (?, ?) RETURNING "name" AS "name", "id" AS "id"',
    )
    assert_eq(compiled.params, (1, "Ada"))


class MariaRecord[S = mariadb.Pending](
    mariadb.Model[S, "MariaRecord[mariadb.Fetched]"]
):
    """A MariaDB write target for capability checks."""

    id: MariaRecord.Col[int] = mariadb.Integer(primary_key=True)
    name: MariaRecord.Col[str] = mariadb.Text()


@test(mark="fast")
def named_update_returning_keeps_backend_capability_guard() -> None:
    """A result contract does not enable unsupported MariaDB UPDATE RETURNING."""
    query = (
        mariadb.update(MariaRecord)
        .set(MariaRecord.name.to("Grace"))
        .all()
        .returning_as(PersonSummary, id=MariaRecord.id, name=MariaRecord.name)
    )

    with assert_raises(mariadb.QueryCompilationError):
        query.compile()


@test(mark="fast")
def named_delete_returning_keeps_backend_capability_guard() -> None:
    """MariaDB DELETE RETURNING remains outside the supported write contract."""
    query = (
        mariadb.delete(MariaRecord)
        .all()
        .returning_as(PersonSummary, id=MariaRecord.id, name=MariaRecord.name)
    )

    with assert_raises(mariadb.QueryCompilationError):
        query.compile()


@test(mark="fast")
def named_returning_rejects_foreign_columns() -> None:
    """Named bindings cannot escape the written model or backend."""
    with assert_raises(sqlite.QueryConstructionError):
        sqlite.insert(Person(id=2, name="Grace")).returning_as(
            PersonSummary, id=MariaRecord.id, name=Person.name
        )


@test(mark="fast")
def named_returning_rejects_do_nothing_conflicts() -> None:
    """Potentially skipped inserts retain the existing RETURNING restriction."""
    query = (
        sqlite.insert(Person(id=1, name="Ada"))
        .on_conflict(Person.id, action=sqlite.DoNothing)
        .returning_as(PersonSummary, id=Person.id, name=Person.name)
    )

    with assert_raises(sqlite.QueryCompilationError):
        query.compile()


if TYPE_CHECKING:

    def named_write() -> sqlite.Write[PersonSummary]:
        """Helper annotations retain a single INSERT's named result type."""
        return sqlite.insert(Person(id=2, name="Grace")).returning_as(
            PersonSummary, id=Person.id, name=Person.name
        )

    def named_update() -> sqlite.Write[list[PersonSummary]]:
        """UPDATE helpers retain list cardinality."""
        return (
            sqlite.update(Person)
            .set(Person.name.to("Grace"))
            .all()
            .returning_as(PersonSummary, id=Person.id, name=Person.name)
        )

    async def check_readiness_and_backend(
        transaction: sqlite.Transaction, other: mariadb.Transaction
    ) -> None:
        incomplete = sqlite.update(Person).returning_as(
            PersonSummary, id=Person.id, name=Person.name
        )
        await transaction.execute(incomplete)  # ty: ignore[no-matching-overload]
        await other.execute(named_write())  # ty: ignore[no-matching-overload]
        assert_type(await transaction.execute(named_write()), PersonSummary)
        assert_type(await transaction.execute(named_update()), list[PersonSummary])

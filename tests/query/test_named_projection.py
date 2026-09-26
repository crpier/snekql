"""Named result contracts through public query compilation."""

from typing import TYPE_CHECKING, ClassVar, assert_type

from pydantic import BaseModel, RootModel
from snektest import assert_eq, assert_raises, test

from snekql import mariadb, sqlite


class Person[S = sqlite.Pending](sqlite.Model[S]):
    """A table independent from its named result contract."""

    __row_type__: ClassVar[sqlite.ReadType[Person[sqlite.Row]]]

    id: Person.Col[int] = sqlite.Integer(primary_key=True)
    name: Person.Col[str] = sqlite.Text()


class PersonSummary(BaseModel):
    """An application result contract, not a table declaration."""

    id: int
    name: str


@test(mark="fast")
def named_projection_compiles_field_labels() -> None:
    """Bindings choose SQL values while the result contract names output fields."""
    compiled = (
        sqlite.select(Person)
        .project(PersonSummary, name=Person.name, id=Person.id)
        .compile()
    )

    assert_eq(compiled.sql, 'SELECT "name" AS "name", "id" AS "id" FROM "person"')
    assert_eq(compiled.params, ())


@test(mark="fast")
def named_projection_rejects_incompatible_column_binding() -> None:
    """Known logical column types cannot silently coerce into result fields."""
    with assert_raises(sqlite.QueryConstructionError):
        sqlite.select(Person).project(PersonSummary, id=Person.name, name=Person.name)


class OptionalPersonSummary(BaseModel):
    """A result field that admits an unmatched joined row."""

    id: int
    name: str | None


class PeerRole:
    """A nominal role for a second occurrence of Person."""


@test(mark="fast")
def named_projection_requires_optional_left_join_field() -> None:
    """A NOT NULL storage column still becomes nullable after a LEFT join."""
    peer = sqlite.alias(Person, PeerRole, name="peer")
    query = sqlite.select(Person).left_join(
        peer, on=Person.id.eq_col(peer.column(Person.id))
    )

    with assert_raises(sqlite.QueryConstructionError):
        query.project(PersonSummary, id=Person.id, name=peer.column(Person.name))


class WidePerson(BaseModel):
    """Nine independently named values exceed the positional overload ceiling."""

    first: int
    second: int
    third: int
    fourth: int
    fifth: int
    sixth: int
    seventh: int
    eighth: int
    ninth: int


@test(mark="fast")
def named_projection_rejects_missing_binding() -> None:
    """The contract cannot silently fill a field absent from the SQL projection."""
    with assert_raises(sqlite.QueryConstructionError):
        sqlite.select(Person).project(PersonSummary, id=Person.id)


@test(mark="fast")
def named_projection_rejects_duplicate_sql_labels() -> None:
    """Names differing only by case must not become ambiguous SQL labels."""

    class Ambiguous(BaseModel):
        id: int
        ID: int

    with assert_raises(sqlite.QueryConstructionError):
        sqlite.select(Person).project(Ambiguous, id=Person.id, ID=Person.id)


if TYPE_CHECKING:

    def person_summary_query() -> sqlite.ClosedRead[PersonSummary]:
        """Completed named queries retain the existing result-oriented annotation."""
        return sqlite.ready(
            sqlite.select(Person).project(PersonSummary, id=Person.id, name=Person.name)
        )

    async def check_named_readiness(transaction: sqlite.Transaction) -> None:
        query = sqlite.select(Person).project(
            PersonSummary, id=Person.id, name=Person.name
        )
        await transaction.fetch_all(query)
        assert_type(
            await transaction.fetch_all(person_summary_query()), list[PersonSummary]
        )
        assert_type(
            await transaction.fetch_one_or_none(query.where(Person.id.eq(1))),
            PersonSummary | None,
        )


@test(mark="fast")
def named_projection_rejects_root_contracts() -> None:
    """RootModel describes one root value rather than named output fields."""
    with assert_raises(sqlite.QueryConstructionError):
        sqlite.select(Person).project(RootModel[int], root=Person.id)


@test(mark="fast")
def named_projection_requires_optional_sum_result() -> None:
    """An aggregate over no input rows can produce SQL NULL."""

    class Total(BaseModel):
        total: int

    with assert_raises(sqlite.QueryConstructionError):
        sqlite.select(Person).project(Total, total=Person.id.sum())


type DisplayName = str


@test(mark="fast")
def named_projection_accepts_result_type_aliases() -> None:
    """An alias for a logical type does not introduce a new storage domain."""

    class AliasedSummary(BaseModel):
        name: DisplayName

    compiled = sqlite.select(Person).project(AliasedSummary, name=Person.name).compile()

    assert_eq(compiled.sql, 'SELECT "name" AS "name" FROM "person"')


@test(mark="fast")
def named_scalar_projection_rejects_another_backend() -> None:
    """Keyword bindings must not erase a scalar subquery's backend identity."""

    class ForeignPerson[S = mariadb.Pending](mariadb.Model[S]):
        __row_type__: ClassVar[mariadb.ReadType[ForeignPerson[mariadb.Row]]]
        id: ForeignPerson.Col[int] = mariadb.Integer(primary_key=True)

    class MaybeId(BaseModel):
        id: int | None

    with assert_raises(sqlite.QueryConstructionError):
        sqlite.select(Person).project(
            MaybeId,
            id=mariadb.scalar(mariadb.select(ForeignPerson.id)),  # ty: ignore[invalid-argument-type]
        )


@test(mark="fast")
def named_row_is_not_a_scalar_subquery_contract() -> None:
    """One named field still yields a row object, not a scalar value."""

    class OnlyId(BaseModel):
        id: int

    query = sqlite.select(Person).project(OnlyId, id=Person.id)

    with assert_raises(sqlite.QueryConstructionError):
        sqlite.scalar(query)  # ty: ignore[invalid-argument-type]


@test(mark="fast")
def named_projection_rejects_unexpected_binding() -> None:
    """Pydantic extra-field policy cannot silently discard projected values."""
    with assert_raises(sqlite.QueryConstructionError):
        sqlite.select(Person).project(
            PersonSummary, id=Person.id, name=Person.name, extra=Person.id
        )


@test(mark="fast")
def named_projection_rejects_unjoined_alias_binding() -> None:
    """A matching field type does not authorize a column outside the query."""
    peer = sqlite.alias(Person, PeerRole, name="peer")

    with assert_raises(sqlite.QueryConstructionError):
        sqlite.select(Person).project(
            PersonSummary, id=Person.id, name=peer.column(Person.name)
        )

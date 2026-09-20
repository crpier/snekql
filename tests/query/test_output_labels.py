"""Typed output tokens bind SQL expressions to named projection fields."""

from pydantic import BaseModel
from snektest import Param, assert_eq, assert_ne, assert_raises, test

from snekql import mariadb, sqlite


class Person[S = sqlite.Pending](sqlite.Model[S, "Person[sqlite.Fetched]"]):
    """A source whose field name differs from its output label."""

    person_id: sqlite.Col[int] = sqlite.Integer(primary_key=True)


class Identifier(BaseModel):
    """A named query result, not a schema declaration."""

    id: int


@test(mark="fast")
def label_binds_its_source_to_a_named_result() -> None:
    """A token retains the original expression while naming a projected output."""
    identifier = Person.person_id.label("id")

    compiled = sqlite.select(Person).all().project(Identifier, id=identifier).compile()

    assert_eq(compiled.sql, 'SELECT "person_id" AS "id" FROM "person"')
    assert_eq(compiled.params, ())


@test(mark="fast")
def label_name_must_match_the_projection_binding() -> None:
    """Spelling disagreement cannot silently rename a typed output token."""
    identifier = Person.person_id.label("different")

    with assert_raises(sqlite.QueryConstructionError):
        sqlite.select(Person).all().project(Identifier, id=identifier)


@test([Param("", name="empty"), Param("bad\x00label", name="nul")], mark="fast")
def malformed_labels_are_rejected(name: str) -> None:
    """Malformed output identifiers fail at token construction, before SQL IO."""
    with assert_raises(sqlite.QueryConstructionError):
        Person.person_id.label(name)


@test(mark="fast")
def equivalent_labels_remain_distinct_tokens() -> None:
    """Equal spelling and source do not manufacture membership in a definition."""
    first = Person.person_id.label("id")
    second = Person.person_id.label("id")

    assert_ne(first, second)


@test(mark="fast")
def labeled_binding_cannot_escape_its_query_scope() -> None:
    """Unwrapping a token still applies the ordinary projection ownership guard."""

    class Outside[S = sqlite.Pending](sqlite.Model[S, "Outside[sqlite.Fetched]"]):
        person_id: sqlite.Col[int] = sqlite.Integer(primary_key=True)

    with assert_raises(sqlite.QueryConstructionError):
        sqlite.select(Person).all().project(
            Identifier, id=Outside.person_id.label("id")
        )


@test(mark="fast")
def labeled_binding_preserves_logical_type_validation() -> None:
    """A label cannot hide an incompatible source value behind a result name."""

    class TextSource[S = sqlite.Pending](sqlite.Model[S, "TextSource[sqlite.Fetched]"]):
        value: sqlite.Col[str] = sqlite.Text()

    with assert_raises(sqlite.QueryConstructionError):
        sqlite.select(TextSource).all().project(
            Identifier, id=TextSource.value.label("id")
        )


@test(mark="fast")
def labeled_projection_uses_the_mariadb_dialect() -> None:
    """The shared token carries source metadata without embedding a dialect."""

    class Native[S = mariadb.Pending](mariadb.Model[S, "Native[mariadb.Fetched]"]):
        person_id: mariadb.Col[int] = mariadb.Integer(primary_key=True)

    compiled = (
        mariadb.select(Native)
        .all()
        .project(Identifier, id=Native.person_id.label("id"))
        .compile()
    )

    assert_eq(compiled.sql, "SELECT `person_id` AS `id` FROM `native`")
    assert_eq(compiled.params, ())

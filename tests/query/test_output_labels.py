"""Typed output tokens bind SQL expressions to named projection fields."""

from dataclasses import FrozenInstanceError

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


@test(mark="fast")
def aggregate_label_keeps_aggregate_sql() -> None:
    """Labeling COUNT preserves aggregate semantics rather than becoming a column."""
    total = Person.person_id.count().label("id")

    compiled = sqlite.select(Person).all().project(Identifier, id=total).compile()

    assert_eq(compiled.sql, 'SELECT COUNT("person_id") AS "id" FROM "person"')
    assert_eq(compiled.params, ())


@test(mark="fast")
def computed_label_preserves_textual_parameter_order() -> None:
    """The labeled SELECT expression's parameter precedes the WHERE parameter."""
    incremented = Person.person_id.add(4).label("id")

    compiled = (
        sqlite.select(Person)
        .where(Person.person_id.gt(8))
        .project(Identifier, id=incremented)
        .compile()
    )

    assert_eq(
        compiled.sql,
        'SELECT ("person_id" + ?) AS "id" FROM "person" WHERE ("person_id" > ?)',
    )
    assert_eq(compiled.params, (4, 8))


class OptionalIdentifier(BaseModel):
    """A scalar subquery can produce SQL NULL when its input is empty."""

    id: int | None


@test(mark="fast")
def scalar_label_preserves_subquery_parameter_order() -> None:
    """A labeled scalar remains a nested query with its own row scope."""
    identifier = sqlite.scalar(
        sqlite.select(Person.person_id).where(Person.person_id.eq(3))
    ).label("id")

    compiled = (
        sqlite.select(Person)
        .where(Person.person_id.eq(7))
        .project(OptionalIdentifier, id=identifier)
        .compile()
    )

    assert_eq(
        compiled.sql,
        'SELECT (SELECT "person"."person_id" FROM "person" WHERE ("person"."person_id" = ?)) AS "id" FROM "person" WHERE ("person_id" = ?)',
    )
    assert_eq(compiled.params, (3, 7))


@test(mark="fast")
def json_label_preserves_native_path_binding() -> None:
    """A dialect expression keeps its compiler and parameter instead of SQL text."""

    class Document[S = mariadb.Pending](mariadb.Model[S, "Document[mariadb.Fetched]"]):
        payload: mariadb.JsonCol[list[int]] = mariadb.Json()

    identifier = Document.payload.json_extract_int("$[0]").label("id")

    compiled = (
        mariadb.select(Document)
        .all()
        .project(OptionalIdentifier, id=identifier)
        .compile()
    )

    assert_eq(
        compiled.sql, "SELECT JSON_EXTRACT(`payload`, %s) AS `id` FROM `document`"
    )
    assert_eq(compiled.params, ("$[0]",))


@test(mark="fast")
def labels_cannot_be_retargeted_after_binding() -> None:
    """An issued output token cannot later acquire a different binding name."""
    identifier = Person.person_id.label("id")
    with assert_raises(FrozenInstanceError):
        identifier.name = "different"  # ty: ignore[invalid-assignment]


@test(mark="fast")
def untyped_label_names_fail_before_projection() -> None:
    """Dynamic callers receive the same construction error as malformed strings."""
    with assert_raises(sqlite.QueryConstructionError):
        Person.person_id.label(None)  # ty: ignore[invalid-argument-type]

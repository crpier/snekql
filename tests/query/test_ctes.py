"""Query-only named SELECT definitions through public compilation."""

from pydantic import BaseModel
from snektest import assert_eq, assert_raises, test

from snekql import mariadb, sqlite


class Person[S = sqlite.Pending](sqlite.Model[S, "Person[sqlite.Fetched]"]):
    """Physical input to a named SQL definition."""

    id: sqlite.Col[int] = sqlite.Integer(primary_key=True)


class Identifier(BaseModel):
    """The final named result contract."""

    id: int


class ActiveRole:
    """Nominal owner for the query-only relation."""


@test(mark="fast")
def completed_named_definition_compiles_as_a_cte() -> None:
    """A definition precedes its consumer and retains its bound parameters."""
    identifier = Person.id.label("id")
    active = (
        sqlite.select(Person)
        .where(Person.id.gt(2))
        .project(Identifier, id=identifier)
        .cte(ActiveRole, name="active")
    )

    compiled = sqlite.select(active).all().compile()

    assert_eq(
        compiled.sql,
        'WITH "active" AS (SELECT "id" AS "id", 1 AS "__snekql_present" FROM "person" WHERE ("id" > ?)) SELECT "active"."id" AS "id" FROM "active"',
    )
    assert_eq(compiled.params, (2,))


@test(mark="fast")
def bound_token_references_only_the_cte_output() -> None:
    """The consumer predicate uses the output role, not the definition's table."""
    identifier = Person.id.label("id")
    active = (
        sqlite.select(Person)
        .where(Person.id.gt(2))
        .project(Identifier, id=identifier)
        .cte(ActiveRole, name="active")
    )

    compiled = sqlite.select(active).where(active.column(identifier).gt(4)).compile()

    assert_eq(
        compiled.sql,
        'WITH "active" AS (SELECT "id" AS "id", 1 AS "__snekql_present" FROM "person" WHERE ("id" > ?)) SELECT "active"."id" AS "id" FROM "active" WHERE ("active"."id" > ?)',
    )
    assert_eq(compiled.params, (2, 4))


class FilteredRole:
    """A dependent definition has its own nominal owner."""


@test(mark="fast")
def chained_definitions_precede_the_consumer_in_parameter_order() -> None:
    """Each dependent SELECT reads an earlier definition without Python validation."""
    identifier = Person.id.label("id")
    active = (
        sqlite.select(Person)
        .where(Person.id.gt(2))
        .project(Identifier, id=identifier)
        .cte(ActiveRole, name="active")
    )
    filtered_id = active.column(identifier).label("id")
    filtered = (
        sqlite.select(active)
        .where(active.column(identifier).gt(3))
        .project(Identifier, id=filtered_id)
        .cte(FilteredRole, name="filtered")
    )

    compiled = (
        sqlite.select(filtered).where(filtered.column(filtered_id).gt(4)).compile()
    )

    assert_eq(
        compiled.sql,
        'WITH "active" AS (SELECT "id" AS "id", 1 AS "__snekql_present" FROM "person" WHERE ("id" > ?)), "filtered" AS (SELECT "active"."id" AS "id", 1 AS "__snekql_present" FROM "active" WHERE ("active"."id" > ?)) SELECT "filtered"."id" AS "id" FROM "filtered" WHERE ("filtered"."id" > ?)',
    )
    assert_eq(compiled.params, (2, 3, 4))


@test(mark="fast")
def definition_cannot_shadow_its_physical_source() -> None:
    """WITH name resolution must not turn a table read into accidental recursion."""
    active = (
        sqlite.select(Person)
        .all()
        .project(Identifier, id=Person.id.label("id"))
        .cte(ActiveRole, name="person")
    )

    with assert_raises(sqlite.QueryCompilationError):
        sqlite.select(active).all().compile()


@test(mark="fast")
def cte_used_only_in_exists_is_emitted() -> None:
    """Reachability includes nested predicates, not just the outer FROM source."""
    identifier = Person.id.label("id")
    active = (
        sqlite.select(Person)
        .where(Person.id.gt(2))
        .project(Identifier, id=identifier)
        .cte(ActiveRole, name="active")
    )
    nested = sqlite.select(active.column(identifier)).where(
        active.column(identifier).gt(3)
    )

    compiled = sqlite.select(Person).where(sqlite.exists(nested)).compile()

    assert_eq(
        compiled.sql,
        'WITH "active" AS (SELECT "id" AS "id", 1 AS "__snekql_present" FROM "person" WHERE ("id" > ?)) SELECT "id" FROM "person" WHERE (EXISTS (SELECT "active"."id" FROM "active" WHERE ("active"."id" > ?)))',
    )
    assert_eq(compiled.params, (2, 3))


@test(mark="fast")
def cte_used_only_in_a_scalar_predicate_is_emitted() -> None:
    """Scalar comparisons expose their nested SELECT to definition discovery."""
    identifier = Person.id.label("id")
    active = (
        sqlite.select(Person)
        .where(Person.id.gt(2))
        .project(Identifier, id=identifier)
        .cte(ActiveRole, name="active")
    )
    nested = (
        sqlite.select(active.column(identifier))
        .where(active.column(identifier).gt(3))
        .limit(1)
    )

    compiled = (
        sqlite.select(Person).where(Person.id.eq_col(sqlite.scalar(nested))).compile()
    )

    assert_eq(compiled.sql.startswith('WITH "active" AS ('), True)
    assert_eq(compiled.params, (2, 3, 1))


@test(mark="fast")
def plain_binding_does_not_make_none_a_column_token() -> None:
    """Only issued, bound label objects can identify typed output columns."""
    active = (
        sqlite.select(Person)
        .all()
        .project(Identifier, id=Person.id)
        .cte(ActiveRole, name="active")
    )

    with assert_raises(sqlite.QueryConstructionError):
        active.column(None)  # ty: ignore[no-matching-overload]


@test(mark="fast")
def definition_and_consumer_ordering_keep_their_own_limits() -> None:
    """Local ordering bounds the definition; final ordering belongs to its reader."""
    identifier = Person.id.label("id")
    active = (
        sqlite.select(Person)
        .all()
        .order_by(Person.id.asc())
        .limit(3)
        .project(Identifier, id=identifier)
        .cte(ActiveRole, name="active")
    )

    compiled = (
        sqlite.select(active)
        .all()
        .order_by(active.column(identifier).desc())
        .limit(1)
        .compile()
    )

    assert_eq(
        compiled.sql,
        'WITH "active" AS (SELECT "id" AS "id", 1 AS "__snekql_present" FROM "person" ORDER BY "id" ASC LIMIT ?) SELECT "active"."id" AS "id" FROM "active" ORDER BY "active"."id" DESC LIMIT ?',
    )
    assert_eq(compiled.params, (3, 1))


@test(mark="fast")
def repeated_predicate_references_emit_one_definition() -> None:
    """Repeated use duplicates consumer parameters, not the definition body."""
    identifier = Person.id.label("id")
    active = (
        sqlite.select(Person)
        .where(Person.id.gt(2))
        .project(Identifier, id=identifier)
        .cte(ActiveRole, name="active")
    )
    nested = sqlite.select(active.column(identifier)).where(
        active.column(identifier).gt(3)
    )

    compiled = (
        sqlite.select(Person)
        .where(sqlite.exists(nested) & sqlite.exists(nested))
        .compile()
    )

    assert_eq(compiled.sql.count('"active" AS ('), 1)
    assert_eq(compiled.params, (2, 3, 3))


@test(mark="fast")
def matching_spelling_does_not_grant_token_membership() -> None:
    """A freshly issued token cannot identify another token's bound output."""
    active = (
        sqlite.select(Person)
        .all()
        .project(Identifier, id=Person.id.label("id"))
        .cte(ActiveRole, name="active")
    )

    with assert_raises(sqlite.QueryConstructionError):
        active.column(Person.id.label("id"))


@test(mark="fast")
def dependent_definitions_cannot_reuse_a_casefolded_name() -> None:
    """One flattened WITH scope cannot contain two distinct matching names."""
    identifier = Person.id.label("id")
    active = (
        sqlite.select(Person)
        .all()
        .project(Identifier, id=identifier)
        .cte(ActiveRole, name="Active")
    )
    downstream_id = active.column(identifier).label("id")
    downstream = (
        sqlite.select(active)
        .all()
        .project(Identifier, id=downstream_id)
        .cte(FilteredRole, name="active")
    )

    with assert_raises(sqlite.QueryCompilationError):
        sqlite.select(downstream).all().compile()


@test(mark="fast")
def cte_mutation_target_fails_with_a_query_construction_error() -> None:
    """Dynamic callers cannot treat a query-only relation as writable schema."""
    active = (
        sqlite.select(Person)
        .all()
        .project(Identifier, id=Person.id)
        .cte(ActiveRole, name="active")
    )

    with assert_raises(sqlite.QueryConstructionError):
        sqlite.update(active)  # ty: ignore[invalid-argument-type]


@test(mark="fast")
def cte_alias_uses_one_definition_and_its_own_qualifier() -> None:
    """A new query role changes references, not the SQL definition's identity."""
    identifier = Person.id.label("id")
    active = (
        sqlite.select(Person)
        .where(Person.id.gt(2))
        .project(Identifier, id=identifier)
        .cte(ActiveRole, name="active")
    )
    peer = sqlite.alias(active, FilteredRole, name="peer")

    compiled = sqlite.select(peer).where(peer.column(identifier).gt(4)).compile()

    assert_eq(
        compiled.sql,
        'WITH "active" AS (SELECT "id" AS "id", 1 AS "__snekql_present" FROM "person" WHERE ("id" > ?)) SELECT "peer"."id" AS "id" FROM "active" AS "peer" WHERE ("peer"."id" > ?)',
    )
    assert_eq(compiled.params, (2, 4))


@test(mark="fast")
def cte_alias_roles_must_be_distinct_in_visible_scopes() -> None:
    """Reusing a role cannot make two visible references nominally identical."""
    identifier = Person.id.label("id")
    active = (
        sqlite.select(Person)
        .all()
        .project(Identifier, id=identifier)
        .cte(ActiveRole, name="active")
    )
    peer = sqlite.alias(active, ActiveRole, name="peer")

    with assert_raises(sqlite.QueryCompilationError):
        sqlite.select(active).where(sqlite.exists(sqlite.select(peer).all())).compile()


@test(mark="fast")
def cte_alias_cannot_shadow_a_different_reachable_definition() -> None:
    """Sibling nested scopes still share the statement's WITH namespace."""
    identifier = Person.id.label("id")
    active = (
        sqlite.select(Person)
        .all()
        .project(Identifier, id=identifier)
        .cte(ActiveRole, name="active")
    )
    other = (
        sqlite.select(Person)
        .all()
        .project(Identifier, id=identifier)
        .cte(FilteredRole, name="other")
    )
    peer = sqlite.alias(active, FilteredRole, name="other")

    with assert_raises(sqlite.QueryCompilationError):
        sqlite.select(Person).where(
            sqlite.exists(sqlite.select(other).all())
            & sqlite.exists(sqlite.select(peer).all())
        ).compile()


@test(mark="fast")
def original_and_alias_references_emit_the_shared_definition_once() -> None:
    """Definition parameters bind once even when two roles read its rows."""
    identifier = Person.id.label("id")
    active = (
        sqlite.select(Person)
        .where(Person.id.gt(2))
        .project(Identifier, id=identifier)
        .cte(ActiveRole, name="active")
    )
    peer = sqlite.alias(active, FilteredRole, name="peer")
    nested = sqlite.select(peer.column(identifier)).where(peer.column(identifier).gt(3))

    compiled = sqlite.select(active).where(sqlite.exists(nested)).compile()

    assert_eq(compiled.sql.count('"active" AS ('), 1)
    assert_eq(compiled.params, (2, 3))


@test(mark="fast")
def cte_alias_rejects_a_foreign_backend_before_compilation() -> None:
    """Dynamic calls cannot retag the definition by choosing another factory."""
    active = (
        sqlite.select(Person)
        .all()
        .project(Identifier, id=Person.id)
        .cte(ActiveRole, name="active")
    )

    with assert_raises(mariadb.QueryConstructionError):
        mariadb.alias(active, FilteredRole, name="peer")  # ty: ignore[no-matching-overload]


@test(mark="fast")
def cte_consumer_cannot_claim_locks_on_underlying_rows() -> None:
    """A derived relation does not establish the physical-table locking contract."""

    class Native[S = mariadb.Pending](mariadb.Model[S, "Native[mariadb.Fetched]"]):
        id: mariadb.Col[int] = mariadb.Integer(primary_key=True)

    active = (
        mariadb.select(Native)
        .all()
        .project(Identifier, id=Native.id)
        .cte(ActiveRole, name="active")
    )

    with assert_raises(mariadb.QueryCompilationError):
        mariadb.select(active).all().for_update().compile()


@test(mark="fast")
def cte_definition_cannot_hide_a_locking_select() -> None:
    """Freezing a SELECT must not move its row-lock intent into a derived scope."""

    class Native[S = mariadb.Pending](mariadb.Model[S, "Native[mariadb.Fetched]"]):
        id: mariadb.Col[int] = mariadb.Integer(primary_key=True)

    query = mariadb.select(Native).all().project(Identifier, id=Native.id).for_update()

    with assert_raises(mariadb.QueryConstructionError):
        query.cte(ActiveRole, name="active")


@test(mark="fast")
def distinct_definitions_cannot_reuse_an_indistinguishable_visible_role() -> None:
    """Different SQL bodies do not create different nominal owner types."""
    identifier = Person.id.label("id")
    first = (
        sqlite.select(Person)
        .all()
        .project(Identifier, id=identifier)
        .cte(ActiveRole, name="first")
    )
    second = (
        sqlite.select(Person)
        .where(Person.id.gt(0))
        .project(Identifier, id=identifier)
        .cte(ActiveRole, name="second")
    )

    with assert_raises(sqlite.QueryCompilationError):
        sqlite.select(first).join(
            second, on=first.column(identifier).eq_col(second.column(identifier))
        ).all().compile()

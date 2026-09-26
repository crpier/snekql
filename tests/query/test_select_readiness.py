"""SELECT composition needs no filtered or unfiltered acknowledgment."""

from typing import ClassVar

from pydantic import BaseModel
from snektest import Param, assert_eq, test

from snekql import mariadb, sqlite


class LocalEntry[S = sqlite.Pending](sqlite.Model[S]):
    __row_type__: ClassVar[sqlite.ReadType[LocalEntry[sqlite.Row]]]
    __tablename__ = "entries"
    id: sqlite.Col[int] = sqlite.Integer(primary_key=True)


class MariaEntry[S = mariadb.Pending](mariadb.Model[S]):
    __row_type__: ClassVar[mariadb.ReadType[MariaEntry[mariadb.Row]]]
    __tablename__ = "entries"
    id: mariadb.Col[int] = mariadb.Integer(primary_key=True)


@test([Param("sqlite", name="sqlite"), Param("mariadb", name="mariadb")], mark="fast")
def limited_select_needs_no_acknowledgment(backend: str) -> None:
    """Pagination can directly refine a SELECT without choosing row scope."""
    if backend == "sqlite":
        compiled = sqlite.select(LocalEntry.id).limit(1).compile()
        expected = 'SELECT "id" FROM "entries" LIMIT ?'
    else:
        compiled = mariadb.select(MariaEntry.id).limit(1).compile()
        expected = "SELECT `id` FROM `entries` LIMIT %s"

    assert_eq(compiled.sql, expected)
    assert_eq(compiled.params, (1,))


@test(
    [Param("sqlite", name="sqlite"), Param("mariadb", name="mariadb")],
    [Param("all-first", name="all-first"), Param("filter-first", name="filter-first")],
    mark="fast",
)
def compatibility_all_preserves_filtering(backend: str, order: str) -> None:
    """The old spelling neither clears predicates nor forbids adding them."""
    if backend == "sqlite":
        original = sqlite.select(LocalEntry.id)
        query = (
            original.all().where(LocalEntry.id.eq(7))
            if order == "all-first"
            else original.where(LocalEntry.id.eq(7)).all()
        )
        expected = 'SELECT "id" FROM "entries" WHERE ("id" = ?)'
    else:
        original = mariadb.select(MariaEntry.id)
        query = (
            original.all().where(MariaEntry.id.eq(7))
            if order == "all-first"
            else original.where(MariaEntry.id.eq(7)).all()
        )
        expected = "SELECT `id` FROM `entries` WHERE (`id` = %s)"

    assert_eq(query.compile().sql, expected)
    assert_eq(query.compile().params, (7,))
    assert_eq(original.compile().params, ())


class EntrySummary(BaseModel):
    id: int


class EntryRole:
    """An independent name for the reusable SELECT."""


@test([Param("sqlite", name="sqlite"), Param("mariadb", name="mariadb")], mark="fast")
def bare_named_select_can_define_cte(backend: str) -> None:
    """A named projection is ready to become a CTE without an extra call."""
    if backend == "sqlite":
        relation = (
            sqlite.select(LocalEntry)
            .project(EntrySummary, id=LocalEntry.id)
            .cte(EntryRole, name="entry_summary")
        )
        compiled = sqlite.select(relation).compile()
    else:
        relation = (
            mariadb.select(MariaEntry)
            .project(EntrySummary, id=MariaEntry.id)
            .cte(EntryRole, name="entry_summary")
        )
        compiled = mariadb.select(relation).compile()

    assert_eq(compiled.sql.startswith("WITH "), True)
    assert_eq(compiled.params, ())


@test([Param("sqlite", name="sqlite"), Param("mariadb", name="mariadb")], mark="fast")
def bare_named_select_can_form_union(backend: str) -> None:
    """Both UNION operands may be unfiltered named projections."""
    if backend == "sqlite":
        query = sqlite.select(LocalEntry).project(EntrySummary, id=LocalEntry.id)
        compiled = query.union_all(query).compile()
    else:
        query = mariadb.select(MariaEntry).project(EntrySummary, id=MariaEntry.id)
        compiled = query.union_all(query).compile()

    assert_eq(compiled.sql.count("UNION ALL"), 1)
    assert_eq(compiled.params, ())

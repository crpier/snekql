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


@test(
    [Param("sqlite", name="sqlite"), Param("mariadb", name="mariadb")],
    [
        Param(shape, name=shape)
        for shape in ("model", "scalar", "tuple", "named", "join")
    ],
    mark="fast",
)
def select_has_no_all_method(backend: str, shape: str) -> None:
    """Read acknowledgment is absent from every public SELECT shape."""
    if backend == "sqlite":
        queries: dict[str, object] = {
            "model": sqlite.select(LocalEntry),
            "scalar": sqlite.select(LocalEntry.id),
            "tuple": sqlite.select(LocalEntry.id, LocalEntry.id),
            "named": sqlite.select(LocalEntry).project(EntrySummary, id=LocalEntry.id),
            "join": sqlite.select(LocalEntry).join(
                sqlite.alias(LocalEntry, EntryRole, name="peer"),
                on=LocalEntry.id.eq(1),
            ),
        }
    else:
        queries = {
            "model": mariadb.select(MariaEntry),
            "scalar": mariadb.select(MariaEntry.id),
            "tuple": mariadb.select(MariaEntry.id, MariaEntry.id),
            "named": mariadb.select(MariaEntry).project(EntrySummary, id=MariaEntry.id),
            "join": mariadb.select(MariaEntry).join(
                mariadb.alias(MariaEntry, EntryRole, name="peer"),
                on=MariaEntry.id.eq(1),
            ),
        }

    assert_eq(hasattr(queries[shape], "all"), False)

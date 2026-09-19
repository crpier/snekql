"""Typed raw reporting recipes with inline data, requiring no schema setup.

Run with Python's context-aware warnings enabled. Pass these trusted SQL strings
and contracts to the matching backend's `raw` factory, then fetch normally.
"""

from typing import TYPE_CHECKING, assert_type

from pydantic import BaseModel

from snekql import mariadb, sqlite


class RankedScore(BaseModel):
    """Partition identity followed by the three different ranking semantics."""

    model_config = {"strict": True, "extra": "forbid"}

    team_id: int
    player_id: int
    position: int
    rank: int
    dense_rank: int


RANKING_SQL = """
WITH scores(team_id, player_id, points) AS (
    SELECT 1, 1, 100
    UNION ALL SELECT 1, 2, 100
    UNION ALL SELECT 1, 3, 70
    UNION ALL SELECT 2, 4, 90
)
SELECT team_id, player_id,
       ROW_NUMBER() OVER (
           PARTITION BY team_id ORDER BY points DESC, player_id
       ) AS position,
       RANK() OVER (PARTITION BY team_id ORDER BY points DESC) AS rank,
       DENSE_RANK() OVER (PARTITION BY team_id ORDER BY points DESC) AS dense_rank
FROM scores
ORDER BY team_id, position
"""
"""Window order determines ranks; final order determines returned row order."""


class CategoryVisit(BaseModel):
    """One visit, not a recursively nested Python object or a unique category."""

    model_config = {"strict": True, "extra": "forbid"}

    category_id: int
    parent_id: int | None
    depth: int


CATEGORY_SQLITE = """
WITH RECURSIVE categories(category_id, parent_id) AS (
    SELECT 1, NULL
    UNION ALL SELECT 2, 1
    UNION ALL SELECT 3, 2
    UNION ALL SELECT 4, 1
    UNION ALL SELECT 5, NULL
    UNION ALL SELECT 6, 7
    UNION ALL SELECT 7, 6
), descendants(category_id, parent_id, depth) AS (
    SELECT category_id, parent_id, 0 FROM categories WHERE category_id = :root_id
    UNION ALL
    SELECT child.category_id, child.parent_id, descendants.depth + 1
    FROM categories AS child
    JOIN descendants ON child.parent_id = descendants.category_id
    WHERE descendants.depth < :max_depth
)
SELECT category_id, parent_id, depth FROM descendants ORDER BY depth, category_id
"""
"""SQLite-native bindings; the disconnected cycle demonstrates bounded revisits."""

CATEGORY_MARIADB = """
WITH RECURSIVE categories(category_id, parent_id) AS (
    SELECT 1, NULL
    UNION ALL SELECT 2, 1
    UNION ALL SELECT 3, 2
    UNION ALL SELECT 4, 1
    UNION ALL SELECT 5, NULL
    UNION ALL SELECT 6, 7
    UNION ALL SELECT 7, 6
), descendants(category_id, parent_id, depth) AS (
    SELECT category_id, parent_id, 0 FROM categories WHERE category_id = %(root_id)s
    UNION ALL
    SELECT child.category_id, child.parent_id, descendants.depth + 1
    FROM categories AS child
    JOIN descendants ON child.parent_id = descendants.category_id
    WHERE descendants.depth < %(max_depth)s
)
SELECT category_id, parent_id, depth FROM descendants ORDER BY depth, category_id
"""
"""MariaDB-native bindings; raw does not translate placeholders for applications."""


class EventIdentity(BaseModel):
    """The shared shape of current and archived event identifiers."""

    model_config = {"strict": True, "extra": "forbid"}

    event_id: int


COMBINED_SQL = """
WITH current_events(event_id) AS (
    SELECT 1 UNION ALL SELECT 2
), archived_events(event_id) AS (
    SELECT 2 UNION ALL SELECT 3
)
SELECT event_id FROM current_events
UNION ALL
SELECT event_id FROM archived_events
ORDER BY event_id LIMIT 2 OFFSET 1
"""
"""Sort and paginate the entire multiset, retaining repeated identifiers."""

DISTINCT_SQL = """
WITH current_events(event_id) AS (
    SELECT 1 UNION ALL SELECT 2
), archived_events(event_id) AS (
    SELECT 2 UNION ALL SELECT 3
)
SELECT event_id FROM current_events
UNION
SELECT event_id FROM archived_events
ORDER BY event_id LIMIT 2 OFFSET 1
"""
"""SQL duplicate equality runs before final ordering and pagination."""


if TYPE_CHECKING:

    def ranking_query() -> sqlite.RawStatement[RankedScore]:
        """A helper preserves both the backend and named row contract."""
        return sqlite.raw(RANKING_SQL, validate=RankedScore)

    async def check_sqlite_reports(transaction: sqlite.Transaction) -> None:
        """Every recipe infers its declared row type through public consumption."""
        assert_type(await transaction.fetch_all(ranking_query()), list[RankedScore])
        assert_type(
            await transaction.fetch_all(
                sqlite.raw(
                    CATEGORY_SQLITE,
                    params={"root_id": 1, "max_depth": 2},
                    validate=CategoryVisit,
                )
            ),
            list[CategoryVisit],
        )
        assert_type(
            await transaction.fetch_all(
                sqlite.raw(COMBINED_SQL, validate=EventIdentity)
            ),
            list[EventIdentity],
        )

    async def check_mariadb_reports(transaction: mariadb.Transaction) -> None:
        """The same contracts do not erase a statement's backend identity."""
        assert_type(
            await transaction.fetch_all(mariadb.raw(RANKING_SQL, validate=RankedScore)),
            list[RankedScore],
        )
        assert_type(
            await transaction.fetch_all(
                mariadb.raw(
                    CATEGORY_MARIADB,
                    params={"root_id": 1, "max_depth": 2},
                    validate=CategoryVisit,
                )
            ),
            list[CategoryVisit],
        )
        assert_type(
            await transaction.fetch_all(
                mariadb.raw(COMBINED_SQL, validate=EventIdentity)
            ),
            list[EventIdentity],
        )
        await transaction.fetch_all(ranking_query())  # ty: ignore[no-matching-overload]

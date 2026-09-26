# Reporting with raw SQL

These examples use SQL for reports such as ranked groups, category trees, and
combined results. They run through [raw SQL](raw-sql.md) and validate the returned
rows with Pydantic.

Prefer the builder? It also supports [CTEs](ctes.md), [UNION](unions.md), and
[recursive queries](recursive-ctes.md). Ranking windows still need raw SQL.

The tested SQL and strict Pydantic result contracts live in
[`examples/reporting.py`](../examples/reporting.py). They include inline data,
so you can run them without migrations or table declarations. Import these
examples from a repository checkout, or copy them into your application and
replace the inline data with your own tables.

## Run the SQLite recipes

Enable context-aware warnings before starting Python:

```bash
PYTHON_CONTEXT_AWARE_WARNINGS=1 uv run python your_report.py
```

```python
import asyncio
from typing import assert_type

from examples.reporting import (
    CATEGORY_SQLITE,
    COMBINED_SQL,
    DISTINCT_SQL,
    RANKING_SQL,
    CategoryVisit,
    EventIdentity,
    RankedScore,
)
from snekql import sqlite


async def main() -> None:
    async with await sqlite.Database.initialize(database=":memory:") as database:
        async with database.transaction() as transaction:
            rankings = await transaction.fetch_all(
                sqlite.raw(RANKING_SQL, validate=RankedScore)
            )
            visits = await transaction.fetch_all(
                sqlite.raw(
                    CATEGORY_SQLITE,
                    params={"root_id": 1, "max_depth": 2},
                    validate=CategoryVisit,
                )
            )
            repeated = await transaction.fetch_all(
                sqlite.raw(COMBINED_SQL, validate=EventIdentity)
            )
            distinct = await transaction.fetch_all(
                sqlite.raw(DISTINCT_SQL, validate=EventIdentity)
            )

    assert_type(rankings, list[RankedScore])
    assert_type(visits, list[CategoryVisit])
    assert_type(repeated, list[EventIdentity])
    print(rankings, visits, repeated, distinct)


asyncio.run(main())
```

For an existing MariaDB Transaction, use `mariadb.raw` and `CATEGORY_MARIADB`.
The other three SQL strings are identical on both backends:

```python
from examples.reporting import CATEGORY_MARIADB, CategoryVisit
from snekql import mariadb


def category_report(
    root_id: int, max_depth: int
) -> mariadb.RawStatement[CategoryVisit]:
    return mariadb.raw(
        CATEGORY_MARIADB,
        params={"root_id": root_id, "max_depth": max_depth},
        validate=CategoryVisit,
    )


async def fetch_categories(transaction: mariadb.Transaction) -> list[CategoryVisit]:
    return await transaction.fetch_all(category_report(root_id=1, max_depth=2))
```

Validate application inputs before calling the helper. In particular, require a
nonnegative, reasonably small integer depth budget. Raw result validation does
not validate query parameters. Native placeholder syntax is intentionally
explicit in each SQL string; snekql does not translate it.

## Ranking semantics

The ranking recipe gives team 1 scores of 100, 100, and 70, then starts team 2.
Its team-1 rows have these results:

| Player | ROW_NUMBER | RANK | DENSE_RANK |
| --- | --- | --- | --- |
| 1 | 1 | 1 | 1 |
| 2 | 2 | 1 | 1 |
| 3 | 3 | 3 | 2 |

ROW_NUMBER orders by score and player ID for deterministic tied positions.
RANK and DENSE_RANK order only by score, preserving tied peer groups. Each window
partitions by team. A separate final ORDER BY chooses returned row order.

To filter a computed rank, put the window SELECT in a CTE or derived table and
filter that output. A window cannot be used directly in the same SELECT's WHERE.

## Category traversal

The recursive recipe anchors at a bound root ID, then joins children to previous
visits using UNION ALL. The root is depth zero. With root 1 and budget 2, rows are
`(1, None, 0)`, `(2, 1, 1)`, `(4, 1, 1)`, `(3, 2, 2)` in final depth/ID order.
That ordering does not promise breadth-first execution.

A missing root returns no rows. Budget zero returns only the root. The inline
categories also contain a disconnected cycle between 6 and 7. Root 6 with budget
3 returns visits to 6, 7, 6, 7 at depths 0 through 3.

The budget bounds revisits; it neither detects cycles nor deduplicates categories.
Changing UNION ALL to UNION would not remove these repeated nodes because their
depths differ. Branching can still produce many rows, and a backend recursion cap
may stop execution sooner. Outer LIMIT is not a portable termination policy.
The example uses integer depth, avoiding MariaDB's recursive text-width issues.

## Combined results

The inputs contain IDs `[1, 2]` and `[2, 3]`. UNION ALL retains both occurrences of
2; UNION removes duplicate SQL rows. Both examples apply final ORDER BY, LIMIT 2,
and OFFSET 1 to the combined result:

- UNION ALL returns IDs `[2, 2]`.
- UNION returns IDs `[2, 3]`.

Deduplication happens before final pagination. SQL equality and collations remain
backend behavior, not Python result-model equality. These integer examples avoid
cross-backend text collation differences.

## Contracts and limits

All three result models use strict validation and forbid extra fields. Raw uses
ordinary Pydantic contract policy, unlike named builder projections' mandatory
strict validation. Raw does not infer table-column codecs. Encode UUIDs, dates,
and other non-native values deliberately when adapting these recipes.

`RawStatement[Result]` keeps helper return types and backend identity. The examples
include positive ty assertions for both backends and a negative cross-backend
consumption case. Runtime tests execute the same SQL through real Transactions.
Result validation proves the fetched row shape, not SQL correctness or safety.
Only trusted SQL belongs in these strings; bind application values as parameters.

A raw statement has no builder readiness or capability analysis. Server syntax,
version support, resource limits, and recursion settings remain execution-time
concerns. These recipes do not change transaction behavior or the raw interface's
existing diagnostics, cleanup, and validation guarantees.

[All guides](README.md)

# Recursive CTE construction, draft

This implementation remains under review. Broader graph-boundary, width and
materialization acceptance is unfinished; it is not ready to release.

Both namespaces provide `recursive_cte(anchor, Role, name=...).step(callback)`.
The first call binds the completed named anchor and role. Its immutable builder
is neither a query nor a query source. `.step(callback)` then constructs and
validates the recursive definition, returning the completed CTE.

The two calls let the type checker fix the self relation's type before checking
the callback. This replaces the draft `recursive_cte(..., step=callback)` form,
which could infer `Unknown` for self-only lambdas. The old keyword is no longer
accepted. The staged form checks self-only member readiness, column comparisons,
source scope, result class and backend identity with ty.

The anchor's labels define the output contract. Each `.step()` call invokes its
callback once, not once per database row. The callback receives a fresh self
relation whose columns are addressed with the anchor's label tokens. It must
return a completed named SELECT with the same result class and compatible
outputs. Construction validates the anchor, name and member before publishing
any usable CTE. Reusing the prepared builder creates an independent definition;
failed construction cannot publish or leave behind a usable self relation.

```python
from pydantic import BaseModel
from snekql import sqlite


class Category[S = sqlite.Pending](sqlite.Model[S, "Category[sqlite.Fetched]"]):
    id: sqlite.Col[int] = sqlite.Integer(primary_key=True)
    parent_id: sqlite.Col[int | None] = sqlite.Integer()


class Visit(BaseModel):
    id: int
    depth: int


class WalkRole:
    pass


identifier = Category.id.label("id")
depth = sqlite.literal(0).label("depth")
anchor = (
    sqlite.select(Category)
    .where(Category.id.eq(1))
    .project(Visit, id=identifier, depth=depth)
)
walk = sqlite.recursive_cte(
    anchor,
    WalkRole,
    name="walk",
).step(
    lambda previous: (
        sqlite.select(Category)
        .join(previous, on=Category.parent_id.eq_col(previous.column(identifier)))
        .where(previous.column(depth).lt(3))
        .project(Visit, id=Category.id, depth=previous.column(depth).add(1))
    )
)
query = (
    sqlite.select(walk)
    .all()
    .order_by(walk.column(depth).asc(), walk.column(identifier).asc())
)
```

SQL uses a direct `anchor UNION ALL member` inside `WITH RECURSIVE`.
It does not wrap the recursive member in the derived tables used by ordinary
UNION composition. Anchor parameters precede member parameters.

The self relation is not the returned relation. A query retaining the callback's
self reference cannot compile independently, including after failed construction.
Nested references cannot reuse the direct member's permission to reference self.

## Initial limits

- One direct self source, never on the nullable side of a join.
- No member DISTINCT, aggregates, grouping, HAVING, local ordering, pagination,
  or locking SELECT. Ordinary UNION contract checks also apply.
- Anchors require physical column outputs or native integer literals, including
  CTE references to those outputs. Computed Python `int` outputs do not establish
  MariaDB SQL width.
- Output fields match by name. The anchor's nullability and decoding policies
  cannot be widened by the member. Growing text paths remain unsupported.
- No mutual recursion, writable members, implicit cycle detection, or public
  depth-budget option.

The application must validate any depth budget it supplies. A depth bound limits
path length, not branching growth or total rows. Repeated visits are expected.
Neither an outer LIMIT nor a deadline proves termination. Server recursion limits
may reject a query before it reaches an application budget.

Native tests currently cover depth zero, missing roots, bounded cyclic revisits,
and final ordering on SQLite and MariaDB. Broader graph-boundary, width,
materialization, and public named-callback annotations remain pending.

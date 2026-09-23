# Native integer literals

Both backend namespaces provide `literal(integer)` for an owner-free, native
signed-64 SQL value. This is the depth-seed prerequisite for typed recursive
CTEs. Recursive builder construction is not implemented yet.

```python
from pydantic import BaseModel
from snekql import sqlite


class Category[S = sqlite.Pending](sqlite.Model[S, "Category[sqlite.Fetched]"]):
    id: sqlite.Col[int] = sqlite.Integer(primary_key=True)


class Visit(BaseModel):
    category_id: int
    depth: int


class Seeds:
    pass


depth = sqlite.literal(0).label("depth")
anchor = (
    sqlite.select(Category)
    .where(Category.id.eq(1))
    .project(Visit, category_id=Category.id, depth=depth)
)
seeds = anchor.cte(Seeds, name="seeds")
next_depth = seeds.column(depth).add(1)
# seeds.column(depth) has integer value type, not int | None.
```

Use the matching namespace for the query and its constants. Mixing a MariaDB
literal into a SQLite projection, or vice versa, raises `QueryConstructionError`.
A literal does not belong to any table and is not null-extended when a projected
query contains a LEFT join. A later LEFT join to the resulting CTE still follows
the normal nullable-output rules.

Constants do not provide an implicit FROM clause. `select(literal(0))` is not
supported. Start from an explicit source and project the literal. After CTE
rebinding, the output supports the existing integer comparisons, arithmetic
and numeric aggregate operations. Native integer literal and arithmetic outputs
have compatible UNION policies, subject to the other named-output guards.

## Validation and SQL domain

Only plain Python integers in `[-2**63, 2**63 - 1]` are accepted. Booleans,
NULL, floats, strings and integers outside that range are rejected. There is no
SQL-text input or caller-supplied type argument. Other literal domains remain
outside this initial API.

Values remain bound parameters. SQLite emits its ordinary placeholder. MariaDB
emits `CAST(CAST(%s AS DECIMAL(19, 0)) AS SIGNED)`. This establishes a signed-64
native result rather than returning a Decimal to Python.

The double cast is deliberate. MariaDB can materialize a small recursive anchor
as a 32-bit integer even for `CAST(0 AS SIGNED)`. Declaring all 19 integer digits
before the signed cast preserves both signed-64 boundaries. Construction has
already rejected values outside that range; this does not cast arbitrary SUM,
AVG or user column outputs into a narrower domain.

The native tests embed compiled literal anchors into raw recursive SQL to check
32-bit boundary crossings and signed-64 edge values. They do not imply that the
future recursive builder, growing text paths, cycle detection or general
termination analysis is already implemented.

# Walk a hierarchy with a recursive query

Use a recursive CTE for data such as category trees or parent/child chains. Start
with an initial query, then describe how to find the next rows from the previous
ones. The database runs that recursion; Python does not fetch one level at a time.

Both SQLite and MariaDB use `recursive_cte(anchor, Role, name=...).step(callback)`.
The example starts at category 1 and follows its children to depth 3. Read
[ordinary CTEs](ctes.md) first if labels and role markers are new to you.

```python
from typing import ClassVar

from pydantic import BaseModel

from snekql import sqlite


class Category[S = sqlite.Pending](sqlite.Model[S]):
    __row_type__: ClassVar[sqlite.ReadType[Category[sqlite.Row]]]
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

## How the step works

The anchor supplies the initial rows and names their output fields. The callback
builds the query that produces the next rows, using those same output labels.
It runs once while constructing the query, **not** once per database row.

The first call to `recursive_cte` only prepares the builder. Call `.step(...)`
to get the completed CTE you can select from. Keeping these calls separate lets
ty infer the callback's input before checking its body. The old `step=` keyword
is not supported.

The step must return a completed named SELECT with the same result class and
compatible outputs. Construction checks names, sources, backend, and output
compatibility before returning a usable CTE. Reusing the prepared builder makes
an independent definition.

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

## Acceptance coverage

[Construction tests](../tests/query/test_recursive_ctes.py) reject multiple aliased
self sources, indirect dependencies, nested self queries, escaped self anchors,
and nested recursion capturing an unfinished outer definition. Existing tests
also retain callback-once, failed-construction isolation and nullable-side guards.
Member ordering, bounds, locks, DISTINCT and aggregates/grouping are rejected
before execution. Windows have no typed builder entry point.

[Native tests](../tests/runtime/test_recursive_ctes.py) run on SQLite and MariaDB:

- Depth zero, missing roots, bounded cyclic revisits and independent final order.
- Direct self aliases crossing both signed-32 limits and reaching both signed-64
  endpoints from full-width literal anchors. Each case terminates after two rows.
- Unchanged UUID/JSON fields, reordered named bindings and completed CTE aliases.
- Invalid intermediate result constraints filtered by SQL before materialization.
  Python field validators run only on the returned rows, once per row.
- Strict final validation with source validation both enabled and disabled.
- An all-NULL recursive member distinguished from an absent outer-joined row.

Construction also rejects nullability widening, INTEGER/TEXT codec substitution
and larger MariaDB text capacities despite matching Python types. These checks do
not prove arbitrary arithmetic cannot overflow. Applications must keep computed
values inside their established SQL domains. Growing text paths remain deferred.

## Named callbacks

The names in this example come from the earlier traversal:

```python
def advance(
    previous: sqlite.Cte[Category, Visit, WalkRole],
) -> sqlite.NamedOperand[Visit]:
    return (
        sqlite.select(Category)
        .join(previous, on=Category.parent_id.eq_col(previous.column(identifier)))
        .where(previous.column(depth).lt(3))
        .project(Visit, id=Category.id, depth=previous.column(depth).add(1))
    )


walk = sqlite.recursive_cte(anchor, WalkRole, name="walk").step(advance)
```

Both namespaces export these nonconstructible annotations:

- `Cte[Source, Result, Role, NonNullableSource=Source]` retains source ownership,
  result model, role and null-extension information. The namespace fixes its
  backend. It also annotates helpers returning completed `.cte()` relations or
  aliases of them. A callback self reference still cannot escape its member.
- `NamedOperand[Result]` describes a completed named SELECT or UNION operand.
  It retains backend, result identity and readiness. Use it for a helper returning
  the right operand of `.union()`/`.union_all()` or a recursive member. Recursive
  construction still restricts that member to one direct self SELECT.

`NamedOperand` deliberately exposes no fluent query editing after source scope
has been erased. It is neither an anchor annotation nor a directly fetchable
query annotation. Use `ReadQuery[Scope, Result]`, or `ClosedRead[Result]` after
`ready`, for helpers returning queries to a Transaction. Keep anchor builder
inference intact.

For a left-joined anchor over `Category | Detail`, pass the nonnullable source
explicitly, for example `Cte[Category | Detail, Visit, WalkRole, Category]`.
Otherwise the default claims both sources are nonnullable and the type checker
rejects that callback. Labels for nullable outputs retain their optional types;
owner-free literal labels do not become nullable.

Source coordinates name model owners, not relation values. The inferred owners
of alias- or CTE-derived anchors are private types; keep callbacks inline when
those owners cannot be expressed using public model annotations. Do not import
private owner types to annotate a helper. This does not restrict inferred query
composition or aliases of a completed, annotated relation.

[All guides](README.md)

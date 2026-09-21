# Query composition design

Status: interface reviewed and approved. Typed labels and nonrecursive CTEs are
implemented; set operations, windows and recursion remain focused follow-ups.
Tracking issue: #280. SQLite and MariaDB only.

## Existing support

The query builder already has subqueries, aggregates, aliases, ordinary join
predicates, typed value expressions, named projections, and supported RETURNING.
The raw interface already executes CTEs, recursive CTEs, windows, and set
operations with validated result contracts. This design does not replace any
of that work.

The four follow-ups below separate implementation work. CTE output references
are implemented because set ordering, ranking filters, and recursion need them.
The runnable interim recipes are in [reporting with raw SQL](reporting.md).

## Typed output references and CTEs

Implemented syntax. See [typed CTE usage and limits](ctes.md) and the tested recipe.

```python
user_id = User.id.label("id")
user_name = User.name.label("name")

active = (
    select(User)
    .where(User.active.eq(True))
    .project(UserSummary, id=user_id, name=user_name)
    .cte(ActiveUsersRole, name="active_users")
)

query = select(active).where(active.column(user_id).gt(10))
# Select[UserSummary]
```

A label token derives its logical value type, comparison domain, backend, and
codec from its expression. It is not constructed from a caller-supplied type.
`active.column(user_id)` rebinds the output to the CTE's nominal role and retains
that SQL value contract. It cannot refer back to the original table implicitly.
The result model still controls the final fetched row object.

For named projections, a token's label must match its keyword binding. Plain
bindings remain valid for fetching whole result objects. A typed column lookup
requires a token actually bound by that definition; matching spelling alone is
insufficient. Duplicate labels are rejected ignoring case. CTEs initially require
named projections, avoiding unlabeled tuple positions and table-model expansion.

Alternatives considered:

- `.column("id")` cannot infer a field type from an arbitrary Pydantic class.
- `.column("id", int)` is a caller assertion, not a derived contract.
- `.column(User.id)` is ambiguous when one source column supplies several outputs.
- Generated result-table declarations duplicate the existing named result model
  and incorrectly suggest schema ownership.
- Attribute access such as `active.c.id` needs generated stubs or checker-specific
  behavior. Do not make that a prerequisite.

The reviewed token interface costs one local variable per output later referenced
in SQL. If the typing proof requires a different interface, reopen review before
implementing it.

CTE rules:

- Completed SELECTs only. Definitions retain backend identity and readiness.
  CTE relations are never schema objects or write targets.
- Emit reachable definitions once, in stable dependency order, before the final
  SELECT. Merely constructing an unused definition does not emit it.
- Definitions see their own FROM/JOIN sources and declared CTE dependencies,
  not an enclosing query's row sources. Ordinary correlated subqueries retain
  their existing rules inside each SELECT.
- Reject dependency cycles, except the explicit recursive form below. Reject
  collisions among visible CTE, table, and alias names before execution.
- Extend existing `alias` to query-only CTE references for repeated joins.
  Two aliases share one definition but have distinct nominal scope owners.
- Definition-local ORDER BY/LIMIT affect that definition. They never promise
  ordering of its consumers. A final ORDER BY remains necessary.
- Preserve output codecs and SQL nullability when columns cross a definition.
  LEFT JOIN consumers widen nullable outputs as they do for table columns.
- Python result validators run when rows are fetched, not inside SQL definitions.
  A column token describes the SQL value, not a Python validator's transformed
  result. No intermediate Pydantic model construction occurs inside the database.
- Compile parameters in SQL text order, including all preceding definitions.
  Definitions do not execute independently and gain no transaction lifetime.
- Do not promise optimizer materialization or evaluation count. Materialization
  hints, writable CTEs, lateral references, and nested WITH shadowing are deferred.

## UNION and UNION ALL

Reviewed syntax, not runnable today:

```text
combined = current.union_all(archived)
unique = current.union(archived)
page = combined.order_by(combined.column(event_id).asc()).limit(50).offset(100)
# Select[EventIdentity]
```

Initial operands must be completed named SELECTs of the same backend and exact
result-model class. A shared Python result class alone does not prove SQL
compatibility. Match fields by name and emit both operands in result-field order,
regardless of the original keyword binding order.

For every output, require provably compatible logical domains, wire encodings,
and decode/validation policies. Preserve nullability across both operands and
require the result field to admit it. Do not guess a common numeric type or use
the left operand's codec when the right differs. Two UUID fields stored as TEXT
and BLOB are not interchangeable just because both decode to UUID. Different
source validators also need an explicit compatibility decision, not silent
selection of one branch's validator. Unknown compatibility fails conservatively.

This requires private output-layout metadata shared with CTEs. Pydantic result
validation remains the final check, but cannot repair values already coerced or
truncated by the server.

- UNION removes duplicate SQL rows. UNION ALL retains them. Equality follows
  backend NULL and collation rules, not Python model equality.
- Combined ORDER BY refers only to combined output tokens, not operand tables.
  LIMIT/OFFSET apply after the complete set operation.
- Initially reject operand-local ORDER BY/LIMIT/OFFSET to avoid backend-dependent
  grouping syntax. Use an explicitly bounded CTE as an operand when needed.
- Repeated operations preserve the expression tree. Never flatten mixed UNION
  and UNION ALL or change their grouping. Dialects must preserve it with explicit
  derived queries where direct parentheses are unsupported.
- To filter or join the combined result, turn it into a CTE. Do not pretend its
  operands' scopes remain visible.
- Scalar/tuple operands, cross-model result inference, implicit casts, INTERSECT,
  EXCEPT, and write inputs are deferred.

## Ranking windows

Reviewed syntax, not runnable today:

```text
position = row_number().over(
    partition_by=(Score.team_id,),
    order_by=(Score.points.desc(), Score.player_id.asc()),
).label("position")

ranked = (
    select(Score)
    .project(RankedScore, ..., position=position)
    .all()
    .cte(RankedRole, name="ranked")
)
query = select(ranked).where(ranked.column(position).lte(3))
```

Factories belong to each backend namespace. Begin with `row_number`, `rank`, and
`dense_rank`, all returning non-null integers. Require nonempty ordering and
allow an empty partition tuple for one partition covering the input.

Every partition/order reference must belong to the current query scope. Track
all referenced owners, including different joined relations. A window is not an
ordinary aggregate and does not force GROUP BY. Its inputs must still respect
ordinary grouping rules in an aggregated query.

Allow windows in SELECT and supported final ORDER BY positions, not WHERE, ON,
GROUP BY, HAVING, assignments, RETURNING, or another window's specification.
Use a CTE to filter a computed rank. Window ordering does not order the returned
rows. ROW_NUMBER needs a unique tie-breaker for deterministic positions; adding
that tie-breaker to RANK would deliberately change its peer groups.

Defer named windows, aggregate windows, frames, LAG/LEAD, and backend-specific
QUALIFY. Before adding running aggregates, review an explicit ROWS frame
interface rather than inheriting surprising default RANGE peer behavior.

## Recursive CTEs

Reviewed shape, not runnable today:

```text
walk = recursive_cte(
    anchor,
    CategoryWalkRole,
    name="category_walk",
    step=lambda previous: (
        select(Category)
        .join(previous, on=Category.parent_id.eq_col(previous.column(category_id)))
        .project(CategoryVisit,
            category_id=Category.id,
            parent_id=Category.parent_id,
            depth=previous.column(depth).add(1),
        )
        .where(previous.column(depth).lt(max_depth))
    ),
)
```

The completed named anchor fixes the row contract and typed output labels before
constructing the step. The callback receives a typed self relation and runs once
during query construction, not per database row. It returns a completed query of
the same result class, backend, and compatible output layout. Step bindings match
anchor labels by name. No Python recursively nested model is required.

A category anchor needs a typed native integer literal for depth zero. An
owner-free, backend-owned `literal(0)` expression is therefore an explicit
prerequisite, not an existing feature. Infer its domain from the value; do not
accept arbitrary SQL text or a caller-asserted type. An untyped NULL anchor cannot
establish a recursive output domain by itself.

Initial restrictions:

- Anchor cannot reference self. Step references self once as a direct FROM/JOIN
  relation. Reject indirect, nested, mutual, or multiple self references.
- Combine anchor and step with UNION ALL. No step-level aggregate/window,
  grouping, DISTINCT, ordering, pagination, or nullable-side self reference.
- Begin with native integer identifiers/depth and unchanged compatible fields.
  Defer growing text paths until explicit SQL width/cast semantics are designed.
  MariaDB anchor widths can otherwise constrain or truncate recursive values.
- A depth predicate limits visits, not cycles or total row count. Revisited nodes
  remain separate rows. Examples require an application-validated nonnegative
  depth budget; arbitrary graph branching can still produce many rows.
- General termination is the caller's responsibility. Do not claim that an
  outer LIMIT, transaction deadline, or server iteration setting proves it.
  Server recursion caps are backend policy, not a portable library depth limit.
- Final ordering is explicit and says nothing about execution traversal order.

## Errors and backend support

Use `QueryConstructionError` for invalid labels, incompatible contracts, backend
mismatches, invalid arguments, and ownership errors already known at construction.
Use `QueryCompilationError` for completed-graph scope, clause placement, recursion,
and dialect capability failures. Both happen before IO. Keep existing result
validation errors for invalid fetched rows.

Dialect support is explicit, not a promise to lower every SQL construct. Shared
query state owns relational structure; backend dialects own SQL differences and
capability checks. Do not add backend imports to the shared query modules.

Both current test backends execute the raw recipes. That is not a claim that all
historical SQLite/MariaDB versions support these features. Offline compilation
cannot discover a server version. Unsupported actual server versions and resource
limits may still raise existing execution errors; broader MariaDB LTS support
remains separate work. Raw SQL bypasses builder capability analysis by design.

## Focused implementation follow-ups

| Follow-up | Delivery and acceptance |
| --- | --- |
| #370: Typed output labels and nonrecursive CTEs | Prove token inference with ty first. Implement query-only relations, output layouts/codecs, dependency order, names, alias reuse, scope, nullability, and parameter order. Test whole named rows and typed column consumption. |
| #372: Named UNION / UNION ALL | Match output fields and compatible codec policies, preserve duplicate semantics, mixed-operation grouping, final ordering/pagination, and backend/readiness errors. Test reordered bindings, incompatible wire encodings, and empty operands. |
| #371: Ranking windows | Three integer ranking functions, explicit partition/order, all-owner scope checks, clause guards, ties, grouping interactions, and CTE rank filtering. |
| #373: Recursive CTEs | Native literal prerequisite, typed anchor/self/step, fixed output contracts, conservative recursion rules, missing roots, depth zero, bounded cycles, and backend anchor-type behavior. |

Each implementation needs public compilation, real SQLite/MariaDB Transaction
results, positive/negative ty cases, snektest, Ruff, and generated-interface
checks. Keep recipe tests as interim coverage. Do not implement all four in one
PR. Start with #370. Set operations and ranking depend on that output-reference
contract; recursion also depends on compatible UNION ALL composition from #372.

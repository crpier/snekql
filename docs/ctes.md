# Typed labels and nonrecursive CTEs

SQLite and MariaDB support completed named SELECT definitions through `.cte()`.
A CTE is a query source, not a table declaration or a stored database object.

## Define and consume

```python
from pydantic import BaseModel
from snekql import sqlite


class User[S = sqlite.Pending](sqlite.Model[S, "User[sqlite.Fetched]"]):
    id: sqlite.Col[int] = sqlite.Integer(primary_key=True)
    name: sqlite.Col[str] = sqlite.Text()
    active: sqlite.Col[bool] = sqlite.Integer()


class UserSummary(BaseModel):
    id: int
    name: str


class ActiveUsers:
    pass


user_id = User.id.label("id")
active = (
    sqlite.select(User)
    .where(User.active.eq(True))
    .project(UserSummary, id=user_id, name=User.name)
    .cte(ActiveUsers, name="active_users")
)
query = (
    sqlite.select(active)
    .where(active.column(user_id).gt(10))
    .order_by(active.column(user_id).asc())
)
# await transaction.fetch_all(query) returns list[UserSummary].
```

The complete, tested recipe is
[`examples/typed_ctes.py`](../examples/typed_ctes.py). Run it from a checkout:

```bash
PYTHON_CONTEXT_AWARE_WARNINGS=1 uv run python -m examples.typed_ctes
```

Use the matching backend's models, factories and transaction. Definitions and
columns retain backend identity. An incomplete SELECT requires `.all()` or
`.where(...)` before `.cte()`.

## Tokens and result contracts

A label derives its value type, comparison domain and codecs from an expression.
It does not accept a caller-supplied type. The label must match its named keyword
binding; output names must be unique ignoring case.

Only a token actually bound by that definition can be used in `.column(token)`.
A new token with the same spelling is not interchangeable. Strings and schema
columns are not lookup keys. Plain bindings such as `name=User.name` remain
valid for whole-row reads but do not create lookup tokens.

The result model validates the final fetched row. Its annotations do not change
SQL value domains or wire encodings. Python result validators never execute
inside a definition. Scalar column reads preserve the original source codec;
`validate=False` retains the existing unchecked source-read policy. Named result
contracts still validate strictly.

## Repeated references and joins

```python
class PeerUsers:
    pass


peer = sqlite.alias(active, PeerUsers, name="peer_users")
paired = (
    sqlite.select(active)
    .join(peer, on=active.column(user_id).eq_col(peer.column(user_id)))
    .all()
)
# Whole joined rows are tuple[UserSummary, UserSummary].
```

Aliases share one definition but have distinct SQL names and nominal owners.
Use distinct roles for simultaneously visible references. INNER and LEFT joins
support whole named rows and explicit column projections. A missing LEFT-joined
whole row is `None`; a matched row whose visible fields are all NULL remains a
result-model instance. A private presence output preserves that distinction.
It is not a public column or label.

Projected LEFT outputs require nullable result fields unless SQL computation
removes NULL, for example with `coalesce`. Optional fetches distinguish a present
named row containing NULL from no row. Chunked reads use the same decoding and
validation rules.

## Output operations

Readonly output references support comparisons, ordering, labels, GROUP BY,
grouped HAVING, COUNT, MIN/MAX and numeric SUM/AVG. Source ordering restrictions
remain in force, including the restriction on ordering `ZonedDatetime` values.
Text, Boolean and UUID outputs are not numeric aggregate inputs.

Native integer, real and text outputs can use the existing value-expression
operations, including arithmetic, COALESCE and text functions. Unsupported or
unknown wire domains fail before execution. In particular, arithmetic over
SUM/AVG outputs is currently rejected rather than guessing from normalized
Python result types. A native integer SUM can arrive as Decimal; silently
casting it to a bounded SQL integer could lose data. Direct SUM/AVG reads remain
supported.

## Scope and execution rules

- Reachable definitions are emitted once, in dependency order. Parameters follow
  SQL text order, including definitions and nested SELECTs.
- Definitions see their own sources and dependencies, not an enclosing consumer
  row. Ordinary correlated subqueries can reference sources inside a definition.
- Definition-local ordering and pagination apply there. Consumers need their own
  ORDER BY. No optimizer materialization or evaluation-count guarantee is made.
- Definitions do not execute independently or acquire transaction lifetime.
- Cycles, invalid tokens, visible name collisions and nested WITH shadowing fail
  before I/O. A definition cannot contain a locking SELECT, and a CTE consumer
  cannot request FOR UPDATE as though it locked the underlying table.
- CTEs cannot register schemas, migrate/scaffold tables, or serve as mutation
  targets. Writable CTEs, lateral references and materialization hints are not
  supported.

[Named UNION and UNION ALL](unions.md) results can also become CTEs. Windows and
recursive builders remain separate follow-ups. Use the [raw reporting
recipes](reporting.md) for those operations. The
[composition design](query-composition-design.md) records their reviewed scope.

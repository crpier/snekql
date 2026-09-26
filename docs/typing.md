# Types and declaration reference

Use this page when you need an exact result type, a query-helper annotation, or
an advanced column declaration. For your first model or query, the shorter
[model guide](models.md) and [query guide](queries.md) are easier starting points.

**ty 0.0.84 is the supported checker.** Pyright and mypy do not support the full
class-body interface. See [checker support](typing-compatibility.md) for results
and editor setup. Static guarantees on this page refer to ty unless stated otherwise.

## Find the part you need

- Values: [model states](#model-states), [columns](#col-and-gencol),
  [query results](#query-result-shapes)
- Helpers: [read query annotations](#read-helper-boundaries),
  [query sources](#query-sources), [named composition](#named-composition-helpers)
- Relationships: [joins](#joins), [aliases](#typed-table-aliases),
  [foreign keys](#optional-foreign-key-ddl)
- Schema: [constraints](#table-level-foreign-key-constraints),
  [indexes](#sqlite-partial-indexes), [defaults](#literal-server-defaults),
  [text capacity](#mariadb-text-capacity)
- Expressions: [arithmetic](#arithmetic-expression-types),
  [text and COALESCE](#coalesce-and-text-function-types), [CASE](#case-result-types),
  [named results](#named-result-contracts)

## Model states

A table model class is generic in its lifecycle state:

```python
from typing import ClassVar

from snekql.sqlite import (
    PENDING_GENERATION,
    Col,
    GenCol,
    Integer,
    Model,
    Pending,
    ReadType,
    Row,
    Text,
)


class User[S = Pending](Model[S]):
    __row_type__: ClassVar[ReadType[User[Row]]]
    id: GenCol[int] = Integer(
        primary_key=True,
        auto_increment=True,
        default=PENDING_GENERATION,
    )
    email: Col[str] = Text()
```

`Pending` is the default state for direct construction:

```python
pending_user = User(email="alice@example.com")  # User[Pending]
```

`Row` is the state returned by database reads:

```python
fetched_user = await tx.fetch_one(select(User).where(User.email.eq("x")))
# fetched_user: User[Row]; fetch_one raises NoResultError when absent
```

### Instance methods and `self`

Model classes are generic in their lifecycle state, so methods that assume a
specific state must say so on `self`. For a shared method, an explicit
`self: User[Pending] | User[Row]` or an application protocol can describe the fields
it needs. Arbitrary state-generic descriptor getters are not a supported contract.

```python
from typing import ClassVar

from snekql.sqlite import ReadType, Row


class User[S = Pending](Model[S]):
    __row_type__: ClassVar[ReadType[User[Row]]]
    id: GenCol[int] = Integer(primary_key=True, default=PENDING_GENERATION)
    email: Col[str] = Text()

    def insert_payload(self: User[Pending]) -> dict[str, str]:
        return {"email": self.email}

    def cache_key(self: User[Row]) -> str:
        return f"user:{self.id}"
```

A bare `User` means `User[Pending]`. `__row_type__` must name the same model in
Row state, for example `ClassVar[ReadType[User[Row]]]`. This witness supplies the
whole-model result of SELECT, RETURNING, and `complete`. It does not choose scalar,
tuple, or named result types. Runtime declaration checks validate the witness;
the checker does not reject every malformed declaration.

Direct construction is Pending-only, even when every generated field is supplied.
`User[Row](...)` is rejected. Use `complete(User, id=7, email="ada@example.com")`
for a logically validated Row snapshot without I/O. Supply all fields; defaults
are not filled, extra fields and generation markers are rejected. This validates
logical values, not wire-encoded storage. Keyword names and domains are checked
at runtime, not statically.

`is_complete(value)` checks recorded Row state and narrows its true branch. It
does not infer completeness from populated fields or prove database existence.
Insertion accepts only Pending values and does not mutate their lifecycle state.
Use `insert(user)` for one value, `insert_many(User, rows)` for a batch. Row values
from either SELECT/RETURNING or `complete` cannot be inserted.

Field reassignment is rejected by ty and raises `FrozenModelError` at runtime,
for both states. This is shallow freezing: nested JSON dict/list mutation remains
possible. SQL assignments such as `User.email.to("grace@example.com")` remain valid,
including assignments to generated columns where the backend permits them.

Module-level column annotations may refer to logical payload types declared later
in the module; snekql retries those unresolved hints after module population. In
a function-local scope, define payload types before the table model. Python does
not retain a safe late-binding namespace for names added to a function after the
model body, so snekql rejects that declaration immediately instead of caching an
unresolvable type.

## Backend-family isolation

Build each operation from one backend namespace. Models, query verbs,
configurations, Database, Transaction, joins, foreign keys, and Scaffold inputs
retain that namespace's backend family under static typing:

```python
from snekql import mariadb, sqlite

sqlite_query: sqlite.ClosedRead[SqliteUser[sqlite.Row]] = sqlite.ready(
    sqlite.select(SqliteUser)
)
mariadb_query: mariadb.ClosedRead[MariadbUser[mariadb.Row]] = mariadb.ready(
    mariadb.select(MariadbUser)
)

await sqlite_tx.fetch_all(mariadb_query)  # type error
sqlite.select(SqliteUser).join(MariadbUser, on=...)  # type error
sqlite.scaffold([MariadbUser])  # type error
```

The family coordinate is private. Application annotations keep the public forms
`Model[State]`, `ReadQuery[Scope, Result]`, `Write[Result]`, and `Transaction`
without a backend type argument. Import those names and every query verb from the
same backend namespace.

Static isolation supplements runtime validation. Dynamic inputs introduced via
`Any`, casts, or runtime model loading are still checked by backend verbs, joins,
foreign keys, Scaffold, Database verification, and Execution Plans.

## Executable query states

SELECT queries are executable immediately. Filters, ordering, limits, joins,
projections, grouping, and HAVING refine the query without an acknowledgment.
SELECT `.all()` remains a compatibility no-op, including before or after filters.

Query Readiness still protects mutations: `delete(...)` needs `.all()` or
`.where(...)`; `update(...)` needs both assignments and row scope, in either order.

```python
select(User)  # executable
select(User).limit(1)  # executable; zero or one SQL result rows
select(User).where(User.id.eq(1))  # executable; not proof of one row

delete(User)  # incomplete
delete(User).where(User.id.eq(1))  # executable

update(User).all()  # incomplete: no assignment
update(User).set(User.status.to("inactive"))  # incomplete: no row scope
update(User).set(User.status.to("inactive")).all()  # executable
update(User).where(User.id.eq(1)).set(User.status.to("inactive"))  # executable
```

`returning(...)` does not complete a write. Ty rejects incomplete mutations at
Transaction execution. Read helpers retain `Scope` and `Result`, or close scope
with `ready` after composition. Scope, backend, grouping, and other SQL checks
remain necessary; executable does not mean valid under every composition.

Fetch methods choose the consumption contract. `fetch_one` requires exactly one
result after SQL pagination; it never inserts a limit. `fetch_all` returns a list
even for `limit(1)`. Named queries, CTEs, UNION operands, and nested SELECTs need no
extra scope acknowledgment. Locking reads follow the same rule, so an unfiltered
MariaDB `for_update()` can lock every selected row. Transaction and dialect
restrictions still apply.

## Read helper boundaries

Keep scope in a reusable helper. Neither ordinary execution nor a scoped helper
needs `ready`:

```python
from snekql import sqlite


async def fetch_rows[Scope, Result](
    transaction: sqlite.Transaction,
    query: sqlite.ReadQuery[Scope, Result],
) -> list[Result]:
    return await transaction.fetch_all(query)


async def fetch_optional[Scope, Result](
    transaction: sqlite.Transaction,
    query: sqlite.OptionalRead[Scope, Result],
) -> Result | None:
    return await transaction.fetch_one_or_none(query)
```

For a result-only helper, finish composition first:

```python
def users() -> sqlite.ClosedRead[User[sqlite.Row]]:
    return sqlite.ready(sqlite.select(User).order_by(User.id.asc()))


def user_by_email(email: str) -> sqlite.ClosedOptional[User[sqlite.Row]]:
    return sqlite.ready(sqlite.select(User).where(User.email.eq(email)))
```

`ready` compiles and checks backend ownership without executing SQL. It returns
the same object. It does not repair missing joins or invalid composition, prove
that tables exist, or cache compilation for later execution. Closed annotations
permit execution and inspection, not further joins or filtering. A normal scoped
query cannot be directly assigned to `ClosedRead`; use `ready` at that boundary.
The closed aliases use `Never` scope, which does not mean an empty SQL FROM.

Optional reads distinguish an absent row from a present row. A nullable scalar
cannot supply this distinction because SQL NULL also becomes `None`. `ready`
preserves optional-fetch eligibility; it does not make nullable scalars eligible.
All read helper names are nonconstructible annotations.

A generic single-insert helper can retain its Pending owner and Row result:

```python
def insert_row[Owner: sqlite.Model[sqlite.Pending], Result: sqlite.Model[sqlite.Row]](
    pending: sqlite.PendingInput[Owner, Result],
) -> sqlite.Write[Result]:
    return sqlite.insert(pending).returning()
```

## Query sources

Use bare model declarations, such as `select(User)`, `update(User)`, or
`alias(User, AuthorRole, name="author")`. Native aliases and CTEs are also valid
read sources; they cannot be mutation targets. Ty rejects model instances and
structural lookalikes at these boundaries. Explicit lifecycle specializations
such as `User[Pending]` and `User[Row]` still pass ty in the tested source calls;
runtime builders reject them. Any/callable erasure can hide evidence, so runtime
checks remain necessary.

## `Col` and `GenCol`

Use `Col[T]` for normal persisted values. The pending and fetched value type is
`T`.

Use `GenCol[T]` for server-filled/generated values. Pending instances may have
`T | PendingGeneration`; fetched instances have `T`.

```python
pending_user = User(email="alice@example.com")
pending_user.id  # int | PendingGeneration

fetched_user: User[Row]
fetched_user.id  # int
```

`PENDING_GENERATION` is the singleton sentinel value for generated pending values that have
not been filled by the database yet.

### Nullability

When `nullable=` is omitted, snekql derives nullability from the field
annotation: `Col[str]` is `NOT NULL`, while `Col[str | None]` is nullable. An
explicit `nullable=True` or `nullable=False` is cross-checked against the
annotation, and contradictory declarations are rejected at class definition.

Named aliases follow the same rule, including alias chains, `Annotated` wrappers
and fixed-arity generic specialization:

```python
type OptionalInteger = int | None
type Identity[T] = T

value: Col[OptionalInteger] = Integer(default=None)
other: Col[Identity[int | None]] = Integer(nullable=True)
```

Inspection checks only field-level None membership. A `list[int | None]` is not
itself nullable. The declared logical annotation and its validators/serializers
stay intact; inspection never runs a validator on a synthetic None value.
Generic arguments and defaults supply the nullability facts of type parameters.
When unresolved references, field-level cycles, unsupported variadic parameters
or inspection depth prevent a decision about an alias, nullability remains
unknown. The existing unknown-result policy requires an explicit `nullable=`
flag or raises `ModelDeclarationError`. Such a flag does not make an invalid
logical type valid for subsequent Pydantic validation.

Earlier versions could infer NOT NULL for an optional named alias. Corrected
inference can expose nullability drift in an existing database. Review the
scaffold, write an explicit migration when needed, then verify again. Neither
model declaration nor verification alters existing tables. This change does not
expand JSON wire-marker support or normalize catalog server defaults.

```python
required: Col[str] = Text()  # NOT NULL
optional: Col[str | None] = Text(default=None)  # nullable and omittable
explicit: Col[str | None] = Text(nullable=True)  # nullable but required

bad: Col[str] = Text(nullable=True)  # rejected: type vs flag
bad2: Col[str | None] = Text(nullable=False)  # rejected: type vs flag
```

If a field annotation cannot be resolved, snekql keeps the conservative physical
default of `NOT NULL`. Hint resolution is per field, so one unresolved sibling
does not suppress validation for the rest of the model. Primary-key annotations
must always be non-optional.

## Query result shapes

The selected shape controls the runtime return type:

```python
await tx.fetch_all(select(User))
# list[User[Row]]

await tx.fetch_all(select(User.email))
# list[str]

await tx.fetch_all(select(User.email, User.status))
# list[tuple[str, str]]
```

`fetch_one(...)` carries an **exactly-one** contract: it returns the single
matching row in the selected shape, and raises `NoResultError` when no row
matches or `MultipleResultsError` when more than one does. Because absence is an
error rather than a `None` return, a single-value result keeps the column read
type — and a returned `None` there can only mean SQL `NULL`:

```python
await tx.fetch_one(select(User.email))
# str            (raises NoResultError / MultipleResultsError on 0 / >1 rows)

await tx.fetch_one(select(User))
# User[Row]
```

`fetch_one_or_none(...)` is the **zero-or-one** variant: it returns the row or
`None` when none matches, still raising `MultipleResultsError` on more than one.
It is offered only for model, tuple, and join selects, where `None` can only
mean a missing row:

```python
await tx.fetch_one_or_none(select(User))
# User[Row] | None

await tx.fetch_one_or_none(select(User.email, User.status))
# tuple[str, str] | None
```

Single-value selects are deliberately rejected by `fetch_one_or_none` (a type
error, and a `QueryConstructionError` at runtime): their `None` would
conflate a missing row with a SQL `NULL` value. For a zero-or-one single value,
use `fetch_all(...)` (the list is the presence channel: `[]` vs `[None]`) or
project a tuple that includes a non-nullable column. To take the first of
several rows on purpose, add `.limit(1)` and use `fetch_one`/`fetch_one_or_none`.

`fetch_chunks(..., size=N)` streams the same per-row shape as `fetch_all`, but
batched: it returns a `ChunkStream[RowT]` whose iteration yields
`list[RowT]` chunks of up to `N` rows. The element type tracks the selected
shape exactly as `fetch_all` does:

```python
async with tx.fetch_chunks(select(User), size=500) as stream:
    async for batch in stream:  # batch: list[User[Row]]
        ...

async with tx.fetch_chunks(select(User.email), size=500) as stream:
    async for batch in stream:  # batch: list[str]
        ...

async with tx.fetch_chunks(select(User.email, User.status), size=500) as stream:
    async for batch in stream:  # batch: list[tuple[str, str]]
        ...
```

`ChunkStream` is exported from the backend namespaces (`snekql.sqlite`,
`snekql.mariadb`) for typed annotations only. Do not construct it directly;
obtain one from `Transaction.fetch_chunks`.

All Query Runtime reads validate and decode database values by default, so their
return type preserves the selected logical shape. Passing `validate=False` is a
raw escape hatch: constraints and some logical conversions are skipped, and the
static result is therefore widened to `object` (`list[object]` for `fetch_all`,
`ChunkStream[object]` for `fetch_chunks`). Narrow a raw result explicitly before
using logical-type operations. The same rule applies to mutation `returning(...)`.
MIN/MAX honor this policy, including in scalar subqueries and chunked reads.
COUNT/SUM/AVG retain their numeric normalization under either policy; empty
MIN/MAX/SUM/AVG results are `None`.

## Insert conflicts

`on_conflict` pins its target columns and update assignments to the inserted
model. ty rejects a target or assignment from another model:

```python
from snekql.sqlite import DoNothing, DoUpdate, insert, insert_many

update_email = insert(User(email=email, status=status)).on_conflict(
    User.email,
    action=DoUpdate(User.status.to_inserted()),
)
# execute(update_email.returning()) returns User[Row]

ignore_email = insert_many(User, [User(email=email, status=status)]).on_conflict(
    User.email,
    action=DoNothing,
)
# execute(ignore_email) returns None
```

`DoUpdate` requires at least one assignment and accepts several. A literal
`.to(value)` assignment keeps the column's normal value type. `.to_inserted()`
needs no value because it refers to that column on the attempted insert.

`DoUpdate` keeps the normal `.returning(...)` result types. `DoNothing` rejects
`.returning(...)`: a SQLite conflict produces no row, which cannot satisfy the
single-insert returning type. Plain execution returns `None` for both actions.

MariaDB cannot encode an explicit conflict target. It checks every primary key
and unique index even though `on_conflict` remains typed to the named columns.
SQLite requires the named columns to match a primary key or unique index.

## Joins

A column may declare the model it references with `FKCol[Target, T]`. The
relationship is carried in the annotation, so it participates in type checking
at zero runtime cost:

```python
from typing import ClassVar

from snekql.sqlite import ReadType, Row


class User[S = Pending](Model[S]):
    __row_type__: ClassVar[ReadType[User[Row]]]
    id: GenCol[int] = Integer(
        primary_key=True,
        auto_increment=True,
        default=PENDING_GENERATION,
    )
    email: Col[str] = Text()


class Order[S = Pending](Model[S]):
    __row_type__: ClassVar[ReadType[Order[Row]]]
    id: GenCol[int] = Integer(
        primary_key=True,
        auto_increment=True,
        default=PENDING_GENERATION,
    )
    user_id: FKCol[User, int] = ForeignKey(User.id)
    note: Col[str] = Text()
```

A join condition is built from an FK column against its target with
`references(...)`. It only accepts a column of the referenced model whose read
type matches, so the condition is provably between related tables of compatible
key type:

```python
Order.user_id.references(User.id)  # ok
Order.user_id.references(User.email)  # type error: str column vs int FK
```

### General ON predicates

`join` and model-select `left_join` also accept ordinary `Predicate` values,
without requiring `FKCol` declarations:

```python
select(User).join(
    Order,
    on=Order.user_id.eq_col(User.id) & Order.note.ne("hidden"),
)
```

Predicates retain their owner types. ON accepts predicate owners from the FROM
anchor, preceding joins, and the newly joined model. An unrelated predicate
owner or a mixed-backend join is a type error, with runtime checks for dynamic
callers. Joining preserves Query Readiness and the existing result shapes.

The six `*_col` comparisons retain both column owners, including nullable RHS
columns and aliases. Scalar-subquery comparisons retain the outer column owner.
This catches a missing joined table, but can reject valid enclosing-table
correlation in a nested JOIN ON. Such a query currently needs a typing escape;
general correlation typing is not redesigned. Query Compilation still checks
references using each ON clause's scope, not the final join graph. Subqueries in ON inherit that
same scope, so neither direct comparisons nor nested correlations may reach a
later join. Aggregate filters directly in ON are rejected at construction.

A predicate may filter only one side of the join. It is explicit SQL, not a
foreign-key assertion. Existing `.references(...)` conditions retain their
relationship checks.

### Model-select joins

A model-select join accumulates a tuple of `Row` models. `left_join` makes
the right side optional:

```python
await tx.fetch_all(
    select(User)
    .join(Order, on=Order.user_id.references(User.id))
    .where(User.email.eq("a@b.c") & Order.note.eq("x")),
)
# list[tuple[User[Row], Order[Row]]]

await tx.fetch_all(
    select(User).left_join(Order, on=Order.user_id.references(User.id)),
)
# list[tuple[User[Row], Order[Row] | None]]
```

`where(...)` and `order_by(...)` accept predicates and orderings from any joined
table and reject columns from a table that is not in the query.

### Projection-select joins

A projection-select join keeps the projected columns as the result; the joined
table contributes only to the `FROM`/`JOIN` graph:

```python
await tx.fetch_all(
    select(User.email, Order.note).join(Order, on=Order.user_id.references(User.id)),
)
# list[tuple[str, str]]
```

Referencing — selecting or filtering — a table that was never joined is a type
error, caught at `fetch_all`/`fetch_one`:

```python
select(User.email, Region.code).join(Order, on=Order.user_id.references(User.id))
# Region is never joined: rejected when fetched
```

Projection-select `left_join(...)` is rejected by both the type checker and the
runtime because the query shape cannot make only nullable-side projected slots
optional. Use a model-select left join, where the whole right model becomes
`... | None`, or use an inner join for projections.

### Typed table aliases

A role marker gives each use of a table its own nominal scope type. The SQL
name alone is not a static identity:

```python
from snekql.sqlite import alias


class ManagerRole:
    pass


class ReviewerRole:
    pass


manager = alias(User, ManagerRole, name="manager")
reviewer = alias(User, ReviewerRole, name="reviewer")

select(manager).where(manager.column(User.email).eq("a@b.c"))  # Valid
select(manager).where(reviewer.column(User.email).eq("a@b.c"))  # Type error
select(manager).where(User.email.eq("a@b.c"))  # Type error
manager.column(Order.note)  # Type error
```

`alias` infers the model owner and Row result type. `column(...)` requires
an original descriptor from that model and retains its logical read and
comparison types. An alias select returns the original Row Model; a model
join appends that same model type, optional on the right of a left join. Alias
columns also retain scalar and tuple projection types.

The backend coordinate remains private. Generic helpers retain role scope through
`ReadQuery[Scope, Result]`. Finish composition before using `ready(query)` and a
`ClosedRead[Result]` execution-only annotation. Aliases are not mutation or schema
targets, and an alias-owned assignment cannot update the physical model.

Runtime checks supplement the types. SQL names must be distinct within visible
scopes, including enclosing queries, using case-insensitive comparison. A
model/role pair may appear only once per visible scope, even if two alias values
use different SQL names. Separate queries may reuse the same alias and role.
Right-hand comparison references and correlated references retain the existing
compilation-time validation described above.

### Optional foreign-key DDL

An `FKCol[...]` annotation controls typing only. Emitting an actual
`FOREIGN KEY` constraint (and including it in startup drift checks) is opt-in
per column by declaring it with `ForeignKey(...)`, which names the exact target
column. The column's storage class is derived from that target — never restated
— and the named target is cross-checked against the annotation at declaration
time:

```python
user_id: FKCol[User, int] = ForeignKey(User.id)  # references user(id)
owner_email: FKCol[User, str] = ForeignKey(User.email)  # references user(email)
ref_code: FKCol[Region, str] = Text()  # typed-only soft reference
```

The target must be a single-column primary key or independently unique column.
Membership in a composite primary key alone is insufficient. A typed-only
reference (an `FKCol` annotation with a plain storage specifier) keeps the
relationship available for joins without enforcing referential integrity.

### Table-level foreign-key constraints

Use `ForeignKeyConstraint` for ordered composite relationships. It is available
from both backend namespaces and does not change column construction or joins.

```python
from typing import ClassVar

from snekql import sqlite


class Account[S = sqlite.Pending](sqlite.Model[S]):
    __row_type__: ClassVar[sqlite.ReadType[Account[sqlite.Row]]]
    tenant_id: sqlite.Col[int] = sqlite.Integer(primary_key=True)
    account_id: sqlite.Col[int] = sqlite.Integer(primary_key=True)


class Entry[S = sqlite.Pending](sqlite.Model[S]):
    __row_type__: ClassVar[sqlite.ReadType[Entry[sqlite.Row]]]
    tenant_id: sqlite.Col[int] = sqlite.Integer()
    account_id: sqlite.Col[int] = sqlite.Integer()
    __foreign_keys__: ClassVar = [
        sqlite.ForeignKeyConstraint(
            tenant_id,
            account_id,
            references=(Account.tenant_id, Account.account_id),
            on_delete="CASCADE",
        ),
    ]
```

The declaration emits one `FOREIGN KEY (tenant_id, account_id) REFERENCES account
(tenant_id, account_id)`. Two separate scalar constraints are not equivalent:
they could allow values taken from different parent rows.

- `__foreign_keys__` is a list, snapshotted when the model is created. Each
  declaration is frozen. Overlapping and repeated constraints remain separate.
- Local columns belong to the declaring model. Targets belong to one table on
  the same backend. Within a self-referencing model, use its class-body column
  descriptors in `references`.
- Tuples are nonempty and equally sized, with no repeated member within either
  tuple. One-column constraints are allowed too.
- Targets must match a complete declared primary key or unique index in order.
  A prefix of a composite key is insufficient. A single-column `unique=True`
  target also qualifies.
- Storage matching is conservative: corresponding columns must use the same
  storage declaration, VARCHAR capacity, collation, and DECIMAL precision/scale.
  No storage is copied, coerced, or silently changed. Some combinations accepted
  by a backend are therefore rejected by the declaration interface.
- `on_delete` and `on_update` accept the same actions as scalar `ForeignKey`.
  `SET NULL` requires every local member nullable and outside the primary key.
  With default backend semantics, any NULL member bypasses the relationship
  check; this does not require the other members to be NULL.

Arity, ownership, storage, and candidate-key mistakes raise
`ModelDeclarationError` before database access. Backend row-size, index-key,
and engine limits still apply. Referenced tables and their unique indexes must
exist before creating the referencing table; order scaffold inputs accordingly.

Columns remain ordinary `Col` values. No `FKCol` annotation, automatic join,
relationship loading, or automatic migration is introduced. Scalar
`ForeignKey(Target.column)` keeps its storage-deriving behavior.

Scaffolding emits the declared constraints. Verification compares catalog
constraint groups, ordered pairs, multiplicity, and actions. Split or reordered
groups now cause drift even when their flattened pairs match. Referenced models
are not automatically added to the verification request. Primary-key ordering,
constraint names, MATCH, deferral, and cross-catalog target identity retain their
separate verification limits.

There are no constraint-name, MATCH, or deferral declaration options yet.

### SQLite partial indexes

`where=` limits an index to rows where its predicate is true. Use a synchronous
`__indexes__` classmethod to build predicates from bound columns:

```python
from typing import ClassVar, Self

from snekql import sqlite


class Account[S = sqlite.Pending](sqlite.Model[S]):
    __row_type__: ClassVar[sqlite.ReadType[Account[sqlite.Row]]]
    email: sqlite.Col[str] = sqlite.Text()
    active: sqlite.Col[bool | None] = sqlite.Integer()

    @classmethod
    def __indexes__(cls) -> list[sqlite.Index[Self]]:
        return [
            sqlite.Index(
                cls.email,
                unique=True,
                where=cls.active.eq(True),
                name="ux_active_email",
            ),
        ]
```

The factory runs once during class creation, after column metadata is bound and
frozen. Its returned list becomes an immutable schema snapshot. Existing
`__indexes__` lists remain supported; a factory can return ordinary and partial
indexes together. Async factories, async generators, and non-list results are
rejected. Use `Self` in the return annotation to preserve exact column ownership.
Alternatively, annotate `cls: type[Account[S]]` explicitly when returning
`list[sqlite.Index[Account[S]]]`.

Predicates use the bounded CHECK grammar: local Integer/Boolean/ordinary Text
comparisons, column comparisons, NULL tests, IN/NOT IN, BETWEEN, and AND/OR/NOT.
Predicate columns need not be index members. Raw SQL, arithmetic, functions,
subqueries, foreign owners, encoded JSON, and other storage domains are excluded.
Literals use column codecs and safe DDL quoting. MariaDB rejects `where=`.

Unlike CHECK, a partial-index predicate excludes both false and NULL results.
`unique=True` constrains only indexed rows. Inserts and updates can therefore
fail when they bring a duplicate into the subset. Native NULL and collation
semantics still apply; there is no Python-side uniqueness check.

A partial unique index never authorizes a foreign-key target. An independent
full key still can. Different named predicates and full indexes may share the
same indexed columns; duplicate declared member/predicate combinations remain
rejected. Supply distinct names to avoid generated-name collisions.

Verification reads the stored CREATE INDEX statement and compares recognized
predicate structure. Known changes drift; unsupported or unavailable predicates
remain unchecked. It does not prove arbitrary expression equivalence or predict
whether SQLite's optimizer will use the index. The existing column-only
`on_conflict(...)` interface cannot target a partial-only unique index because it
does not declare an ON CONFLICT target predicate. No upsert extension is included.

### MariaDB prefix indexes

Use `prefix_lengths` to index leading characters of ordinary text columns:

```python
from typing import ClassVar

from snekql import mariadb


class Document[S = mariadb.Pending](mariadb.Model[S]):
    __row_type__: ClassVar[mariadb.ReadType[Document[mariadb.Row]]]
    tenant_id: mariadb.Col[int] = mariadb.Integer()
    body: mariadb.Col[str] = mariadb.LongText()
    __indexes__: ClassVar = [
        mariadb.Index(
            tenant_id,
            body,
            prefix_lengths=(None, 128),
            name="ix_document_body",
        ),
    ]
```

The tuple has one entry per column, in order. `None` means the whole column;
a positive exact integer means that many characters, not UTF-8 bytes. Prefixes
require Text or LongText with a logical `str`, optionally nullable or Annotated.
Encoded JSON and other logical domains are excluded. LongText requires an explicit
prefix; it still cannot be a primary key or foreign-key target.

SQLite rejects `prefix_lengths` tuples, including all-None tuples. Omitting the
option preserves ordinary index declarations. Booleans, nonpositive lengths,
wrong tuple lengths, and prefixes exceeding VARCHAR capacity fail before IO.
Counts exceeding LONGTEXT's absolute capacity also fail. Server byte limits for
index keys still apply, especially for compound indexes. An accepted declaration
does not promise that MariaDB can create the index as requested.

`unique=True` enforces uniqueness of the indexed prefixes, subject to native
collation and NULL behavior. Different complete values can collide. Indexing a
prefix does not truncate stored values or change the column's codec limits.

Full and differently prefixed indexes may share columns when their names differ.
Duplicate declared member/prefix combinations remain rejected. Use explicit
names to avoid generated-name collisions. Declarations and bound index metadata
are immutable snapshots.

Any explicit prefix excludes an index from foreign-key candidate-key validation.
An independent full primary key or unique index can still authorize the target.
Catalog indexes with actual prefixes are not hidden as inferred FK-supporting
indexes. Normalized full-column catalog entries can still qualify for that
existing filtering rule.

MariaDB normalizes a VARCHAR prefix equal to its capacity into a full-column
catalog entry. Verification recognizes this equivalence while keeping the
original declaration for scaffold and conservative FK validation. Other changed
prefix lengths, order, uniqueness, or missing indexes remain drift. Verification
does not certify the original spelling of equivalent DDL.

This adds no expression indexes, custom index methods, sort direction, or
index-level collation. SQLite partial indexes use `where=` as described above.

### Literal server defaults

Pass `LiteralDefault(value)` through `default=` to declare a SQL DEFAULT rather
than a Python construction default. Both backend namespaces export the marker.

```python
from typing import ClassVar

from snekql import sqlite


class Job[S = sqlite.Pending](sqlite.Model[S]):
    __row_type__: ClassVar[sqlite.ReadType[Job[sqlite.Row]]]
    attempts: sqlite.GenCol[int] = sqlite.Integer(default=sqlite.LiteralDefault(0))
    status: sqlite.GenCol[str] = sqlite.Text(
        default=sqlite.LiteralDefault("pending"),
    )
```

`Job()` holds `PENDING_GENERATION` for these fields. INSERT omits them and the
database fills them. Fetch the row to obtain the generated values. Explicit
values override the default; explicit `None` inserts SQL NULL on nullable columns,
not the default. `default=0` remains a Python default and emits no SQL DEFAULT.
`CurrentTimestamp` keeps its existing behavior.

The marker is frozen. Its supported values are exact Python `int`, `bool`, `str`,
and `None`. Non-NULL values must match the column's logical type. The supported
storage families are Integer, Boolean, Text, and MariaDB LongText. Logical integer
and Boolean values use Integer or Boolean storage; logical strings use Text or
LongText. SQLite Boolean values use Integer storage. NULL defaults require nullable non-primary-key columns
in those families. Encoded JSON, temporal, Decimal, Real, and binary defaults are
not included. There is no raw SQL or additional server-function interface.

The model declaration validates values through the column's normal logical
validation and codec, then snapshots their encoded values. Invalid values,
integer overflow, invalid Unicode, and text exceeding a declared VARCHAR length
fail before IO. A server default requires `GenCol` and cannot combine with
`default_factory` or auto-increment. `LiteralDefault` is not an UPDATE assignment
marker. For generated foreign-key members, use ordinary `GenCol` declarations
plus table-level `ForeignKeyConstraint` declarations, not a new generated FK alias.

Scaffold emits safely quoted literals. MariaDB text uses an explicit UTF-8 hex
conversion, independent of backslash SQL modes. Apply the DDL through a reviewed
migration; declaring a default does not backfill existing rows.

Verification compares supported encoded literal values, preserving literal types.
It accepts cosmetic parentheses and supported integer spellings, but does not
infer SQL affinity coercions or evaluate expressions. Unsupported catalog
expressions remain unchecked. MariaDB cannot distinguish implicit NULL from an
explicit DEFAULT NULL clause; verification reports that limitation separately.

### Named CHECK constraints

Declare CHECKs in a synchronous `__checks__` classmethod. snekql calls it once,
after binding and freezing the table's columns. Keep it pure and deterministic;
it runs during class creation, often at import time. Returning a list directly
in the class body is not supported because `ty` treats those field variables as
dataclass fields rather than bound column descriptors.

```python
from typing import ClassVar

from snekql import sqlite


class Account[S = sqlite.Pending](sqlite.Model[S]):
    __row_type__: ClassVar[sqlite.ReadType[Account[sqlite.Row]]]
    balance: sqlite.Col[int] = sqlite.Integer()
    ceiling: sqlite.Col[int] = sqlite.Integer()

    @classmethod
    def __checks__(cls) -> list[sqlite.CheckConstraint[Account[S]]]:
        return [
            sqlite.CheckConstraint(
                cls.balance.gte(0) & cls.balance.lte_col(cls.ceiling),
                name="ck_account_balance",
            ),
        ]
```

MariaDB uses the same interface. `CheckConstraint` is frozen, and snekql snapshots
the returned list into immutable schema expressions. Scaffold and verification
do not rerun the method.

Supported operands are local integer, Boolean, and ordinary Text columns with
matching Python logical types. Integer-backed Boolean values are supported too.
JSON-encoded values, Real, Decimal, LongText, temporal values, and other encoded
domains are excluded initially. Corresponding columns in column comparisons
must have matching logical types, storage types, and collations.

Supported predicates:

- `eq`, `ne`, `gt`, `gte`, `lt`, `lte`, and their `_col` forms;
- `is_null`, `is_not_null`;
- `in_(first, second, ...)`, `not_in(...)`, and `between(low, high)`;
- `&`, `|`, and `~` for AND, OR, and NOT.

Names are required SQL identifiers, unique within the table. Literals must have
the operand's logical type and fit its wire codec. snekql encodes and quotes DDL
literals directly, never by replacing placeholders in query SQL. MariaDB text
literals use explicit UTF-8 hex conversion to avoid SQL-mode-dependent escaping.
There is no raw SQL, arithmetic, function, aggregate, subquery, or cross-table
CHECK interface.

Declaration validation raises `ModelDeclarationError` before database access.
Predicate construction retains its normal query-construction errors. Backend
identifier and storage limits still apply. Async declaration methods are rejected.

CHECK enforcement belongs to the database, not the Python model constructor.
A CHECK rejects false, but **SQL NULL passes**. Use nonnullable columns or include
`is_not_null()` when NULL must fail. Text comparisons follow backend collation
rules; snekql does not normalize values in Python.

Apply scaffold output through an explicit migration. Verification checks declared
names and recognized expression structure. Missing declared names and changed
supported expressions are drift. Unrecognized expressions, ambiguous duplicate
names, and unmanaged checks remain unchecked. Unchecked facts alone neither warn
nor fail strict verification. Existing data and enforcement settings are not
certified; see [schema drift](schema-drift.md#check-verification).

### Nullable foreign keys

Nullability and omittability are separate. `nullable=True` permits SQL `NULL`
and requires `T | None` in the annotation. Without a default, callers must still
provide the field:

```python
from typing import ClassVar

from snekql.sqlite import ReadType, Row


class RequiredChild[S = Pending](Model[S]):
    __row_type__: ClassVar[ReadType[RequiredChild[Row]]]
    parent_id: FKCol[User, int | None] = ForeignKey(
        User.id,
        nullable=True,
    )


RequiredChild(parent_id=None)  # ok
RequiredChild(parent_id=1)  # ok
RequiredChild()  # type error: parent_id is required
```

Add `default=None` when omission should supply `None`:

```python
from typing import ClassVar

from snekql.sqlite import ReadType, Row


class OmittableChild[S = Pending](Model[S]):
    __row_type__: ClassVar[ReadType[OmittableChild[Row]]]
    parent_id: FKCol[User, int | None] = ForeignKey(
        User.id,
        nullable=True,
        default=None,
    )


OmittableChild()  # ok: parent_id defaults to None
```

Both forms materialize `parent_id` as `int | None` on Row Models. The
difference applies only while constructing Pending Models.

### Defaulted typed-only and self references

Plain storage declarations support `FKCol` with a literal default or
`default_factory`. The annotation retains the target used by `.references(...)`;
plain storage alone does not emit a foreign-key constraint.

For an omittable, nullable self reference with eager declaration checks, use the
existing table-level constraint:

```python
from typing import ClassVar

from snekql import sqlite


class Account[S = sqlite.Pending](sqlite.Model[S]):
    __row_type__: ClassVar[sqlite.ReadType[Account[sqlite.Row]]]
    account_id: sqlite.GenCol[int] = sqlite.Integer(
        primary_key=True,
        auto_increment=True,
        default=sqlite.PENDING_GENERATION,
    )
    manager_id: sqlite.FKCol[Account, int | None] = sqlite.Integer(default=None)
    __foreign_keys__: ClassVar = [
        sqlite.ForeignKeyConstraint(manager_id, references=(account_id,))
    ]


account = Account()  # manager_id defaults to None
Account.manager_id.references(Account.account_id)  # target-checked join condition
```

The same spelling works in `mariadb`. Omit `__foreign_keys__` for a typed-only
relationship. Without a default, the nullable constructor argument remains
required. Ordinary `Col` and `GenCol` annotations do not gain `.references(...)`.
Aliased self-joins still use `.eq_col(...)` with the aliased target column.

Direct class-body `ForeignKey(account_id, default=None)` remains unsupported by
the checked typing contract. The bare descriptor has not acquired its model
owner, and ty also represents the initializer as a synthetic dataclass field.
Class-qualified references to already declared models, such as
`ForeignKey(Account.account_id, default=None)`, remain supported. No permissive
self-target overload bypasses target or logical-type checks.

### Callable self-reference targets

Both backends also accept a zero-argument callback with an explicit Python
`default`. This form derives storage and emits a scalar foreign-key constraint:

```python
from typing import ClassVar

from snekql import sqlite


class Account[S = sqlite.Pending](sqlite.Model[S]):
    __row_type__: ClassVar[sqlite.ReadType[Account[sqlite.Row]]]
    account_id: sqlite.GenCol[int] = sqlite.Integer(
        primary_key=True,
        auto_increment=True,
        default=sqlite.PENDING_GENERATION,
    )
    manager_id: sqlite.FKCol[Account, int | None] = sqlite.ForeignKey(
        lambda: Account.account_id,
        default=None,
    )


account = Account()
Account.manager_id.references(Account.account_id)
```

The callback must synchronously return a column on the annotated target model.
Use a class-qualified name, not the bare class-body descriptor. The target
annotation must resolve at declaration time to self or an existing model; this
is not a general cross-model forward-reference facility. Callbacks should be
side-effect-free and must not construct models or queries as part of resolution.
No application globals or closure cells are rewritten.

**This opts the model into deferred binding.** Declaration options and logical
nullability are fixed when the class is created. The callback runs once when
construction, schema/query metadata use, or a derived-storage inspection first
requires the binding. For these models, index/check hooks and target-dependent
constraint validation also wait until binding. Ordinary models keep eager
validation. A query or encoded value cannot consume a failed model.

The target identity, backend and keyable storage are checked before its immutable
storage snapshot is exposed. Concurrent first uses share one resolution. Success
and failure are cached; changing names or globals does not retry a failed binding
or redirect a successful one. Cyclic storage dependencies and invalid callback
results raise `ModelDeclarationError`, possibly wrapped by the calling query
operation. Do not force binding from a class decorator before Python has assigned
the class name.

Callbacks require an explicit `default=None` or a compatible Python value.
Omitted defaults, `default_factory`, server defaults and `PENDING_GENERATION`
are not supported for this form. The omitted-default restriction preserves target
checking on ty; the checker currently misses some wrong-target declarations
without it. Existing `ForeignKey(Target.column, ...)` overloads are unchanged.
For required self-FKs or eager error timing, use `FKCol` with ordinary storage and
`ForeignKeyConstraint` instead.

### Referential actions

`ForeignKey(...)` takes optional `on_delete=` and `on_update=` referential
actions, rendered verbatim as `ON DELETE`/`ON UPDATE` clauses on the constraint.
The accepted actions are `"CASCADE"`, `"RESTRICT"`, `"SET NULL"`, and
`"NO ACTION"`:

```python
# Owned rows that are meaningless once the parent is gone:
job_id: FKCol[Job, str] = ForeignKey(Job.id, on_delete="CASCADE")
# Detach the child instead of deleting it (nullable but still required):
owner_id: FKCol[User, int | None] = ForeignKey(
    User.id,
    nullable=True,
    on_delete="SET NULL",
)
```

Because snekql enforces foreign keys, deleting a parent with no action declared
fails while children still reference it; `on_delete="CASCADE"` lets a single
`DELETE` remove the parent and its children. An action left unset renders no
clause, leaving the database default (`NO ACTION`). Both backends render the
same clauses.

`SET DEFAULT` is intentionally unsupported: SQLite honors it but InnoDB silently
ignores it, so it is not portable. `"SET NULL"` is rejected at declaration on a
`NOT NULL` or primary-key foreign-key column, where the action could never fire.
On both backends, `verify(...)` compares managed targets and actions and reports
a model/live mismatch as drift. MariaDB normalizes its equivalent `RESTRICT`
and `NO ACTION` catalog spellings.

### Composite primary keys

Marking more than one column `primary_key=True` declares a composite
(multi-column) primary key — the natural shape for a pure join table whose
identity *is* the referenced column pair:

```python
from typing import ClassVar

from snekql.sqlite import ReadType, Row


class TeamMember[S = Pending](Model[S]):
    __row_type__: ClassVar[ReadType[TeamMember[Row]]]
    team_id: FKCol[Team, int] = ForeignKey(Team.id, primary_key=True)
    user_id: FKCol[User, int] = ForeignKey(User.id, primary_key=True)
    role: Col[str] = Text()
```

This emits a single table-level `PRIMARY KEY (team_id, user_id)` constraint in
declaration order. Every column of a composite key is always `NOT NULL`, so
declaring such a column `nullable=True` is rejected at declaration time, as is
combining `auto_increment` with a composite key (`AUTOINCREMENT` requires a
single `INTEGER PRIMARY KEY`).

## Runtime-checked constraints

Most validity rules are enforced by the type checker, but a few cannot be
expressed in Python's type system and are checked at query construction or
compilation instead. They raise loudly — they are never silent unsoundness — but
the type checker will not flag them ahead of time:

- **Mixed aggregate projections need `group_by`.** `select(col, agg)` type-checks
  as an ordinary tuple select, but every non-aggregate projected column must
  appear in `group_by(...)`; a missing one raises `QueryCompilationError` at
  fetch. The type checker cannot track which columns are grouped.
- **`limit`/`offset` bounds.** Their parameter is `NonNegativeInt`, which `ty`
  sees as plain `int`, so a negative literal type-checks; a negative value raises
  `QueryConstructionError` at construction.
- **Bulk insert column sets.** `insert_many(User, rows)` fixes the destination
  and Row result even for an empty batch. Ty rejects wrong-model and Row inputs;
  runtime checks also reject them after type erasure. Every row must supply the
  same columns, which compilation checks rather than the type checker.

A scalar subquery (`scalar(...)`), by contrast, **is** reflected in the types: it
evaluates to SQL `NULL` on an empty/no-match result set, so its projected slot is
typed `... | None` and decodes a no-match to `None` rather than raising, even over
a `NOT NULL` inner column. A projection must start with a real column, aggregate,
or dialect expression to establish its `FROM` scope; scalar subqueries may appear
only in later slots.

## MariaDB text capacity

```python
from typing import ClassVar

from snekql import mariadb


class Article[S = mariadb.Pending](mariadb.Model[S]):
    __row_type__: ClassVar[mariadb.ReadType[Article[mariadb.Row]]]
    title: mariadb.Col[str] = mariadb.Text(length=200)
    summary: mariadb.Col[str | None] = mariadb.Text(length=2000, default=None)
```

`mariadb.Text(length=...)` declares VARCHAR character capacity. The default is
255; valid lengths are exact integers from 1 to 16,383. Boolean, floating-point,
and string arguments are not coerced. The character set remains `utf8mb4`;
collation defaults to `utf8mb4_bin`. Server row and index limits still apply.

This changes scaffolding and the expected catalog shape, not an existing table.
Write and apply a migration to change deployed storage. `ForeignKey(Target.col)`
inherits a text target's length. Python defaults and factories retain their
existing meaning, and this option does not truncate values or add Python
max-length validation. Strict-mode server writes reject over-capacity values.
SQLite `Text()` has no equivalent `length` keyword.

### MariaDB native long text

```python
from typing import ClassVar


class Document[S = mariadb.Pending](mariadb.Model[S]):
    __row_type__: ClassVar[mariadb.ReadType[Document[mariadb.Row]]]
    body: mariadb.Col[str] = mariadb.LongText()
    note: mariadb.Col[str | None] = mariadb.LongText(default=None)
```

`LongText()` uses native LONGTEXT, defaulting to utf8mb4_bin, with ordinary Text
codecs, including LIKE predicates and lexical-order safety checks. Python
defaults and factories work as with `Text()`. Values beyond VARCHAR capacity are
not truncated; server packet and storage limits still apply.

There is no `length`, `primary_key`, `unique`, or `index` argument. Table-level
indexes containing LongText require an explicit [character prefix](#mariadb-prefix-indexes).
Physical foreign keys targeting LongText remain rejected. SQLite has no LongText
constructor; its `Text()` already uses TEXT.


### Column collations

```python
sqlite.Text(collation="NOCASE")
mariadb.Text(length=255, collation="utf8mb4_unicode_ci")
mariadb.LongText(collation="utf8mb4_general_ci")
```

Accepted names are exact and case-sensitive at declaration:

| Declaration | Choices | Default |
| --- | --- | --- |
| SQLite Text | `BINARY`, `NOCASE`, `RTRIM` | `BINARY` |
| MariaDB Text and LongText | `utf8mb4_bin`, `utf8mb4_general_ci`, `utf8mb4_unicode_ci` | `utf8mb4_bin` |

Other names and non-string values raise `ModelDeclarationError`. Arbitrary
collations, character-set changes, and expression/index-level COLLATE declarations
are not supported. `Json()` is unchanged. Physical `ForeignKey` columns inherit
the target's collation. LongText supports explicit prefix indexes, but not primary
keys or foreign-key targets.

The database applies collation during comparisons and uniqueness checks. Python
values are not case-folded, trimmed, or otherwise normalized. SQLite `NOCASE`
folds ASCII letters only. `RTRIM` ignores trailing ASCII spaces, not tabs.
MariaDB's supported `_ci` collations are case- and accent-insensitive. MariaDB
`utf8mb4_bin` is case-sensitive but ignores trailing spaces in equality, unlike
SQLite `BINARY`. Do not assume cross-backend comparison equivalence. SQLite LIKE
has separate behavior and does not follow a column's collating function.
Comparisons between differently collated columns use backend coercion rules and
can fail; snekql does not insert an implicit COLLATE expression.

Changing the declaration changes scaffolding and verification expectations, not
live schema. Review existing values for newly equivalent keys, review affected
indexes and foreign keys, and apply an explicit migration. Verification checks
column collations, not arbitrary index/expression overrides or complete semantic
compatibility.

## Backend namespaces

Every public symbol is imported from a backend namespace. Pick `snekql.sqlite`
or `snekql.mariadb` and import the whole surface from it -- the dialect-neutral
verbs as well as that backend's `Model` and column declarations:

```python
from typing import ClassVar

from snekql import mariadb, sqlite
from snekql.sqlite import PENDING_GENERATION, Pending


class SqliteUser[S = Pending](sqlite.Model[S]):
    __row_type__: ClassVar[sqlite.ReadType[SqliteUser[sqlite.Row]]]
    id: sqlite.GenCol[int] = sqlite.Integer(
        primary_key=True,
        auto_increment=True,
        default=PENDING_GENERATION,
    )


class MariadbUser[S = Pending](mariadb.Model[S]):
    __row_type__: ClassVar[mariadb.ReadType[MariadbUser[mariadb.Row]]]
    id: mariadb.GenCol[int] = mariadb.Integer(
        primary_key=True,
        auto_increment=True,
        default=PENDING_GENERATION,
    )
```

Backend namespaces expose distinct model bases and column constructor functions,
so backend-specific options can evolve without pretending the dialects are
portable. The functions are PEP 681 field specifiers, which lets `ty` infer
required and defaulted constructor fields.

## Mixed-backend safety

Table models carry backend identity. `db.verify(...)` rejects a model whose
backend does not match the runtime config, and `Transaction` rejects a query
built from another backend's model before SQL is executed. (Initialization is
connect-only and takes no models, so a wrong-backend deploy is caught at the
first `verify` or query, not at init.) Both namespaces expose the same
non-generic `SchemaVerificationResult`; backend-family witnesses remain internal
and do not appear in deployment-tooling annotations.

`ty` can see the backend namespace types where they are explicit, and runtime
checks cover the remaining cases that Python's type system cannot express yet.

## Import path

There is no flat `snekql.<symbol>` surface. Import every public symbol from a
backend namespace; the package root only exposes the `sqlite` and `mariadb`
namespace handles:

```python
from snekql.sqlite import Database, Pending, Text, select
```

Each namespace's exports are curated in its own `__all__`, and the package
root's `__all__` lists only `mariadb` and `sqlite`. Keeping the dialects in
separate namespaces stops auto-imports from landing on the wrong backend.

## Stability contract

The supported public API is intentionally small. Treat the following as the
compatibility surface; everything else is an implementation detail that can
change without notice.

**Supported import surface:**

- `snekql.sqlite` and `snekql.mariadb` — import every symbol from a namespace's
  top level (e.g. `from snekql.sqlite import select, Text`). Each namespace's
  `__all__` is the contract.
- `snekql.testing.mariadb` — the Temporary MariaDB Test Server support, curated
  in its own `__all__`.

**Implementation detail (do not import, may change without notice):**

- Any module or name beginning with an underscore (`snekql._common`,
  `snekql._query_compile`, and the rest of the `snekql._*` modules).
- Backend *submodules*, even though they are not underscored:
  `snekql.sqlite.config`, `snekql.sqlite.verbs`, `snekql.sqlite.runtime`, and
  their MariaDB peers. Their public symbols are re-exported through the
  namespace top level; the submodule paths are not a supported import surface.
  (Each namespace imports its `_dialect_sql` module only to register its query
  Dialect for SQL inspection — see
  [ADR 0004](adr/0004-dialect-blind-core-with-open-ast-dialect-expressions.md).)

**Read helpers preserve scope.** Use `ReadQuery[Scope, Result]` for an executable
read and `Write[Result]` for an executable mutation. For a result-only read helper,
return `ready(query)` as `ClosedRead[Result]`. The
state-specific builder classes and
concrete expression nodes are private implementation vocabulary. Build queries
through `select`, `insert`, `insert_many`, `update`, and `delete`; obtain `Predicate`,
`Aggregate`, `Scalar`, `JoinOn`, `OrderBy`, and `Assignment` values from
model/column methods and expression factories. Those names are
non-constructible annotations.

`Predicate`, `Scalar`, `Aggregate`, and `ColumnRef` annotations bind their backend
family through the namespace you import. Their public type arguments are
unchanged. A `sqlite.Scalar[...]` helper cannot return a MariaDB scalar, even when
the scalar's inner query was correctly built through `mariadb.scalar`.

The witness survives boolean composition, scalar comparisons, IN/NOT IN queries,
computed values, aliases, output labels, and CTE rebinding. Named SELECT bindings
also check family identity; their keyword schema, value domains, and token
identity still require runtime validation. These checks do not make scalar
subqueries legal in SQL positions that the backend forbids.

`exists` and `not_exists` return `Predicate[Never]`. Scalar factories likewise
use `Never` for their outer owner: inner tables do not become joined outer tables.
The separate family witness still prevents mixing namespaces. Correlation scope
remains subject to Query Compilation.

Use `ColumnRef[OwnerT, T]` when a helper accepts a read-only model column. It
supports equality comparisons and projection while intentionally omitting
mutation operations. A scalar built from such a projection retains its comparison
value domain; using the helper does not permit comparisons against unrelated types:

```python
def user_filter[T](
    column: ColumnRef[User[Pending], T],
    value: T,
) -> Predicate[User[Pending]]:
    return column.eq(value)


def user_projection[T](
    column: ColumnRef[User[Pending], T],
) -> ReadQuery[User[Pending], T]:
    return select(column)
```

Read helper annotations and `Write` are aliases rather than runtime classes, so
do not construct them or use them with `isinstance`. Incomplete writes do not
satisfy `Write`; finish their row scope and assignments before storing them at
an application seam. An annotated query remains
executable through `Transaction`:

```python
async def load_users[Scope](
    tx: Transaction,
    query: ReadQuery[Scope, User[Row]],
) -> list[User[Row]]:
    return await tx.fetch_all(query)
```

Projection and `returning(...)` overloads preserve up to eight selected values.
Wider calls are rejected statically; project a model or split the query instead.

**Error contract.** The exceptions in the `SnekqlError` hierarchy re-exported
from each namespace are the catchable contract — catch `SnekqlError` for a
catch-all, or a more specific subclass for targeted handling (see
[error-handling.md](error-handling.md)). The hierarchy is defined in
`snekql/errors.py`, but catch the names re-exported from the backend namespace.

**Warning contract.** Advisory warnings are part of the same public surface: the
`SnekqlWarning` hierarchy (currently `LexicalDatetimeWarning`) is re-exported
from each namespace so applications can filter by category. See
[error-handling.md](error-handling.md#warnings).

The [1.0 compatibility policy](compatibility.md) treats typing-only regressions
as breaking changes and defines deprecation periods. It is a prospective contract,
not a claim that 1.0 has shipped.

**Pre-1.0 note.** While snekql is on `0.x`, the namespace surface is the
stability target but may still change between minor versions. Breaking changes
are called out in `CHANGELOG.md`.

## Type-checkable examples

The repository keeps a focused public typing example in:

- `examples/typed_queries.py`
- `tests/test_public_typing.py`

Run:

```sh
uv run ty check examples/typed_queries.py tests/test_public_typing.py
```


## Arithmetic expression types

Native numeric `.add`, `.sub`, and `.mul` operations retain their query-source
owner and result domain. SQL nullability follows both operands, including nested
expressions. Executable reads retain `ReadQuery[Scope, Result]`; writes retain
`Write[Result]`. Use `ready` for result-only closed read helpers.

| Operands | Result |
| --- | --- |
| `int`, `int` | `int` |
| `int`, `int | None` | `int | None` |
| `int | None`, `int` | `int | None` |
| `float`, `float` | `float` |
| Either floating operand nullable | `float | None` |
| Numeric expression, literal `None` | Nullable numeric result |

An integer expression accepts integer literals; a floating expression accepts
floating and integer literals. Integer and floating column/expression domains
cannot be mixed. Python treats bool as an int subtype, so runtime checks reject
boolean operands that static typing admits. Storage compatibility also requires
runtime checks because `Col[int]` alone does not distinguish INTEGER from a
text-encoded integer.

`.to_expr(...)` accepts columns and expressions from the assignment's own model.
It rejects incompatible numeric types and nullable-to-non-null assignments.
Non-null expressions can fill nullable columns. Alias role owners remain
distinct, and alias-owned assignments cannot target the original model.

The compiler also rejects reads of other columns assigned by the same UPDATE.
The type system does not track those statement-wide dependencies. These checks
traverse nested arithmetic as well as direct column reads.

Literal `.to(...)` validation remains unchanged. Computed values are evaluated
by the database, so the expression's numeric result contract does not promise
that every Python validator attached to the target column will pass. See the
README's arithmetic section for overflow and storage constraints.


## COALESCE and text function types

`coalesce` supports native `int`, `float`, and `str` domains. A non-null input
remains non-null regardless of the fallback. For nullable inputs, a non-null
fallback removes nullability; a nullable fallback preserves it. A literal
`None` is a nullable fallback, not a value that changes the result domain.

`lower()` accepts `str` and `str | None`, returning the same nullability.
`char_length()` accepts the same inputs and returns `int` or `int | None`.
Its result can participate in arithmetic and numeric `.to_expr()` assignments.
Text expressions also support `.to_expr()` with matching native text columns.

Overloads reject cross-domain fallbacks and incompatible assignments. Runtime
checks reject JSON-encoded strings despite their logical `str` annotation.
Integer literals accepted by floating COALESCE are bound as floats; expressions
from integer columns are not silently converted to floating expressions.


## CASE result types

`case(condition, then=..., otherwise=...)` requires both branches. Its owner
comes from the condition's query source. Branch columns and expressions must
have that same owner. Backend namespace factories enforce their backend family,
including nominal alias roles.

Non-null branches of the same native domain produce `int`, `float`, or `str`.
A nullable branch or literal `None` makes that result optional. The type system
does not infer non-nullability from the condition. Calling `coalesce` with a
non-null fallback can remove it explicitly.

Python permits integer literals in float annotations. CASE normalizes those
literals to floating bindings after validation, while invariant expression
contracts reject mixing integer and float columns. Boolean literals and two
literal NULL branches require runtime rejection. Column comparisons retain both
owners statically; CASE also validates ownership at runtime for erased inputs.
Row-local restrictions exclude subqueries and aggregates.

## Named result contracts

`select(Model).project(Result, **bindings)` returns a query whose row type is the
plain Pydantic `BaseModel` subclass `Result`. The same operation is available
after model joins. This replaces positional projection overloads with one
result-type parameter, so nine or more fields retain the full named result type.

Use `ReadQuery[Scope, Result]`, or `ClosedRead[Result]` after `ready`, for read
helpers. Named projections, grouping, and HAVING need no `.all()` or `.where(...)`
acknowledgment. Query backend identity survives the result contract, which itself
is reusable across backends.

`.returning_as(Result, **bindings)` preserves write cardinality and readiness:

| Operation | Executable helper annotation |
| --- | --- |
| Single INSERT | `Write[Result]` |
| Bulk INSERT | `Write[list[Result]]` |
| Supported UPDATE/DELETE RETURNING | `Write[list[Result]]` |

Python typing cannot check arbitrary keyword bindings against a Pydantic
class's declared fields. Result objects are statically typed; binding labels,
source ownership, known logical domains, and left-join nullability are runtime
construction checks. Constraints and domains that cannot be inferred safely are
validated after decoding each row. No expression is treated as a caller-asserted
result type, and `validate=False` does not bypass this final validation.

LEFT JOIN fields need optional result annotations even if their source column
is NOT NULL. Named row objects support `fetch_one_or_none`, including a one-field
row whose field is nullable. The object is distinct from the missing-row `None`.
A named row query is not a scalar-subquery contract, even with one projected
field. Use a scalar/tuple query when those result semantics are required.

Bindings use Python field names rather than Pydantic aliases. All fields must be
bound explicitly, including defaulted and optional fields. Extra bindings and
case-insensitive duplicate labels fail rather than silently changing shape.


## Named composition helpers

Both namespaces provide nonconstructible `Cte[Source, Result, Role,
NonNullableSource=Source]` and `NamedOperand[Result]` annotations. See
[named recursive callbacks](recursive-ctes.md#named-callbacks) for a complete
example and nullable-anchor rules.

`Cte` retains source/role identity and output nullability while hiding the backend
coordinate. `NamedOperand` retains the backend, exact named result class and
completed readiness required by UNION and recursive member composition. It does
not expose fluent editing or direct Transaction execution after scope erasure.
Use `ReadQuery[Scope, Result]`, or `ClosedRead[Result]` after `ready`, for
execution helpers instead.

[All guides](README.md)

# snekql

snekql is a Python async-first query builder and query runtime for SQL.
It gives applications explicit SQL-shaped operations, typed
model declarations, runtime validation, startup schema checks, and transaction-
based execution without becoming an ORM.

## Install

```sh
uv add snekql                 # Query Builder and backend namespaces only
uv add 'snekql[aiosqlite]'    # SQLite Query Runtime
uv add 'snekql[aiomysql]'     # MariaDB Query Runtime
```

snekql requires Python 3.14 or newer. Database drivers are optional backend
extras. The base `snekql` install is enough for importing the Query Builder and
backend namespaces, but runtime initialization requires the matching backend
extra.

## Bundled docs and examples

Installed packages include copyable docs and examples:

```sh
snekql --agent-docs
snekql --llms
snekql --examples
snekql --example basic
snekql example typed_queries
python -m snekql --agent-docs
```

## Quick start

```python
from __future__ import annotations

from datetime import datetime
from pathlib import Path

from snekql import sqlite
from snekql.sqlite import (
    Database,
    Fetched,
    Pending,
    insert,
    select,
)


class User[S = Pending](sqlite.Model[S, "User[Fetched]"]):
    id: sqlite.GenCol[int] = sqlite.Integer(
        primary_key=True,
        auto_increment=True,
        default=sqlite.PENDING_GENERATION,
    )
    email: sqlite.Col[str] = sqlite.Text(unique=True)
    status: sqlite.Col[str] = sqlite.Text(default="active")
    created_at: sqlite.GenCol[datetime] = sqlite.Text(default=sqlite.CurrentTimestamp)


MIGRATIONS = {
    "0001_create_user": (
        'CREATE TABLE "user" ('
        '"id" INTEGER PRIMARY KEY AUTOINCREMENT, '
        '"email" TEXT NOT NULL, '
        '"status" TEXT NOT NULL, '
        '"created_at" TEXT NOT NULL DEFAULT '
        "(strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))"
        ") STRICT"
    ),
    "0002_user_email_unique": (
        'CREATE UNIQUE INDEX "ux_user_email" ON "user" ("email")'
    ),
}


async def main() -> None:
    # The migration SQL is generated once during development, reviewed, and
    # committed as a literal. Runtime model changes cannot alter its checksum.
    async with await Database.initialize(
        sqlite.Config(
            database=Path("app.db"),
            pool_size=5,
            acquire_timeout=30.0,
        ),
    ) as db:
        await db.migrate(MIGRATIONS)
        await db.verify_migrations(MIGRATIONS)
        await db.verify([User], policy="strict")
        async with db.transaction(timeout=5.0) as tx:
            await tx.execute(insert(User(email="alice@example.com")))
            # fetch_one is exactly-one: it raises NoResultError if the row is
            # absent, so the result is never None.
            user = await tx.fetch_one(
                select(User).where(User.email.eq("alice@example.com")),
            )
            print(user.email)
```

## Model declaration

Table models are declared through a backend namespace such as `sqlite` or
`mariadb`. Application-created instances are `Pending`; database reads return
`Fetched` instances.

```python
from datetime import datetime

from snekql import sqlite
from snekql.sqlite import Fetched, Pending


class AuditLog[S = Pending](sqlite.Model[S, "AuditLog[Fetched]"]):
    __tablename__ = "audit_log"

    id: sqlite.GenCol[int] = sqlite.Integer(
        primary_key=True,
        auto_increment=True,
        default=sqlite.PENDING_GENERATION,
    )
    message: sqlite.Col[str] = sqlite.Text()
    created_at: sqlite.GenCol[datetime] = sqlite.Text(
        default=sqlite.CurrentTimestamp,
    )
```

Rules to remember:

- Keep models, query verbs, configurations, Transactions, joins, foreign keys,
  and Scaffold calls in one backend namespace; `ty` rejects cross-family use.
- `Col[T]` is a normal persisted column.
- `GenCol[T]` is server/generated; pending values may be `PENDING_GENERATION`, fetched
  values are `T`.
- If `__tablename__` is omitted, class names become snake_case table names.
- Models are immutable after construction/materialization.
- Column descriptor metadata is finalized with the model declaration and is
  immutable afterward.
- Fetched models are produced by database reads only.
- Instance methods that assume a state should annotate `self`, e.g.
  `self: User[Pending]` or `self: User[Fetched]`.

### State-specific instance methods

Model classes are generic in state. If a method uses pending-only or
fetched-only assumptions, write that state on `self`:

```python
class User[S = Pending](sqlite.Model[S, "User[Fetched]"]):
    id: sqlite.GenCol[int] = sqlite.Integer(
        primary_key=True, default=sqlite.PENDING_GENERATION
    )
    email: sqlite.Col[str] = sqlite.Text()

    def insert_payload(self: User[Pending]) -> dict[str, str]:
        return {"email": self.email}

    def cache_key(self: User[Fetched]) -> str:
        return f"user:{self.id}"
```

A bare `User` means `User[Pending]`; spell `User[Fetched]` for methods that
require a materialized row.

### Ruff/Pyflakes unused-import note

`Fetched` appears in model declarations as part of a string forward reference,
for example `sqlite.Model[S, "User[Fetched]"]`. Type checkers resolve that name,
but Ruff's Pyflakes `F401` check does not count names inside string literals as
import usage. If a project imports `Fetched` only for those model self-types,
allow that import in Ruff:

```toml
[tool.ruff.lint.pyflakes]
allowed-unused-imports = [
  "snekql.sqlite.Fetched",
  "snekql.mariadb.Fetched",
]
```

## Column types and logical types

A column is two coordinates (see ADR 0005):

- The **column type** is the constructor. It names a *storage primitive* of the
  backend and decides where the value is physically stored — nothing else.
- The **logical type** is the field annotation (`Col[T]`). It is the single
  source of truth for the column's Python value and all validation, which is
  delegated to Pydantic.

Read a declaration as a sentence — `created_at: Col[datetime] = Text()` is "a
datetime, stored as text." The codec that bridges the two is *derived* from the
pair; you never name it.

SQLite exposes exactly its four storage classes as column types:

- `sqlite.Integer` — `INTEGER` storage. A `Col[bool]` stores as `0`/`1`.
- `sqlite.Real` — `REAL` storage.
- `sqlite.Text` — `TEXT` storage. Holds `Col[str]`, `Col[UtcDatetime]`
  (canonical UTC millisecond text), `Col[ZonedDatetime]` (canonical instant and
  timezone identity), `Col[datetime]` (raw ISO text), `Col[uuid.UUID]` (string
  form), or a `Col[pydantic.Json[T]]` payload.
- `sqlite.Blob` — `BLOB` storage for `Col[bytes]`.

JSON uses Pydantic's marker, not a snekql type: annotate
`Col[pydantic.Json[T]] = Text()`. Serialization and validation both run through
`T`, so any type Pydantic can validate (`datetime`, Pydantic models,
`list[Model]`, ...) round-trips, not just `dict`/`list`/primitives. Optional `Json[T] | None` and
`Json[T | None]` fields also accept decoded payloads. See
[optional JSON fields](docs/optional-json.md) for metadata and SQL NULL semantics.

MariaDB additionally exposes its native types as column types — `mariadb.Json`,
`mariadb.Boolean`, `mariadb.DateTime`, `mariadb.Uuid` (native `UUID`), and
`mariadb.Decimal(precision, scale)` (native `DECIMAL(p,s)`). To store a UUID as
raw bytes instead, pair `Col[uuid.UUID]` with `Blob()`. Existing text-encoded
MariaDB UUID Blob rows need an explicit [data migration](docs/binary-uuid-migration.md)
before binary UUID predicates can match them.

There is no declaration-time storage/logical compatibility check: any pairing is
allowed and an impossible one fails at encode/decode via a Pydantic error.
Timezone policy is the logical type's job — over a primitive storage class
(SQLite `Text()`, or `Integer()` with an epoch type) a naive `datetime`
round-trips naive. Use `UtcDatetime` for database timestamp columns: it rejects
naive values, normalizes aware values to UTC milliseconds, and serializes SQLite
text so `=`, `ORDER BY`, and ranges compare by instant. Bare SQLite
`Col[datetime] = Text()` and `Col[AwareDatetime] = Text()` columns emit a
suppressible `LexicalDatetimeWarning` because their raw ISO text compares
lexically. The one exception is MariaDB's native `DateTime`, which stores
offset-less UTC text: it has no way to record a naive value's zone, so encoding a
naive `datetime` there is rejected with a `ModelValidationError` rather than
silently assuming the writer's local zone. Attach a timezone (or annotate
`Col[UtcDatetime]`) for those columns.

Use `ZonedDatetime` when the timezone itself has domain meaning:

```python
from datetime import datetime
from zoneinfo import ZoneInfo

from snekql.sqlite import Col, Text, ZonedDatetime

starts_at: Col[ZonedDatetime] = Text(nullable=False)
value = ZonedDatetime(datetime(2026, 7, 1, 8, tzinfo=ZoneInfo("America/New_York")))
```

It preserves the UTC instant plus the exact IANA key or fixed offset. Equality
requires both to match, so `America/New_York` differs from a fixed `-04:00` even
when they identify the same instant. Store it with `Text()` on both backends;
MariaDB `DateTime()` cannot retain timezone identity. Equality, membership, and
unique indexes are supported. Ordering, ranges, `MIN`, and `MAX` raise
`QueryConstructionError`; use `UtcDatetime` when the database must compare
chronologically.

Decimal storage has the same two-coordinate rule:

- Use `Col[CanonicalDecimal] = Text()` when you need portable exact decimal
  identity/equality over text storage. It normalizes `Decimal("1.50")` to
  `Decimal("1.5")`, `Decimal("1E+2")` to `Decimal("100")`, and negative zero to
  zero, then stores minimal plain text. Equality, `IN`, and unique indexes are
  safe; lexical ordering and range predicates are not.
- On SQLite, store integer minor units (`Col[int] = Integer()`, e.g. cents) when
  the database must order, range-filter, or aggregate decimal quantities.
- On MariaDB, use `Col[decimal.Decimal] = mariadb.Decimal(precision, scale)` for
  native numeric equality, ordering, range predicates, and aggregation. Stored
  values that would overflow or require rounding for the declared
  `(precision, scale)` are rejected before they reach the driver. Native Decimal
  `SUM` comparison bounds accept exact finite `Decimal` values beyond the input
  column's precision and scale; they are not rounded to that column's shape.
  Integer `SUM` bounds likewise preserve exact integer serialization beyond
  signed BIGINT, while individual writes retain their 64-bit limit. SQLite's
  integer SUM overflow and parameter limits are unchanged.

Bare `Col[decimal.Decimal] = Text()` emits `LexicalDecimalWarning` on both
backends because Pydantic's default decimal text can represent the same value in
multiple ways and still sorts lexically, not numerically. Suppress it only when a
custom `Annotated[..., Canonical]` or `Annotated[..., OrderPreserving]` logical
type owns the wire-form invariant.

Because the logical type is whatever Pydantic can validate, the UUID-version
aliases work as drop-in logical types and add version validation for free:
`Col[pydantic.UUID4] = Text()`, or `Col[pydantic.UUID7] = mariadb.Uuid()`.
Pydantic ships `UUID1`/`UUID3`/`UUID4`/`UUID5`/`UUID6`/`UUID7`/`UUID8`; all of
them store the same as a plain `Col[uuid.UUID]` and round-trip through both
`Text` and MariaDB's native `Uuid`. Pair the annotation with a matching factory
(`Col[pydantic.UUID7] = mariadb.Uuid(default_factory=uuid.uuid7)`) — nothing
forces the factory and the annotation to agree, so a mismatched version fails
construct-time validation.

All column constructors accept `unique=True` for column-level unique indexes.
SQLite allows multiple `NULL` values in a unique index, so use a non-optional
annotation such as `Col[str]` when uniqueness should also require a value.
Primary-key columns reject `unique=True`; use a table-level unique `Index` when
a composite-key component also needs independent uniqueness.

A scalar `ForeignKey(Target.column)` requires a single-column primary key,
`unique=True` on a non-primary column, or a singleton `Index(column, unique=True)`.
Membership in a composite primary key or multi-column unique index is not enough.
This rule applies during scaffolding and schema verification on both backends.
Do not add a singleton unique constraint if repeated values are legitimate;
choose an independently unique target instead. Composite foreign-key declarations
are not introduced by this rule, and existing schemas are not rewritten.

For a plain non-unique single-column index, pass `index=True` instead — sugar
for an `Index(col)` entry in `__indexes__` (named `ix_<table>_<col>`). It is
rejected on primary-key columns and alongside `unique=True`, since both are
already indexed.

A *server default* is declared by passing a marker as the column's `default`:
`sqlite.CurrentTimestamp` and `mariadb.CurrentTimestamp` are the only v1 server
defaults. The marker means the database computes the value, so the field is
valid only on `GenCol` columns, is omittable at construction (it is `PENDING_GENERATION`
until the database fills it), and accepts an explicit value when you pass one.

To refresh a column to the server clock on *update*, pass the same marker to an
update assignment: `update(Doc).set(Doc.edited_at.to(CurrentTimestamp))`. It
renders the backend's current-timestamp SQL inline (no bound parameter) and is
identical on SQLite and MariaDB. SQLite has no native `ON UPDATE`, so this keeps
the refresh explicit at the call site -- include it in each update that should
bump the timestamp.

## Indexes

Use the backend namespace `Index(...)` in `__indexes__` for table-level indexes:

```python
from snekql import sqlite
from snekql.sqlite import Fetched, Pending


class User[S = Pending](sqlite.Model[S, "User[Fetched]"]):
    email: sqlite.Col[str] = sqlite.Text(unique=True)
    status: sqlite.Col[str] = sqlite.Text()
    tenant_id: sqlite.Col[int] = sqlite.Integer()

    __indexes__ = [
        sqlite.Index(status),
        sqlite.Index(tenant_id, email, unique=True),
        sqlite.Index(tenant_id, name="ix_user_tenant_custom"),
    ]
```

Index declarations accept column descriptors only. Names are inferred as
`ix_<table>_<columns>` or `ux_<table>_<columns>` unless `name=` is supplied. A
column-level `index=True` collides with an equivalent `Index(col)` here and is
rejected as a duplicate.

## Queries

Queries are immutable. Chaining returns new query objects.

```python
from snekql.sqlite import delete, insert, select, update

select(User).all()
select(User.email).where(User.status.eq("active"))
select(User.email, User.status).where(User.email.like("%@example.com"))

insert(User(email="alice@example.com"))

update(User).set(User.status.to("disabled")).where(
    User.email.eq("alice@example.com"),
)

delete(User).where(User.email.eq("retired@example.com"))
delete(User).all()  # explicit full-table delete
```

Inserts can handle a primary-key or unique-index conflict atomically. `DoUpdate`
accepts one or more assignments. `.to_inserted()` takes the value from the row
whose insert conflicted, while `.to(...)` assigns a literal or
`CurrentTimestamp`:

```python
from snekql.sqlite import DoNothing, DoUpdate, insert

insert(User(email=email, name=name, status=status)).on_conflict(
    User.email,
    action=DoUpdate(
        User.name.to_inserted(),
        User.status.to("active"),
    ),
)

insert(User(email=email, name=name, status=status)).on_conflict(
    User.email,
    action=DoNothing,
)
```

SQLite compiles these actions as `ON CONFLICT (...) DO UPDATE` or `DO NOTHING`.
MariaDB compiles them as `ON DUPLICATE KEY UPDATE`. MariaDB checks every primary
key and unique index, so its SQL cannot limit detection to the columns passed to
`on_conflict`; those columns select the no-op assignment used for `DoNothing`.
On SQLite, the target columns must match a primary key or unique index.

`DoNothing` cannot be combined with `.returning(...)` because SQLite may return
no row. `DoUpdate` supports `.returning(...)` for single and bulk inserts.

Filtering is explicit: `select`, `update`, and `delete` must choose exactly one
of `.where(...)` or `.all()` before execution. Predicates use methods such as
`.eq(...)`, `.ne(...)`, `.is_null()`, `.in_(...)`, `.like(...)`,
`.gt(...)`/`.gte(...)`/`.lt(...)`/`.lte(...)`, and `.between(low, high)`; Python
comparison operators are not part of the v1 API.

Combine predicates with `|` (OR), `&` (AND), and `~` (NOT); use parentheses to
group. Repeated `.where(...)` calls AND together, so `&` is mainly useful inside
an OR. Python's `and`/`or`/`not` keywords are rejected — a predicate raises if
used as a boolean.

```python
# WHERE status = 'active' OR status = 'trialing'
select(User).where(User.status.eq("active") | User.status.eq("trialing"))

# WHERE tenant_id = 1 AND (status = 'active' OR email LIKE '%@vip.com')
select(User).where(
    User.tenant_id.eq(1) & (User.status.eq("active") | User.email.like("%@vip.com")),
)

# WHERE NOT (status = 'disabled')
select(User).where(~User.status.eq("disabled"))
```

### Arithmetic and atomic updates

Use `.add(...)`, `.sub(...)`, and `.mul(...)` on native numeric columns and
expressions. Operands may be literals or columns/expressions from the same query
source, including an alias. Chaining preserves parentheses and binds literals.
Expressions work in SELECT projections and WHERE/ON predicates.

`.to_expr(...)` assigns the computed value inside UPDATE. `.to(...)` retains its
existing Python-literal validation:

```python
query = (
    update(Inventory)
    .set(
        Inventory.quantity.to_expr(Inventory.quantity.sub(amount)),
        Inventory.version.to_expr(Inventory.version.add(1)),
    )
    .where(
        Inventory.id.eq(item_id)
        & Inventory.quantity.gte(amount)
        & Inventory.version.eq(expected_version)
    )
)

async with database.transaction() as transaction:
    changed = await transaction.execute(query)
# With a unique item_id, changed == 1 means this version was claimed.
```

Validate application inputs such as a positive purchase amount separately. The
stock check, decrement, and version increment execute in one statement, without
an application-side read/modify/write. A stale version or insufficient stock
changes no rows.

The initial numeric contract is deliberately narrow:

- `int` requires native INTEGER storage; `float` requires native REAL storage.
  Text-encoded numbers, bool, Decimal, durations, and custom numeric types are
  rejected. Division and mixed integer/real column expressions are unsupported.
- Integer literals must fit signed 64 bits. Floating literals must be finite.
  Float expressions also accept integer literals, matching Python's float
  annotations. Boolean literals are rejected at runtime.
- Either nullable operand makes the result nullable. A literal `None` is SQL
  NULL, not zero. Assignments require matching numeric domains. A non-null
  expression may target nullable storage, but not the reverse.
- Arithmetic follows backend numeric behavior, not Python unlimited integers.
  SQLite may promote overflowing integer arithmetic to REAL; integer projection
  decoding rejects that result rather than truncating it. MariaDB integer
  overflow remains an execution error. Floating arithmetic uses backend
  precision and overflow behavior.
- Computed writes use database constraints, not Python field validators. Final
  storage validation cannot detect every overflowed or rounded intermediate
  expression. Guard operand ranges when exact integer arithmetic is required.
- Compilation rejects an expression reading another column assigned by the same
  UPDATE, even inside nested arithmetic. This avoids MariaDB's assignment-order
  behavior differing from SQLite. Independent stock/version updates are valid.
- Expression assignments currently support UPDATE only, not `DoUpdate` conflict
  actions. Aliases remain query-only, not mutation targets.

### COALESCE and text functions

Native integer, float, and text values support `.coalesce(fallback)`. The fallback
may be a compatible literal or a column/expression from the same query source.
A non-null input or fallback makes the result non-null. Two nullable operands
retain a nullable result.

```python
select(User.nickname.coalesce("anonymous").lower()).all()  # str
select(User.nickname.char_length()).all()  # int | None for nullable nickname
select(User.nickname.char_length().coalesce(0).add(1)).all()  # int

update(User).set(
    User.nickname.to_expr(User.nickname.coalesce("anonymous").lower()),
).where(User.id.eq(user_id))
```

`lower()` preserves text nullability. `char_length()` returns `int` or
`int | None`. Both require native text storage, not JSON-encoded strings or
text-encoded non-string values. Text `.to_expr()` assignments follow the same
ownership, nullability, dependency, and database-validation rules as numeric
assignments. Grouped projections must group every column read by an expression.

These functions retain backend behavior. SQLite renders `LENGTH`, which counts
characters only up to the first NUL; MariaDB renders `CHAR_LENGTH`, which counts
all characters, not bytes. SQLite's built-in `LOWER` handles ASCII casing;
MariaDB casing depends on its character set and collation. Neither function
promises Python string semantics or identical Unicode casing across backends.

For floating COALESCE expressions, integer literal fallbacks are bound as floats
so a missing input still produces the promised float result. Integer and float
column/expression operands remain distinct. No caller-supplied function names
or result-type assertions are accepted.

### CASE expressions

Both namespaces export `case(condition, then=..., otherwise=...)`. It builds a
searched SQL CASE with an explicit fallback:

```python
from snekql.sqlite import case, select

select(case(User.score.gte(100), then="gold", otherwise="standard")).all()
select(
    case(User.score.gte(100), then=User.nickname, otherwise=None)
    .coalesce("anonymous")
    .lower()
).all()
```

TRUE selects `then`; FALSE or SQL UNKNOWN selects `otherwise`. Branches accept
native integer, float, or text literals, columns, and expressions. They must
share a value domain and query source. Either nullable branch makes the result
nullable, even when the condition logically excludes NULL. Two literal NULL
branches are rejected because they do not identify a result domain. Integer
literals in a floating CASE are validated and bound as floats; integer and
floating column/expression branches cannot be mixed.

CASE results compose with arithmetic, COALESCE, text functions, comparisons,
and `.to_expr()` assignments. Nested CASE is supported. The initial condition
contract is row-local: plain columns and native value expressions from one
query source, including compound predicates. Subqueries, aggregates, and
multi-source conditions are excluded. Aliases retain their own source identity.

Grouping and UPDATE dependency checks include condition reads and both branches,
including nested expressions. A branch that would not execute for today's data
still counts as a dependency. Comparisons such as `.gt_col(expression)` preserve
bindings and check the right-hand expression against the current query scope.

### Named projections

Use a plain Pydantic `BaseModel` as a result contract when positional tuples are
awkward or a query needs more than eight projected values. It is not a table
model and declares no storage, primary key, or schema.

```python
from pydantic import BaseModel
from snekql.sqlite import Select, select


class UserSummary(BaseModel):
    id: int
    name: str


def summaries() -> Select[UserSummary]:
    return (
        select(User)
        .project(
            UserSummary,
            id=User.id,
            name=User.name,
        )
        .all()
    )


async with database.transaction() as transaction:
    rows = await transaction.fetch_all(summaries())  # list[UserSummary]
```

Keyword names identify result fields; values are query columns, aggregates,
scalar subqueries, or supported dialect expressions. Binding order chooses the
SQL projection order but does not change which result field receives each value.
There is no library arity cap for named results, although database limits still
apply. Existing scalar, tuple, and table-model results remain unchanged.

Build joins before calling `.project(...)`. Fields from the nullable side of a
LEFT JOIN must accept `None`, including alias columns whose physical storage is
NOT NULL. Filters do not refine that declared nullability. Named queries retain
`where`, `all`, `order_by`, `group_by`, `having`, `distinct`, `limit`, and `offset`.
They work with eager fetches and `fetch_chunks`. A named row containing a NULL
field remains distinguishable from no row in `fetch_one_or_none`.

Every declared result field needs exactly one binding, including fields with
Python defaults. Extra or missing bindings and labels differing only by case
are rejected. Labels are quoted SQL identifiers and use Python field names,
not Pydantic validation/serialization aliases. Table models and `RootModel`
are not named result contracts. A one-field named row is still a row object;
use a scalar select, not a named projection, for a scalar subquery.

Known logical domains and nullability are checked during construction. Source
codecs decode UUIDs, JSON, dates, and other logical values before the result
model validates them strictly. Value constraints, opaque expression domains,
and complex annotation compatibility are checked against actual rows.
`validate=False` can skip source-column validators, but never named result
validation. Invalid result rows raise `ModelValidationError` without including
Pydantic input values or validator messages.

### Named RETURNING results

Use `.returning_as(Result, **bindings)` on supported writes:

```python
query = insert(User(name="Ada")).returning_as(
    UserSummary,
    id=User.id,
    name=User.name,
)

async with database.transaction() as transaction:
    created = await transaction.execute(query)  # UserSummary
```

Bindings must be columns of the written model. Named RETURNING has the same
validation and arity rules as named SELECT. A single insert returns one result
object. Bulk inserts and SQLite UPDATE/DELETE return lists. Empty bulk inserts
remain no-ops returning `[]`. Existing `DoUpdate` conflict actions work;
`DoNothing` still cannot be combined with RETURNING.

SQLite supports named INSERT, UPDATE, and DELETE RETURNING. MariaDB supports
named INSERT RETURNING; this library still rejects MariaDB UPDATE/DELETE
RETURNING before IO. On UPDATE/DELETE, a later `.returning(...)` replaces the
named contract with the usual scalar, tuple, or whole-model result.

### Joins

`join(..., on=...)` and model-select `left_join(..., on=...)` accept ordinary
predicates as well as FK-column `.references(...)` conditions. No foreign-key
declaration is required for a predicate join:

```python
select(User).left_join(
    Order,
    on=(
        Order.user_id.eq_col(User.id)
        & Order.tenant_id.eq_col(User.tenant_id)
        & Order.status.ne("cancelled")
    ),
).all()
# Select[tuple[User[Fetched], Order[Fetched] | None]]
```

ON supports column comparisons, literal filters, `&`, `|`, `~`, and subqueries.
Bindings use the column's normal codec. Conditions may filter only one side;
they do not assert that a foreign-key relationship exists. An ON filter on a
left join keeps unmatched left rows, unlike the same filter in WHERE.

Each ON clause can reference the FROM anchor, preceding joins, and its newly
joined table, but not later joins. Nested subqueries inherit that scope.
Right-hand column references and correlations are checked during compilation.
Aggregates cannot filter ON directly; use an aggregate subquery instead.

Joins preserve readiness, so choose `.all()` or `.where(...)` before execution.
Projection inner joins keep their selected result types. Projection left joins
remain unsupported because their nullable result slots cannot yet be typed.

### Table aliases and self-joins

Use a role marker class to distinguish aliases statically, and `name=` to choose
an SQL identifier. Both backend namespaces export `alias`:

```python
from snekql.sqlite import alias


class ManagerRole:
    pass


manager = alias(User, ManagerRole, name="manager")

query = (
    select(User)
    .left_join(
        manager,
        on=User.manager_id.eq_col(manager.column(User.id)),
    )
    .all()
)
# Select[tuple[User[Fetched], User[Fetched] | None]]
```

`manager.column(User.email)` retains the column's value type and codec while
referencing `manager` in SQL. Pass an original column of the aliased model;
columns from another model or alias are rejected. `select(manager)` returns
original `User[Fetched]` instances. Alias columns also support projections,
ordering, comparisons, and aggregates.

Give every repeated role a distinct marker class and SQL name. Aliases can be
reused in separate queries, but the same model/role pair cannot appear twice
in one visible scope. Names must be ASCII SQL identifiers and must not collide
case-insensitively with another visible source, including enclosing queries.
Compilation rejects collisions rather than silently shadowing a correlated
reference.

Aliases are immutable, query-only values. They do not declare tables or change
model metadata. Mutation and schema operations reject aliases, and assignments
from alias columns cannot target the underlying model. Scope checks distinguish
an alias from its original table and from other roles of that table. As with
ordinary columns, right-hand `*_col` references are checked during compilation.

### Subqueries

A select can be nested inside another query as a subquery:

```python
from snekql.sqlite import exists, not_exists, scalar, select

# IN / NOT IN against a single-column subquery
select(User).where(
    User.id.in_subquery(select(Order.user_id).where(Order.amount.gt(100))),
)

# EXISTS / NOT EXISTS, correlated to the outer row via a column comparison
select(User).where(
    exists(select(Order.id).where(Order.user_id.eq_col(User.id))),
)
select(User).where(
    not_exists(select(Order.id).where(Order.user_id.eq_col(User.id))),
)

# A scalar subquery used in a projection (or as a comparison operand)
select(
    User.id,
    scalar(select(Order.amount.sum()).where(Order.user_id.eq_col(User.id))),
).all()
```

`in_subquery`/`not_in_subquery` and `scalar(...)` require a single-column
select; `exists`/`not_exists` accept any select. The `*_col` comparisons
(`.eq_col`, `.ne_col`, `.gt_col`, `.gte_col`, `.lt_col`, `.lte_col`) compare a
column against another column or a scalar subquery, which is how a correlated
subquery references the outer query. A reference to a table in neither the
subquery nor an enclosing query is rejected when the query compiles.

### Inspecting the generated SQL

Use `query.compile()` for structured inspection without a `Database` or
transaction:

```python
from snekql.sqlite import CompiledQuery

compiled: CompiledQuery = select(User.email).where(User.status.eq("active")).compile()
compiled.sql  # 'SELECT "email" FROM "user" WHERE ("status" = ?)'
compiled.params  # ('active',)
compiled.backend  # 'sqlite'
```

Both backend namespaces export `CompiledQuery`. Its fields are frozen, and
`params` is an ordered tuple of dialect-encoded bindings. SQLite uses `?`
placeholders; MariaDB uses `%s` and backtick-quoted identifiers. The query's
models determine the backend; compilation cannot retarget a query.

Compiled output is inspection-only. Pass the original query to a Transaction,
not `CompiledQuery`. Compilation neither executes SQL nor includes private
execution plans, row decoders, or result-cardinality policy. It does not verify
that tables exist on a server. Incomplete queries raise `QueryCompilationError`.
Empty bulk inserts also raise because they have no model or SQL to compile,
even though executing an empty bulk insert is a no-op.

`repr(compiled)` and `str(compiled)` redact bound values as `<redacted:N>`.
Accessing `.params` explicitly reveals them. SQL text remains visible, including
identifiers and any literals supplied by custom dialect expressions.

#### Debug text

Unlike compiled output, query `repr()` and `str()` expose parameter values.
Use them only for deliberate debugging, not production logging.

Any query object renders its own SQL through `repr()` and `str()`, resolving the
dialect from its model's backend — no `Database` or transaction needed. Because
queries are immutable, the object you hold after composing (`query =
query.where(...)`) already carries the full state, so inspecting it shows the
final SQL.

```python
query = select(User).where(User.status.eq("active"))
query = query.where(User.email.like("%@example.com"))

repr(query)
# <SelectModelQuery: SELECT ... FROM "user"
#  WHERE ("status" = ?) AND ("email" LIKE ?) | params=('active', '%@example.com')>

print(query)  # str(): the parameterized form plus an inlined-literals form
# -- parameterized (executes):
# SELECT ... WHERE ("status" = ?) AND ("email" LIKE ?)
# -- params: ('active', '%@example.com')
#
# -- inlined literals (approximate, not executed):
# SELECT ... WHERE ("status" = 'active') AND ("email" LIKE '%@example.com')
```

The parameterized form is what executes. The inlined form substitutes the
encoded parameters as SQL literals for pasting into a database console; it is
approximate and must not be executed. A query that has not yet chosen
`.where(...)`/`.all()` renders as `<SelectModelQuery incomplete: ...>` rather
than raising, so it is always safe to `repr` a query in a debugger. Such a
builder cannot be passed to a typed Transaction or stored as `Select[Row]` until
it becomes executable.

### Explaining query plans

`await transaction.explain(query)` asks the active backend for a query plan.
It does not apply the query's writes. The query must be a complete builder
from the Transaction's backend, not `raw(...)` or a `CompiledQuery`.

```python
from snekql.sqlite import ExplainResult

async with db.transaction() as transaction:
    plan: ExplainResult = await transaction.explain(
        select(User.email).where(User.status.eq("active"))
    )

plan.backend  # 'sqlite'
plan.columns  # ('id', 'parent', 'notused', 'detail')
for row in plan.rows:
    print(dict(zip(plan.columns, row, strict=True)))  # Deliberate inspection
```

Both namespaces export frozen `ExplainResult` with `.backend`, `.columns`,
and `.rows`. Columns are a tuple of native column names. Rows are a tuple of
row tuples in column order, with native driver values and no model decoding.
SQLite returns `EXPLAIN QUERY PLAN` output, which can be empty for writes.
MariaDB returns native optimizer columns such as `select_type`, `key`, `rows`,
and `Extra`. Column sets, row order, estimates, and detail text depend on the
query and server version. There is no portable optimizer schema.

| Backend | `explain(query)` | `explain_analyze(query)` |
| --- | --- | --- |
| SQLite | `EXPLAIN QUERY PLAN` for SELECT, INSERT, UPDATE, DELETE | Rejected |
| MariaDB | `EXPLAIN` for SELECT, UPDATE, DELETE without RETURNING | `ANALYZE` for the same supported queries |

`explain_analyze` **executes the query**, including UPDATE and DELETE. It returns
execution statistics instead of application rows. MariaDB calls this statement
`ANALYZE`, not `EXPLAIN ANALYZE`; its output includes observed statistics such
as `r_rows` and `r_filtered`. SQLite's unrelated `ANALYZE` command is never used
as a substitute. MariaDB INSERT plans are outside this interface's supported
statement set.

```python
# MariaDB only. This DELETE really runs and commits on normal transaction exit.
async with db.transaction() as transaction:
    plan = await transaction.explain_analyze(
        delete(User).where(User.status.eq("disabled"))
    )
```

There is no automatic rollback or savepoint around ANALYZE. It uses the active
Transaction's normal commit, rollback, locking, and operation-deadline rules.
Even plain EXPLAIN performs database IO and can acquire metadata locks.
For MariaDB `FOR UPDATE` queries, its optimizer can also acquire row locks;
EXPLAIN and ANALYZE of these queries require a read-write Transaction. Use
`.compile()` when inspection must perform no IO or acquire no locks.

Incomplete queries, empty bulk inserts, and unsupported statement combinations
raise `QueryCompilationError` before query IO. Backend mismatches raise
`DatabaseRuntimeError`. Transaction lifecycle errors remain unchanged.

Plan cells can contain sensitive values. Result `repr` and `str` show only the
backend and column/row counts; accessing `.rows` or `.columns` reveals the
native output. EXPLAIN execution logs and driver-error text omit SQL and bound
values even with `parameter_visibility="values"`. This does not redact a
caller's own logging or server-side instrumentation.

## Runtime

`Database.initialize(...)` is the only public construction path and is
**connect-only**: it opens connectivity and a connection pool and does no schema
work. Select the backend with its namespace config. The legacy SQLite keyword
form remains supported for compatibility, but new code should use `sqlite.Config`.

```python
from pathlib import Path

from snekql import sqlite
from snekql.sqlite import Database


db = await Database.initialize(
    sqlite.Config(database=Path("app.db"), pool_size=5),
)
# MIGRATIONS is the committed literal chain from the quick start above.
await db.migrate(MIGRATIONS)
await db.verify_migrations(MIGRATIONS)
await db.verify([User])

memory_db = await Database.initialize(
    sqlite.Config(database=":memory:"),
)
```

A `Database` is an async context manager, so the runtime is closed for you on
block exit (including when the body raises) — `async with await
Database.initialize(...) as db:`. Call `await db.close()` directly only when you
manage the lifecycle by hand.

snekql logs through the standard library `logging` module. Every snekql logger
is a child of the `snekql` logger (`snekql.runtime`, `snekql.sqlite.runtime`,
…), so an application controls all snekql output from one place:

```python
import logging

# Route snekql logs wherever the app sends its own logs.
logging.basicConfig(level=logging.INFO)

# Or silence snekql while keeping the rest of the app verbose.
logging.getLogger("snekql").setLevel(logging.WARNING)
```

snekql attaches a `NullHandler` to the `snekql` logger, so it emits nothing
until the application configures logging. To capture snekql's structured fields,
point a JSON/structured formatter (e.g. `structlog`'s `ProcessorFormatter`) at
the handler that receives `snekql` records — snekql itself stays pure stdlib.

MariaDB models should use the MariaDB namespace so backend-specific columns and
runtime checks agree:

```python
from snekql import mariadb
from snekql.mariadb import Database, Fetched, Pending, insert, select


class Account[S = Pending](mariadb.Model[S, "Account[Fetched]"]):
    id: mariadb.GenCol[int] = mariadb.Integer(
        primary_key=True,
        auto_increment=True,
        default=mariadb.PENDING_GENERATION,
    )
    email: mariadb.Col[str] = mariadb.Text(unique=True)


config = mariadb.Config(
    database="app",
    host="127.0.0.1",
    port=3306,
    user="snekql",
    password="secret",
)

async with await Database.initialize(config) as db:
    migrations = {
        "0001_create_account": (
            "CREATE TABLE `account` ("
            "`id` BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY, "
            "`email` VARCHAR(255) CHARACTER SET utf8mb4 "
            "COLLATE utf8mb4_bin NOT NULL"
            ") ENGINE=InnoDB"
        ),
        "0002_account_email_unique": (
            "CREATE UNIQUE INDEX `ux_account_email` ON `account` (`email`)"
        ),
    }
    await db.migrate(migrations)
    await db.verify_migrations(migrations)
    await db.verify([Account])
    async with db.transaction() as tx:
        await tx.execute(insert(Account(email="alice@example.com")))
        account = await tx.fetch_one(
            select(Account).where(Account.email.eq("alice@example.com")),
        )
```

For production TCP, set `tls=mariadb.TLSConfig(...)`; certificate verification,
hostname checks, and TLS 1.2+ are mandatory on that path. See
[engine settings](docs/engine-settings.md#verified-tls).

Use transactions for all work:

```python
async with db.transaction() as tx:
    rows = await tx.fetch_all(select(User).all())
    first_email = await tx.fetch_one(
        select(User.email).all().order_by(User.id.asc()).limit(1)
    )
    await tx.execute(update(User).set(User.status.to("inactive")).all())
```

Pass `isolation="serializable"` and/or `read_only=True` to `db.transaction()`
for explicit transaction policy. Omitted options preserve defaults; MariaDB also
supports read-uncommitted, read-committed, and repeatable-read isolation. See
[transaction isolation and access mode](docs/error-handling.md#transaction-isolation-and-access-mode)
for capability checks, pooled-setting restoration, and recovery limits.

MariaDB SELECTs support `.for_update()` with `wait="block"`, `"nowait"`, or
`"skip_locked"`. Keep the locking read and its update in the same Transaction.
SQLite and unsupported query shapes fail compilation; read-only transactions
reject locking queries before IO. See
[locking SELECTs](docs/error-handling.md#locking-selects) for a queue-claim example
and lock-lifetime limits.

Transaction errors expose optional `error.failure` metadata with a portable
category and available native error details. See
[classified transaction failures](docs/error-handling.md#classified-transaction-failures).
Classification does not make a failed connection reusable or retry a statement.
After context exit, `transaction.commit_outcome` reports `"not_attempted"`,
`"rejected"`, `"committed"`, or `"unknown"`. See
[commit outcomes and retry guidance](docs/error-handling.md#commit-outcomes)
before retrying failed work.

Runtime methods:

- `begin_nested()` returns an explicit savepoint context on the existing
  Transaction: `async with tx.begin_nested(): ...`. Success releases it without
  committing; exceptional exit rolls back nested work. Recognized immediate
  constraint failures can recover, but unsafe connections remain unusable.
  Nested contexts reserve the Transaction for their entering task and require
  streams to close before savepoint entry/exit. See
  [nested transactions and recovery limits](docs/error-handling.md#explicit-nested-transactions).
  Nested `db.transaction()` calls still acquire independent connections.
- `fetch_all(select(...))` returns all result rows. It is for bounded result
  sets: the whole result is loaded into memory and every row is validated
  synchronously on the event loop. The materialization loop yields a cooperative
  checkpoint periodically so a large read does not monopolize the loop, but it
  still holds the connection for its full duration. For large result sets stream
  with `fetch_chunks` instead, which fetches incrementally and keeps per-batch
  materialization small.
- `fetch_chunks(select(...), size=N)` streams rows in batches of up to `N` from a
  server-side cursor, so an arbitrarily large result never has to fit in memory.
  It returns a `ChunkStream` — an async context manager and async iterator — that
  must be consumed inside `async with` so the cursor is closed and the connection
  released deterministically:

  ```python
  async with tx.fetch_chunks(select(User).all(), size=500) as stream:
      async for batch in stream:  # batch: list[User[Fetched]]
          for user in batch:
              ...
  ```

  The stream holds the transaction's single connection for its whole lifetime: no
  other query may run on the transaction until the stream is closed, and it must
  be opened and consumed within one task. On MariaDB this uses an unbuffered
  `SSCursor`; a default cursor would buffer the full result client-side and defeat
  streaming.
- `fetch_one(select(...))` returns the single matching row (exactly-one
  contract); it raises `NoResultError` for no row and `MultipleResultsError` for
  more than one. A `None` from a single-value `fetch_one` means SQL `NULL`.
- `fetch_one_or_none(select(...))` returns the row or `None` for the zero-or-one
  case (model, tuple, and join selects), still raising on more than one row.
- `execute(insert(...))` returns `None`, including conflict-handled inserts
  without `.returning(...)`; `execute(update/delete)` returns the affected-row
  count. SQLite counts matched rows; MariaDB counts only rows an `UPDATE`
  actually changed. On SQLite UPDATE/DELETE, `.returning()` returns Fetched
  models, one explicit returning column yields scalars, and multiple columns
  yield tuples. Each `.returning(...)` call replaces the previous projection;
  a final `.returning()` restores whole-model results. The MariaDB adapter
  currently rejects UPDATE/DELETE RETURNING.
- `close()` is async and idempotent after a successful close.

Backend Configs separate pool waiting (`acquire_timeout`) from driver I/O
(`operation_timeout`), both defaulting to 30 seconds. Passing
`db.transaction(timeout=N)` overrides both for that transaction. Each driver
operation gets a fresh budget; application code between calls is not timed.
Timed-out operations discard the uncertain physical connection. A timeout before
COMMIT acknowledgement leaves an unknown outcome requiring reconciliation.
Acknowledged commits remain committed even if subsequent cleanup times out.

## Migrations and verification

Initialization does no schema work. A live `Database` applies the complete
migration chain, verifies its recorded head, then checks the schema against the
models:

```python
db = await Database.initialize(database=Path("app.db"))
# MIGRATIONS is the complete committed chain shown in the quick start.
result = await db.migrate(MIGRATIONS)
await db.verify_migrations(MIGRATIONS)
await db.verify([User], policy="strict")
```

- `db.migrate(migrations)` accepts the complete ordered `dict[str, str]` chain.
  It verifies each recorded position and exact-body SHA-256 before applying the
  pending suffix, then returns an immutable `MigrationResult`. Migrations are the
  sole schema-creation authority. Run `scaffold(...)` during development, review
  its output, and commit the SQL as literals rather than recomputing old bodies
  from current model metadata.
- `db.verify_migrations(migrations)` performs a read-only exact-head check. It
  neither applies pending SQL nor upgrades legacy history.
- `db.verify(models, *, policy=...)` is a partial, structural check that returns
  an immutable `SchemaVerificationResult` with checked tables and table-scoped
  drift issues. Every model is inspected before policy is applied:
  `policy="strict"` raises `SchemaVerificationError` with the result attached;
  `policy="warn"` logs and returns it. Verification compares supported column,
  index, foreign-key, and storage facts by semantics, but cannot represent
  literal defaults, partial-index predicates, `CHECK` constraints, triggers, or
  data.

A deploy step runs `initialize -> migrate -> verify_migrations -> verify`; app
replicas run `initialize -> verify_migrations -> verify`. See
[docs/migrations.md](./docs/migrations.md) and
[docs/schema-drift.md](./docs/schema-drift.md).

## Error model

Every intentional package-originated exception is a `SnekqlError` subclass.
Use `SnekqlError` to catch all snekql failures, or catch narrower subclasses:

- `ModelDeclarationError`, `ModelValidationError`, `FrozenModelError`
- `QueryConstructionError`, `QueryCompilationError`
- `DatabaseClosedError`, `PoolTimeoutError`, `DatabaseOperationTimeoutError`,
  `TransactionClosedError`, `ExecutionError`
- `SchemaVerificationError` (strict Schema Drift; inspect `.result`)
- `MigrationDeclarationError`, `MigrationHistoryError`, `MigrationError`,
  `MigrationLockError`

`ExecutionError` preserves parameterized `sql` and raw `.params` for explicit
inspection. Its string form and normal query logs render
`params=<redacted:N>` by default. Set a Backend Config's
`parameter_visibility="values"` only for controlled local diagnostics.

## Further reading

- [Adoption and release confidence](docs/adoption.md)
- [Why snekql is not an ORM](docs/why-not-orm.md)
- [Typing guide](docs/typing.md)
- [Schema startup and drift](docs/schema-drift.md)
- [Temporary MariaDB Test Server](docs/testing-mariadb.md)
- [Raw SQL](docs/raw-sql.md)
- [Reporting recipes](docs/reporting.md)
- [Query composition design](docs/query-composition-design.md)
- [Error handling guide](docs/error-handling.md)
- [MariaDB integration PRD](https://github.com/crpier/snekql/issues/34)

Runnable examples live in `examples/`:

```sh
uv run python -m examples.basic_app
uv run ty check examples/typed_queries.py
```

Local validation uses `PYTHON_CONTEXT_AWARE_WARNINGS=1 uv run snektest`.
Validated raw SQL requires this Python startup setting for context-local warning
isolation. MariaDB integration tests start a
Temporary MariaDB Test Server through `snekql.testing.mariadb`, so `mariadbd`,
`mariadb-install-db`, and `mariadb` must be available on the test machine.

## Public API

The backend namespaces are the public import surface. Pick `snekql.sqlite` or
`snekql.mariadb` and import the whole surface from it -- the dialect-neutral
verbs and builders as well as that backend's `Model` and column constructors.
There is no flat `snekql.<symbol>` surface; the package root only exposes the
`sqlite` and `mariadb` namespace handles. This keeps SQLite-only and
MariaDB-only symbols from colliding and stops auto-imports from landing on the
wrong backend. Static backend-family witnesses also reject mixing models,
queries, configurations, Transactions, joins, foreign keys, or Scaffold inputs
across those namespaces; runtime checks remain for dynamically typed callers.

The supported import surface is `snekql.sqlite`, `snekql.mariadb`, and
`snekql.testing.mariadb`, each curated in its own `__all__`. Underscored modules
(`snekql._*`) and backend submodules (`snekql.sqlite.config`,
`snekql.sqlite.verbs`, …) are implementation detail and not supported import
paths — their public symbols are re-exported through the namespace top level.
Use `Select[Row]` and `Write[Result]` to annotate executable queries without
depending on their state-specific implementation classes. Query Readiness is
tracked privately: selects and deletes need `.all()` or `.where(...)`; updates
need both `.set(...)` and row scope. `ty` rejects guaranteed-incomplete queries
at stored-query and Transaction seams, while Query Compilation keeps equivalent
checks for dynamic callers. `Predicate`, `Aggregate`,
`Scalar`, `JoinOn`, `OrderBy`, and `Assignment` are likewise annotation-only:
obtain their values from model/column methods and Query Builder factories,
never constructors. Use
`ColumnRef[Owner, T]` for a read-only column parameter that a helper compares or
projects; assignment methods intentionally remain on model columns. Queries are
built only through the `select`/`insert`/`update`/`delete` factory verbs. The
catchable error contract
is the `SnekqlError` hierarchy re-exported from each namespace. See
[docs/typing.md](docs/typing.md#stability-contract) for the full contract.

Agent navigation map:

- `snekql/model.py`: model metaclass, table metadata, pending/fetched
  materialization.
- `snekql/storage.py`: column descriptors, SQLite storage metadata, value
  codecs.
- `snekql/expressions.py`: predicates, ordering, update assignments.
- `snekql/query.py`: query builders and SQL compilation.
- `snekql/runtime.py`: `Database`, `Transaction`, execution methods.
- `snekql/sqlite/pool.py`: internal async SQLite connection pool.
- `snekql/sqlite/schema.py`: scaffold DDL generation and schema verification
  (dialect-blind pipeline in `snekql/_schema_*.py`).
- `snekql/errors.py`: public exception hierarchy.
- `tests/test_public_typing.py`: type-checker prototypes for the public API.
- `CONTEXT.md`: project language and terminology.

# Typing guide

snekql's public API is designed so model declaration, query construction, and
runtime result shapes are visible to static type checkers.

## Model states

A table model class is generic in its lifecycle state:

```python
class User[S = Pending](Model[S, "User[Fetched]"]):
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

`Fetched` is the state returned by database reads:

```python
fetched_user = await tx.fetch_one(select(User).where(User.email.eq("x")))
# fetched_user: User[Fetched] | None
```

### Instance methods and `self`

Model classes are generic in their lifecycle state, so methods that assume a
specific state must say so on `self`. Leave `self` unannotated only when the
method works for both `User[Pending]` and `User[Fetched]`.

```python
class User[S = Pending](Model[S, "User[Fetched]"]):
    id: GenCol[int] = Integer(primary_key=True, default=PENDING_GENERATION)
    email: Col[str] = Text()

    def insert_payload(self: User[Pending]) -> dict[str, str]:
        return {"email": self.email}

    def cache_key(self: User[Fetched]) -> str:
        return f"user:{self.id}"
```

A bare `User` means the default state, `User[Pending]`; spell `User[Fetched]`
when a method requires a database-materialized row. The state annotation is for
static typing and is erased at runtime. The Query Runtime separately tags rows
it materializes so lifecycle-sensitive operations can reject them.

`insert(...)` is the lifecycle transition: it accepts `Pending` instances only.
A model returned by the Query Runtime is `Fetched` and is rejected if passed back
to `insert`; construct a new pending model explicitly when copying a row.

Because `Fetched` is used in string forward references such as
`Model[S, "User[Fetched]"]`, Ruff's Pyflakes `F401` check may not see the import
as used. Projects that lint model declarations with Ruff should allow the
qualified backend imports:

```toml
[tool.ruff.lint.pyflakes]
allowed-unused-imports = [
  "snekql.sqlite.Fetched",
  "snekql.mariadb.Fetched",
]
```

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

sqlite_query: sqlite.Select[SqliteUser[sqlite.Fetched]] = sqlite.select(SqliteUser)
mariadb_query: mariadb.Select[MariadbUser[mariadb.Fetched]] = mariadb.select(
    MariadbUser
)

await sqlite_tx.fetch_all(mariadb_query)  # type error
sqlite.select(SqliteUser).join(MariadbUser, on=...)  # type error
sqlite.scaffold([MariadbUser])  # type error
```

The family coordinate is private. Application annotations keep the public forms
`Model[State, ReadModel]`, `Select[Row]`, `Write[Result]`, and `Transaction`
without a backend type argument. Import those names and every query verb from the
same backend namespace.

Static isolation supplements runtime validation. Dynamic inputs introduced via
`Any`, casts, or runtime model loading are still checked by backend verbs, joins,
foreign keys, Scaffold, Database verification, and Execution Plans.

## `Col` and `GenCol`

Use `Col[T]` for normal persisted values. The pending and fetched value type is
`T`.

Use `GenCol[T]` for server-filled/generated values. Pending instances may have
`T | PendingGeneration`; fetched instances have `T`.

```python
pending_user = User(email="alice@example.com")
pending_user.id  # int | PendingGeneration

fetched_user: User[Fetched]
fetched_user.id  # int
```

`PENDING_GENERATION` is the singleton sentinel value for generated pending values that have
not been filled by the database yet.

### Nullability

When `nullable=` is omitted, snekql derives nullability from the field
annotation: `Col[str]` is `NOT NULL`, while `Col[str | None]` is nullable. An
explicit `nullable=True` or `nullable=False` is cross-checked against the
annotation, and contradictory declarations are rejected at class definition.

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
await tx.fetch_all(select(User).all())
# list[User[Fetched]]

await tx.fetch_all(select(User.email).all())
# list[str]

await tx.fetch_all(select(User.email, User.status).all())
# list[tuple[str, str]]
```

`fetch_one(...)` carries an **exactly-one** contract: it returns the single
matching row in the selected shape, and raises `NoResultError` when no row
matches or `MultipleResultsError` when more than one does. Because absence is an
error rather than a `None` return, a single-value result keeps the column read
type — and a returned `None` there can only mean SQL `NULL`:

```python
await tx.fetch_one(select(User.email).all())
# str            (raises NoResultError / MultipleResultsError on 0 / >1 rows)

await tx.fetch_one(select(User).all())
# User[Fetched]
```

`fetch_one_or_none(...)` is the **zero-or-one** variant: it returns the row or
`None` when none matches, still raising `MultipleResultsError` on more than one.
It is offered only for model, tuple, and join selects, where `None` can only
mean a missing row:

```python
await tx.fetch_one_or_none(select(User).all())
# User[Fetched] | None

await tx.fetch_one_or_none(select(User.email, User.status).all())
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
async with tx.fetch_chunks(select(User).all(), size=500) as stream:
    async for batch in stream:  # batch: list[User[Fetched]]
        ...

async with tx.fetch_chunks(select(User.email).all(), size=500) as stream:
    async for batch in stream:  # batch: list[str]
        ...

async with tx.fetch_chunks(select(User.email, User.status).all(), size=500) as stream:
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

## Insert conflicts

`on_conflict` pins its target columns and update assignments to the inserted
model. Pyright rejects a target or assignment from another model:

```python
from snekql.sqlite import DoNothing, DoUpdate, insert

update_email = insert(User(email=email, status=status)).on_conflict(
    User.email,
    action=DoUpdate(User.status.to_inserted()),
)
# InsertQuery[User[Pending], User[Fetched]]

ignore_email = insert([User(email=email, status=status)]).on_conflict(
    User.email,
    action=DoNothing,
)
# InsertManyQuery[User[Pending], User[Fetched]]
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
class User[S = Pending](Model[S, "User[Fetched]"]):
    id: GenCol[int] = Integer(
        primary_key=True,
        auto_increment=True,
        default=PENDING_GENERATION,
    )
    email: Col[str] = Text()


class Order[S = Pending](Model[S, "Order[Fetched]"]):
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

### Model-select joins

A model-select join accumulates a tuple of `Fetched` models. `left_join` makes
the right side optional:

```python
await tx.fetch_all(
    select(User)
    .join(Order, on=Order.user_id.references(User.id))
    .where(User.email.eq("a@b.c") & Order.note.eq("x")),
)
# list[tuple[User[Fetched], Order[Fetched]]]

await tx.fetch_all(
    select(User).left_join(Order, on=Order.user_id.references(User.id)),
)
# list[tuple[User[Fetched], Order[Fetched] | None]]
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

The target column may be any primary key or `unique=True` column. A typed-only
reference (an `FKCol` annotation with a plain storage specifier) keeps the
relationship available for joins without enforcing referential integrity.

### Nullable foreign keys

Nullability and omittability are separate. `nullable=True` permits SQL `NULL`
and requires `T | None` in the annotation. Without a default, callers must still
provide the field:

```python
class RequiredChild[S = Pending](Model[S, "RequiredChild[Fetched]"]):
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
class OmittableChild[S = Pending](Model[S, "OmittableChild[Fetched]"]):
    parent_id: FKCol[User, int | None] = ForeignKey(
        User.id,
        nullable=True,
        default=None,
    )


OmittableChild()  # ok: parent_id defaults to None
```

Both forms materialize `parent_id` as `int | None` on Fetched Models. The
difference applies only while constructing Pending Models.

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
On SQLite, `verify(...)` compares the action and reports a model/live mismatch as
drift; MariaDB does not verify foreign keys.

### Composite primary keys

Marking more than one column `primary_key=True` declares a composite
(multi-column) primary key — the natural shape for a pure join table whose
identity *is* the referenced column pair:

```python
class TeamMember[S = Pending](Model[S, "TeamMember[Fetched]"]):
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
- **Bulk insert homogeneity.** Every row in one `insert([...])` batch must be an
  instance of the same model. The Query Builder rejects mixed batches at runtime;
  `ty` may infer `Unknown` rather than diagnose a heterogeneous sequence.

A scalar subquery (`scalar(...)`), by contrast, **is** reflected in the types: it
evaluates to SQL `NULL` on an empty/no-match result set, so its projected slot is
typed `... | None` and decodes a no-match to `None` rather than raising, even over
a `NOT NULL` inner column. A projection must start with a real column, aggregate,
or dialect expression to establish its `FROM` scope; scalar subqueries may appear
only in later slots.

## Backend namespaces

Every public symbol is imported from a backend namespace. Pick `snekql.sqlite`
or `snekql.mariadb` and import the whole surface from it -- the dialect-neutral
verbs as well as that backend's `Model` and column declarations:

```python
from snekql import mariadb, sqlite
from snekql.sqlite import PENDING_GENERATION, Database, Fetched, Pending


class SqliteUser[S = Pending](sqlite.Model[S, "SqliteUser[Fetched]"]):
    id: sqlite.GenCol[int] = sqlite.Integer(
        primary_key=True,
        auto_increment=True,
        default=PENDING_GENERATION,
    )


class MariadbUser[S = Pending](mariadb.Model[S, "MariadbUser[Fetched]"]):
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
first `verify` or query, not at init.)

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

**Queries are named by result.** Use `Select[RowT]` for a read query and
`Write[ResultT]` for a mutation. The state-specific builder classes are private
implementation vocabulary. Build queries through `select`, `insert`, `update`,
and `delete`; do not instantiate query classes directly. Use
`ColumnRef[OwnerT, T]` when a helper accepts a read-only model column.
`Select` and `Write` are annotation-only aliases rather than runtime classes, so
do not construct them or use them with `isinstance`. An annotated query remains
executable through `Transaction`:

```python
async def load_users(
    tx: Transaction,
    query: Select[User[Fetched]],
) -> list[User[Fetched]]:
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

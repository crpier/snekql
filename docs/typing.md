# Typing guide

snekql's public API is designed so model declaration, query construction, and
runtime result shapes are visible to static type checkers.

## Model states

A table model class is generic in its lifecycle state:

```python
class User[S = Pending](Model[S, "User[Fetched]"]):
    id: User.GenCol[int] = Integer(
        primary_key=True,
        auto_increment=True,
        default=PENDING_GENERATION,
    )
    email: User.Col[str] = Text(nullable=False)
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
    id: User.GenCol[int] = Integer(primary_key=True, default=PENDING_GENERATION)
    email: User.Col[str] = Text(nullable=False)

    def insert_payload(self: User[Pending]) -> dict[str, str]:
        return {"email": self.email}

    def cache_key(self: User[Fetched]) -> str:
        return f"user:{self.id}"
```

A bare `User` means the default state, `User[Pending]`; spell `User[Fetched]`
when a method requires a database-materialized row. The state annotation is for
static typing only — it does not add a runtime guard.

Because `Fetched` is used in string forward references such as
`Model[S, "User[Fetched]"]`, Ruff's Pyflakes `F401` check may not see the import
as used. Projects that lint model declarations with Ruff should allow the
package-root import:

```toml
[tool.ruff.lint.pyflakes]
allowed-unused-imports = [
  "snekql.Fetched",
]
```

## `Col` and `GenCol`

Use `Col[T]` for normal persisted values. The pending and fetched value type is
`T`.

Use `GenCol[T]` for server-filled/generated values. Pending instances may have
`T | PendingGeneration`; fetched instances have `T`.

```python
pending_user = User(email="alice@example.com")
pending_user.id      # int | PendingGeneration

fetched_user: User[Fetched]
fetched_user.id      # int
```

`PENDING_GENERATION` is the singleton sentinel value for generated pending values that have
not been filled by the database yet.

### Nullability

A column is **NOT NULL by default**. `nullable=` is unset (the constructor
default), `nullable=None`, and `nullable=False` all produce a NOT NULL column;
only `nullable=True` makes it nullable. The read annotation and the flag are
cross-checked at declaration: a `| None` read type requires `nullable=True`, and
a non-optional read type forbids it. Each side rejects the contradiction at class
definition time.

```python
name:     User.Col[str]        = Text()                 # NOT NULL (unset default)
required: User.Col[str]        = Text(nullable=False)   # NOT NULL (explicit)
optional: User.Col[str | None] = Text(nullable=True)    # nullable

bad:      User.Col[str]        = Text(nullable=True)    # rejected: type vs flag
bad2:     User.Col[str | None] = Text()                 # rejected: | None needs nullable=True
```

The NOT NULL default holds even when the cross-check cannot resolve the
annotation (for example a forward reference it skips): the physical column is
still NOT NULL, so a non-optional read type is never handed a SQL `NULL`.

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
    async for batch in stream:   # batch: list[User[Fetched]]
        ...

async with tx.fetch_chunks(select(User.email).all(), size=500) as stream:
    async for batch in stream:   # batch: list[str]
        ...

async with tx.fetch_chunks(select(User.email, User.status).all(), size=500) as stream:
    async for batch in stream:   # batch: list[tuple[str, str]]
        ...
```

`ChunkStream` is exported from the backend namespaces (`snekql.sqlite`,
`snekql.mariadb`) for typed annotations only. Like the query classes, do not
construct it directly — obtain one from `Transaction.fetch_chunks`.

## Joins

A column may declare the model it references with `FKCol[Target, T]`. The
relationship is carried in the annotation, so it participates in type checking
at zero runtime cost:

```python
class User[S = Pending](Model[S, "User[Fetched]"]):
    id: User.GenCol[int] = Integer(
        primary_key=True,
        auto_increment=True,
        default=PENDING_GENERATION,
    )
    email: User.Col[str] = Text(nullable=False)


class Order[S = Pending](Model[S, "Order[Fetched]"]):
    id: Order.GenCol[int] = Integer(
        primary_key=True,
        auto_increment=True,
        default=PENDING_GENERATION,
    )
    user_id: Order.FKCol[User, int] = ForeignKey(User.id)
    note: Order.Col[str] = Text(nullable=False)
```

A join condition is built from an FK column against its target with
`references(...)`. It only accepts a column of the referenced model whose read
type matches, so the condition is provably between related tables of compatible
key type:

```python
Order.user_id.references(User.id)        # ok
Order.user_id.references(User.email)     # type error: str column vs int FK
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
    select(User.email, Order.note)
    .join(Order, on=Order.user_id.references(User.id)),
)
# list[tuple[str, str]]
```

Referencing — selecting or filtering — a table that was never joined is a type
error, caught at `fetch_all`/`fetch_one`:

```python
select(User.email, Region.code).join(Order, on=Order.user_id.references(User.id))
# Region is never joined: rejected when fetched
```

> **LEFT-join nullability caveat.** For projection-select, a projected column
> taken from the nullable side of a `left_join` keeps its non-optional read type
> (for example `str`, not `str | None`), even though an unmatched row yields
> `None` at runtime — the unmatched value decodes to `None` rather than raising
> on the column's own `NOT NULL` constraint. Model-select left joins are sound — the whole right model
> becomes `... | None`. Prefer model-select when you need a left join's
> nullability reflected in the types.

### Optional foreign-key DDL

An `FKCol[...]` annotation controls typing only. Emitting an actual
`FOREIGN KEY` constraint (and including it in startup drift checks) is opt-in
per column by declaring it with `ForeignKey(...)`, which names the exact target
column. The column's storage class is derived from that target — never restated
— and the named target is cross-checked against the annotation at declaration
time:

```python
user_id: Order.FKCol[User, int] = ForeignKey(User.id)            # references user(id)
owner_email: Order.FKCol[User, str] = ForeignKey(User.email)     # references user(email)
ref_code: Order.FKCol[Region, str] = Text()                      # typed-only soft reference
```

The target column may be any primary key or `unique=True` column. A typed-only
reference (an `FKCol` annotation with a plain storage specifier) keeps the
relationship available for joins without enforcing referential integrity.

### Referential actions

`ForeignKey(...)` takes optional `on_delete=` and `on_update=` referential
actions, rendered verbatim as `ON DELETE`/`ON UPDATE` clauses on the constraint.
The accepted actions are `"CASCADE"`, `"RESTRICT"`, `"SET NULL"`, and
`"NO ACTION"`:

```python
# Owned rows that are meaningless once the parent is gone:
job_id: Step.FKCol[Job, str] = ForeignKey(Job.id, nullable=False, on_delete="CASCADE")
# Detach the child instead of deleting it:
owner_id: Doc.FKCol[User, int] = ForeignKey(User.id, on_delete="SET NULL")
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
    team_id: TeamMember.FKCol[Team, int] = ForeignKey(Team.id, primary_key=True)
    user_id: TeamMember.FKCol[User, int] = ForeignKey(User.id, primary_key=True)
    role: TeamMember.Col[str] = Text(nullable=False)
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
- **`limit`/`offset` bounds.** Their parameter is `NonNegativeInt`, which Pyright
  sees as plain `int`, so a negative literal type-checks; a negative value raises
  `QueryConstructionError` at construction.

A scalar subquery (`scalar(...)`), by contrast, **is** reflected in the types: it
evaluates to SQL `NULL` on an empty/no-match result set, so its projected slot is
typed `... | None` and decodes a no-match to `None` rather than raising, even over
a `NOT NULL` inner column.

## Backend namespaces

Every public symbol is imported from a backend namespace. Pick `snekql.sqlite`
or `snekql.mariadb` and import the whole surface from it -- the dialect-neutral
verbs as well as that backend's `Model` and column declarations:

```python
from snekql import mariadb, sqlite
from snekql.sqlite import PENDING_GENERATION, Database, Fetched, Pending


class SqliteUser[S = Pending](sqlite.Model[S, "SqliteUser[Fetched]"]):
    id: SqliteUser.GenCol[int] = sqlite.Integer(
        primary_key=True,
        auto_increment=True,
        default=PENDING_GENERATION,
    )


class MariadbUser[S = Pending](mariadb.Model[S, "MariadbUser[Fetched]"]):
    id: MariadbUser.GenCol[int] = mariadb.Integer(
        primary_key=True,
        auto_increment=True,
        default=PENDING_GENERATION,
    )
```

Backend namespaces expose distinct model bases and column declaration classes,
so backend-specific options can evolve without pretending the dialects are
portable.

## Mixed-backend safety

Table models carry backend identity. `db.verify(...)` rejects a model whose
backend does not match the runtime config, and `Transaction` rejects a query
built from another backend's model before SQL is executed. (Initialization is
connect-only and takes no models, so a wrong-backend deploy is caught at the
first `verify` or query, not at init.)

Pyright can see the backend namespace types where they are explicit, and runtime
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
  `snekql.sqlite.query`, `snekql.sqlite.config`, `snekql.sqlite.verbs`,
  `snekql.sqlite.runtime`, and their MariaDB peers. Their public symbols are
  re-exported through the namespace top level; the submodule paths are not a
  supported import surface. (The `query` submodule is imported by each namespace
  only to register its Dialect for SQL inspection — see
  [ADR 0004](adr/0004-dialect-blind-core-with-open-ast-dialect-expressions.md) —
  not to expose a `<namespace>.query` import path.)

**Query classes are return types, not constructors.** The query classes
(`SelectModelQuery`, `InsertQuery`, the `*Returning*` variants, and the rest)
are public so you can name them in annotations and `isinstance` checks. Build
them only through the factory verbs `select`, `insert`, `update`, and `delete`;
do not instantiate the classes directly.

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
uv run pyright examples/typed_queries.py tests/test_public_typing.py
```

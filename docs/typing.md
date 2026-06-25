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
> `None` at runtime. Model-select left joins are sound — the whole right model
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

## Type-checkable examples

The repository keeps a focused public typing example in:

- `examples/typed_queries.py`
- `tests/test_public_typing.py`

Run:

```sh
uv run pyright examples/typed_queries.py tests/test_public_typing.py
```

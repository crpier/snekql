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
        default=MISSING,
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
`T | Missing`; fetched instances have `T`.

```python
pending_user = User(email="alice@example.com")
pending_user.id      # int | Missing

fetched_user: User[Fetched]
fetched_user.id      # int
```

`MISSING` is the singleton sentinel value for generated pending values that have
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

`fetch_one(...)` returns the first row or `None` with the same selected shape:

```python
await tx.fetch_one(select(User.email).all())
# str | None
```

## Joins

A column may declare the model it references with `FKCol[Target, T]`. The
relationship is carried in the annotation, so it participates in type checking
at zero runtime cost:

```python
class User[S = Pending](Model[S, "User[Fetched]"]):
    id: User.GenCol[int] = Integer(
        primary_key=True,
        auto_increment=True,
        default=MISSING,
    )
    email: User.Col[str] = Text(nullable=False)


class Order[S = Pending](Model[S, "Order[Fetched]"]):
    id: Order.GenCol[int] = Integer(
        primary_key=True,
        auto_increment=True,
        default=MISSING,
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
from snekql.sqlite import MISSING, Database, Fetched, Pending


class SqliteUser[S = Pending](sqlite.Model[S, "SqliteUser[Fetched]"]):
    id: SqliteUser.GenCol[int] = sqlite.Integer(
        primary_key=True,
        auto_increment=True,
        default=MISSING,
    )


class MariadbUser[S = Pending](mariadb.Model[S, "MariadbUser[Fetched]"]):
    id: MariadbUser.GenCol[int] = mariadb.Integer(
        primary_key=True,
        auto_increment=True,
        default=MISSING,
    )
```

Backend namespaces expose distinct model bases and column declaration classes,
so backend-specific options can evolve without pretending the dialects are
portable.

## Mixed-backend safety

Table models carry backend identity. `Database.initialize(..., logger=logger)` rejects a model
whose backend does not match the runtime config, and `Transaction` rejects a
query built from another backend's model before SQL is executed.

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

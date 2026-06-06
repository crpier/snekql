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

## Backend namespaces

SQLite compatibility aliases remain available at the package root, but new code
should prefer explicit backend namespaces:

```python
from snekql import Database, Fetched, MISSING, Pending, mariadb, sqlite


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
Top-level `Model`, `Integer`, `Text`, and related compatibility aliases continue
to behave as SQLite declarations.

## Import path

Prefer importing public symbols from the package root:

```python
from snekql import Database, Pending, Text, select, sqlite
```

The root exports are curated in `snekql.__all__` and mirrored by
`snekql/__init__.pyi`.

## Type-checkable examples

The repository keeps a focused public typing example in:

- `examples/typed_queries.py`
- `tests/test_public_typing.py`

Run:

```sh
uv run pyright examples/typed_queries.py tests/test_public_typing.py
```

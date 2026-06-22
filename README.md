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
    id: User.GenCol[int] = sqlite.Integer(
        primary_key=True,
        auto_increment=True,
        default=sqlite.MISSING,
    )
    email: User.Col[str] = sqlite.Text(nullable=False, unique=True)
    status: User.Col[str] = sqlite.Text(nullable=False, default="active")
    created_at: User.GenCol[datetime] = sqlite.Text(
        server_default=sqlite.CurrentTimestamp(),
        default=sqlite.MISSING,
    )


async def main() -> None:
    db = await Database.initialize(
        sqlite.Config(
            database=Path("app.db"),
            pool_size=5,
            acquire_timeout=30.0,
        ),
        models=[User],
        schema_policy="strict",
    )
    try:
        async with db.transaction(timeout=5.0) as tx:
            await tx.execute(insert(User(email="alice@example.com")))
            # fetch_one is exactly-one: it raises NoResultError if the row is
            # absent, so the result is never None.
            user = await tx.fetch_one(
                select(User).where(User.email.eq("alice@example.com")),
            )
            print(user.email)
    finally:
        await db.close()
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

    id: AuditLog.GenCol[int] = sqlite.Integer(
        primary_key=True,
        auto_increment=True,
        default=sqlite.MISSING,
    )
    message: AuditLog.Col[str] = sqlite.Text(nullable=False)
    created_at: AuditLog.GenCol[datetime] = sqlite.Text(
        server_default=sqlite.CurrentTimestamp(),
        default=sqlite.MISSING,
    )
```

Rules to remember:

- `Col[T]` is a normal persisted column.
- `GenCol[T]` is server/generated; pending values may be `MISSING`, fetched
  values are `T`.
- If `__tablename__` is omitted, class names become snake_case table names.
- Models are immutable after construction/materialization.
- Fetched models are produced by database reads only.

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
- `sqlite.Text` — `TEXT` storage. Holds `Col[str]`, `Col[datetime]` (ISO text),
  `Col[uuid.UUID]` (string form), or a `Col[pydantic.Json[T]]` payload.
- `sqlite.Blob` — `BLOB` storage for `Col[bytes]`.

JSON uses Pydantic's marker, not a snekql type: annotate
`Col[pydantic.Json[T]] = Text()`. Serialization and validation both run through
`T`, so any type Pydantic can validate (`datetime`, Pydantic models,
`list[Model]`, ...) round-trips, not just `dict`/`list`/primitives.

MariaDB additionally exposes its native types as column types — `mariadb.Json`,
`mariadb.Boolean`, `mariadb.DateTime`, and `mariadb.Uuid` (native `UUID`). To
store a UUID as raw bytes instead, pair `Col[uuid.UUID]` with `Blob()`.

There is no declaration-time storage/logical compatibility check: any pairing is
allowed and an impossible one fails at encode/decode via a Pydantic error.
Timezone policy is the logical type's job — a naive `datetime` round-trips
naive; annotate `Col[AwareDatetime]` to require awareness.

Because the logical type is whatever Pydantic can validate, the UUID-version
aliases work as drop-in logical types and add version validation for free:
`Col[pydantic.UUID4] = Text()`, or `Col[pydantic.UUID7] = mariadb.Uuid()`.
Pydantic ships `UUID1`/`UUID3`/`UUID4`/`UUID5`/`UUID6`/`UUID7`/`UUID8`; all of
them store the same as a plain `Col[uuid.UUID]` and round-trip through both
`Text` and MariaDB's native `Uuid`. Pair the annotation with a matching factory
(`Col[pydantic.UUID7] = mariadb.Uuid(default_factory=uuid.uuid7)`) — nothing
forces the factory and the annotation to agree, so a mismatched version fails
construct-time validation.

All column types accept `unique=True` for column-level unique indexes. SQLite
allows multiple `NULL` values in a unique index, so use `nullable=False` when
uniqueness should also require a value. Primary-key columns reject `unique=True`
because it is redundant. Every column type also exposes `server_default`.

`sqlite.CurrentTimestamp()` and `mariadb.CurrentTimestamp()` are the only v1
server defaults and are valid only on `GenCol` fields.

## Indexes

Use the backend namespace `Index(...)` in `__indexes__` for table-level indexes:

```python
from snekql import sqlite
from snekql.sqlite import Fetched, Pending


class User[S = Pending](sqlite.Model[S, "User[Fetched]"]):
    email: User.Col[str] = sqlite.Text(nullable=False, unique=True)
    status: User.Col[str] = sqlite.Text(nullable=False)
    tenant_id: User.Col[int] = sqlite.Integer(nullable=False)

    __indexes__ = [
        sqlite.Index(status),
        sqlite.Index(tenant_id, email, unique=True),
        sqlite.Index(tenant_id, name="ix_user_tenant_custom"),
    ]
```

Index declarations accept column descriptors only. Names are inferred as
`ix_<table>_<columns>` or `ux_<table>_<columns>` unless `name=` is supplied.

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
    User.tenant_id.eq(1)
    & (User.status.eq("active") | User.email.like("%@vip.com")),
)

# WHERE NOT (status = 'disabled')
select(User).where(~User.status.eq("disabled"))
```

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

## Runtime

`Database.initialize(...)` is the only public construction path. Select the
backend with its namespace config. The legacy SQLite keyword form remains
supported for compatibility, but new code should use `sqlite.Config`.

```python
from pathlib import Path

from snekql import sqlite
from snekql.sqlite import Database


db = await Database.initialize(
    sqlite.Config(database=Path("app.db"), pool_size=5),
    models=[User],
)
memory_db = await Database.initialize(
    sqlite.Config(database=":memory:"),
)
```

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
    id: Account.GenCol[int] = mariadb.Integer(
        primary_key=True,
        auto_increment=True,
        default=mariadb.MISSING,
    )
    email: Account.Col[str] = mariadb.Text(nullable=False, unique=True)


config = mariadb.Config(
    database="app",
    host="127.0.0.1",
    port=3306,
    user="snekql",
    password="secret",
)

db = await Database.initialize(config, models=[Account])
try:
    async with db.transaction() as tx:
        await tx.execute(insert(Account(email="alice@example.com")))
        account = await tx.fetch_one(
            select(Account).where(Account.email.eq("alice@example.com")),
        )
finally:
    await db.close()
```

Use transactions for all work:

```python
async with db.transaction() as tx:
    rows = await tx.fetch_all(select(User).all())
    first_email = await tx.fetch_one(
        select(User.email).all().order_by(User.id.asc()).limit(1)
    )
    await tx.execute(update(User).set(User.status.to("inactive")).all())
```

Runtime methods:

- `fetch_all(select(...))` returns all result rows.
- `fetch_one(select(...))` returns the single matching row (exactly-one
  contract); it raises `NoResultError` for no row and `MultipleResultsError` for
  more than one. A `None` from a single-value `fetch_one` means SQL `NULL`.
- `fetch_one_or_none(select(...))` returns the row or `None` for the zero-or-one
  case (model, tuple, and join selects), still raising on more than one row.
- `execute(insert(...))` returns `None`; `execute(update/delete)` returns the
  affected-row count. SQLite counts matched rows; MariaDB counts only rows an
  `UPDATE` actually changed.
- `close()` is async and idempotent after a successful close.

## Schema startup

When initialized with `models=[...]`, snekql:

1. Preserves model order.
2. Rejects duplicate resolved table and index names.
3. Creates missing backend tables and their indexes.
4. Verifies existing tables and indexes with backend metadata: SQLite compares
   deterministic `STRICT` DDL; MariaDB compares normalized `INFORMATION_SCHEMA`
   metadata.
5. Treats drift according to `schema_policy`: `"strict"` raises,
   `"warn"` logs and continues.

## Error model

Every intentional package-originated exception is a `SnekqlError` subclass.
Use `SnekqlError` to catch all snekql failures, or catch narrower subclasses:

- `ModelDeclarationError`, `ModelValidationError`, `FrozenModelError`
- `QueryConstructionError`, `QueryCompilationError`
- `DatabaseClosedError`, `PoolTimeoutError`, `TransactionClosedError`,
  `ExecutionError`
- `SchemaVerificationError`

`ExecutionError` preserves `sql` and `params` for debugging. Structured query
logs may also include SQL and params exactly as supplied to the database driver;
snekql does not redact secrets.

## Further reading

- [Adoption and release confidence](docs/adoption.md)
- [Why snekql is not an ORM](docs/why-not-orm.md)
- [Typing guide](docs/typing.md)
- [Schema startup and drift](docs/schema-drift.md)
- [Temporary MariaDB Test Server](docs/testing-mariadb.md)
- [Error handling guide](docs/error-handling.md)
- [MariaDB integration PRD](https://github.com/crpier/snekql/issues/34)

Runnable examples live in `examples/`:

```sh
uv run python -m examples.basic_app
uv run pyright examples/typed_queries.py
```

Local validation uses `uv run snektest`. MariaDB integration tests start a
Temporary MariaDB Test Server through `snekql.testing.mariadb`, so `mariadbd`,
`mariadb-install-db`, and `mariadb` must be available on the test machine.

## Public API

The backend namespaces are the public import surface. Pick `snekql.sqlite` or
`snekql.mariadb` and import the whole surface from it -- the dialect-neutral
verbs and builders as well as that backend's `Model` and column constructors.
There is no flat `snekql.<symbol>` surface; the package root only exposes the
`sqlite` and `mariadb` namespace handles. This keeps SQLite-only and
MariaDB-only symbols from colliding and stops auto-imports from landing on the
wrong backend.

Agent navigation map:

- `snekql/model.py`: model metaclass, table metadata, pending/fetched
  materialization.
- `snekql/storage.py`: column descriptors, SQLite storage metadata, value
  codecs.
- `snekql/expressions.py`: predicates, ordering, update assignments.
- `snekql/query.py`: query builders and SQL compilation.
- `snekql/runtime.py`: `Database`, `Transaction`, execution methods.
- `snekql/_pool.py`: internal async SQLite connection pool.
- `snekql/schema.py`: `STRICT` DDL generation and schema verification.
- `snekql/errors.py`: public exception hierarchy.
- `tests/test_public_typing.py`: type-checker prototypes for the public API.
- `PRD.md`: full v1 product contract.
- `CONTEXT.md`: project language and terminology.

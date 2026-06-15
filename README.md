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

from snekql import (
    Database,
    Fetched,
    Pending,
    StructuredLogger,
    insert,
    select,
    sqlite,
)


class User[S = Pending](sqlite.Model[S, "User[Fetched]"]):
    id: User.GenCol[int] = sqlite.Integer(
        primary_key=True,
        auto_increment=True,
        default=sqlite.MISSING,
    )
    email: User.Col[str] = sqlite.Text(nullable=False, unique=True)
    status: User.Col[str] = sqlite.Text(nullable=False, default="active")
    created_at: User.GenCol[datetime] = sqlite.DateTime(
        server_default=sqlite.CurrentTimestamp(),
        default=sqlite.MISSING,
    )


async def main(*, logger: StructuredLogger) -> None:
    db = await Database.initialize(
        sqlite.Config(
            database=Path("app.db"),
            pool_size=5,
            acquire_timeout=30.0,
        ),
        logger=logger,
        models=[User],
        schema_policy="strict",
    )
    try:
        async with db.transaction(timeout=5.0) as tx:
            await tx.execute(insert(User(email="alice@example.com")))
            user = await tx.fetch_one(
                select(User).where(User.email.eq("alice@example.com")),
            )
            if user is not None:
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

from snekql import Fetched, Pending, sqlite


class AuditLog[S = Pending](sqlite.Model[S, "AuditLog[Fetched]"]):
    __tablename__ = "audit_log"

    id: AuditLog.GenCol[int] = sqlite.Integer(
        primary_key=True,
        auto_increment=True,
        default=sqlite.MISSING,
    )
    message: AuditLog.Col[str] = sqlite.Text(nullable=False)
    created_at: AuditLog.GenCol[datetime] = sqlite.DateTime(
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
  "snekql.Fetched",
]
```

## Storage classes

Use storage declarations from the same backend namespace as the model:

- `sqlite.Integer` / `mariadb.Integer`
- `sqlite.Real` / `mariadb.Real`
- `sqlite.Text` / `mariadb.Text`
- `sqlite.Blob` / `mariadb.Blob`
- `sqlite.Json` / `mariadb.Json` stores JSON text. Serialization and validation
  both go through the column's annotated type, so any type Pydantic can validate
  (`datetime`, Pydantic models, `list[Model]`, ...) round-trips, not just
  `dict`/`list`/primitives.
- `sqlite.Boolean` / `mariadb.Boolean` stores boolean values in
  integer-compatible columns.
- `sqlite.DateTime` / `mariadb.DateTime` stores UTC datetimes.

All storage declarations accept `unique=True` for column-level unique indexes.
SQLite allows multiple `NULL` values in a unique index, so use `nullable=False`
when uniqueness should also require a value. Primary-key columns reject
`unique=True` because it is redundant.

`sqlite.CurrentTimestamp()` and `mariadb.CurrentTimestamp()` are the only v1
server defaults and are valid only on `DateTime` `GenCol` fields.

## Indexes

Use the backend namespace `Index(...)` in `__indexes__` for table-level indexes:

```python
from snekql import Fetched, Pending, sqlite


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
from snekql import delete, insert, select, update

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

A select can be nested inside another query as a subquery:

```python
from snekql import exists, not_exists, scalar, select

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

`Database.initialize(..., logger=logger)` is the only public construction path.
Select the backend with its namespace config. The legacy SQLite keyword form
remains supported for compatibility, but new code should use `sqlite.Config`.

```python
from pathlib import Path

from snekql import Database, sqlite


db = await Database.initialize(
    sqlite.Config(database=Path("app.db"), pool_size=5),
    logger=logger,
    models=[User],
)
memory_db = await Database.initialize(
    sqlite.Config(database=":memory:"),
    logger=logger,
)
```

snekql requires a structured logger. The logger must use the structlog-style
shape `logger.debug("event", field=value)`. stdlib
`logging.Logger` is not accepted directly; wrap it in an adapter if needed.

```python
class AppLogger:
    def debug(self, event: str, **fields: object) -> None: ...
    def info(self, event: str, **fields: object) -> None: ...
    def warning(self, event: str, **fields: object) -> None: ...
    def error(self, event: str, **fields: object) -> None: ...


logger = AppLogger()
db = await Database.initialize(
    sqlite.Config(database=Path("app.db")),
    logger=logger,
    models=[User],
)
```

A stdlib logger can be adapted at the application boundary:

```python
class StdlibStructuredLogger:
    def __init__(self, *, logger: logging.Logger) -> None:
        self.logger = logger

    def debug(self, event: str, **fields: object) -> None:
        self.logger.debug(event, extra=fields)

    def info(self, event: str, **fields: object) -> None:
        self.logger.info(event, extra=fields)

    def warning(self, event: str, **fields: object) -> None:
        self.logger.warning(event, extra=fields)

    def error(self, event: str, **fields: object) -> None:
        self.logger.error(event, extra=fields)
```

MariaDB models should use the MariaDB namespace so backend-specific columns and
runtime checks agree:

```python
from snekql import Database, Fetched, Pending, insert, mariadb, select


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

db = await Database.initialize(config, logger=logger, models=[Account])
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
    first_email = await tx.fetch_one(select(User.email).all())
    await tx.execute(update(User).set(User.status.to("inactive")).all())
```

Runtime methods:

- `fetch_all(select(...))` returns all result rows.
- `fetch_one(select(...))` returns the first row or `None`.
- `execute(insert/update/delete)` returns `None`.
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

The package root is the public import surface. Prefer `from snekql import ...`
over importing from internal modules.

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

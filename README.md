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
    MISSING,
    CurrentTimestamp,
    Database,
    DateTime,
    Fetched,
    Integer,
    Model,
    Pending,
    StructuredLogger,
    Text,
    insert,
    select,
)


class User[S = Pending](Model[S, "User[Fetched]"]):
    id: User.GenCol[int] = Integer(
        primary_key=True,
        auto_increment=True,
        default=MISSING,
    )
    email: User.Col[str] = Text(nullable=False, unique=True)
    status: User.Col[str] = Text(nullable=False, default="active")
    created_at: User.GenCol[datetime] = DateTime(
        server_default=CurrentTimestamp(),
        default=MISSING,
    )


async def main(logger: StructuredLogger) -> None:
    db = await Database.initialize(
        logger,
        database=Path("app.db"),
        models=[User],
        schema_policy="strict",
        pool_size=5,
        acquire_timeout=30.0,
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

Models directly subclass `Model[S, "ModelName[Fetched]"]`. Application-created
instances are `Pending`; database reads return `Fetched` instances.

```python
class AuditLog[S = Pending](Model[S, "AuditLog[Fetched]"]):
    __tablename__ = "audit_log"

    id: AuditLog.GenCol[int] = Integer(
        primary_key=True,
        auto_increment=True,
        default=MISSING,
    )
    message: AuditLog.Col[str] = Text(nullable=False)
    created_at: AuditLog.GenCol[datetime] = DateTime(
        server_default=CurrentTimestamp(),
        default=MISSING,
    )
```

Rules to remember:

- `Col[T]` is a normal persisted column.
- `GenCol[T]` is server/generated; pending values may be `MISSING`, fetched
  values are `T`.
- If `__tablename__` is omitted, class names become snake_case table names.
- Models are immutable after construction/materialization.
- Fetched models are produced by database reads only.

## Storage classes

- `Integer`
- `Real`
- `Text`
- `Blob`
- `Json` stores `JSON` text.
- `Boolean` stores `0` / `1` in an `INTEGER` column.
- `DateTime` stores UTC text as `YYYY-MM-DDTHH:MM:SS.SSSZ`.

All storage declarations accept `unique=True` for column-level unique indexes.
SQLite allows multiple `NULL` values in a unique index, so use `nullable=False`
when uniqueness should also require a value. Primary-key columns reject
`unique=True` because it is redundant.

`CurrentTimestamp()` is the only v1 server default and is valid only on
`DateTime` `GenCol` fields.

## Indexes

Use `Index(...)` in `__indexes__` for table-level indexes:

```python
from snekql import Index

class User[S = Pending](Model[S, "User[Fetched]"]):
    email: User.Col[str] = Text(nullable=False, unique=True)
    status: User.Col[str] = Text(nullable=False)
    tenant_id: User.Col[int] = Integer(nullable=False)

    __indexes__ = [
        Index(status),
        Index(tenant_id, email, unique=True),
        Index(tenant_id, name="ix_user_tenant_custom"),
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
`.eq(...)`, `.ne(...)`, `.is_null()`, `.in_(...)`, `.like(...)`; Python
comparison operators are not part of the v1 API.

## Runtime

`Database.initialize(logger, ...)` is the only public construction path. Select a backend
with its namespace config. SQLite can be selected explicitly with the backend
namespace, while the original SQLite keyword form remains supported.

```python
from snekql import sqlite

db = await Database.initialize(logger, sqlite.Config(database=Path("app.db")), models=[User])
legacy_db = await Database.initialize(logger, database=Path("app.db"), models=[User])
memory_db = await Database.initialize(logger, sqlite.Config(database=":memory:"))
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
    logger,
    sqlite.Config(database=Path("app.db")),
    models=[User],
)
```

A stdlib logger can be adapted at the application boundary:

```python
class StdlibStructuredLogger:
    def __init__(self, logger: logging.Logger) -> None:
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
from snekql import MISSING, Database, Fetched, Pending, insert, mariadb, select


class Account[S = Pending](mariadb.Model[S, "Account[Fetched]"]):
    id: Account.GenCol[int] = mariadb.Integer(
        primary_key=True,
        auto_increment=True,
        default=MISSING,
    )
    email: Account.Col[str] = mariadb.Text(nullable=False, unique=True)


config = mariadb.Config(
    database="app",
    host="127.0.0.1",
    port=3306,
    user="snekql",
    password="secret",
)

db = await Database.initialize(logger, config, models=[Account])
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

# Connections and transactions

Keep a `Database` open for the lifetime of your service or worker. Open a new
transaction for each unit of work. Share the Database, not a live transaction,
between concurrent tasks.

## Connect to SQLite

```python
from pathlib import Path

from snekql import sqlite


async def check_connection() -> None:
    async with await sqlite.Database.initialize(
        sqlite.Config(database=Path("app.db")),
    ) as db:
        # Use db here. This example only checks connectivity.
        print(db.pool_stats())
```

Initialization opens the connection pool and checks required engine settings.
It does not create tables or apply migrations. See [getting started](getting-started.md)
for a complete application or [service recipes](service-recipes.md) for separating
deployment from startup.

Use `database=":memory:"` for a temporary SQLite database. Replacing its connection
loses its contents; use a file when data must survive connection replacement.

## Connect to MariaDB

Install `snekql[aiomysql]`. Your models, queries, config, and Database must all use
the MariaDB namespace:

```python
from os import environ

from snekql import mariadb


async def check_connection() -> None:
    config = mariadb.Config(
        database="app",
        host="db.example.com",
        user="app_user",
        password=environ["DATABASE_PASSWORD"],
        tls=mariadb.TLSConfig(),
    )
    async with await mariadb.Database.initialize(config) as db:
        print(db.pool_stats())
```

This needs a real server, credentials, and a certificate trusted by the client.
Configure your CA and client certificates as needed. See [verified TLS](engine-settings.md#verified-tls)
and [supported MariaDB releases](mariadb-support.md). Local examples are not a
reason to disable TLS on production TCP connections.

## Commit or roll back as a block

Given the `User` model from [getting started](getting-started.md):

```python
async with db.transaction() as tx:
    await tx.execute(sqlite.insert(User(email="ada@example.com")))
# Normal exit commits. An exception leaving the block rolls back.
```

Do not keep using `tx` after the block exits. Do not run two operations on it
concurrently, hand it to another task, or move it to another event loop.

You can use `tx.begin_nested()` for an explicit savepoint. It does not create a
second connection or commit the outer transaction. Not every database failure
is recoverable with a savepoint. Read [nested transactions](error-handling.md#explicit-nested-transactions)
before catching errors and continuing.

## Stream large results

`fetch_all` loads and validates the whole result in memory. For a large query,
fetch bounded batches:

```python
async with db.transaction() as tx:
    async with tx.fetch_chunks(sqlite.select(User).all(), size=500) as stream:
        async for batch in stream:
            for user in batch:
                print(user.email)
```

The stream holds the transaction's connection until it closes. Keep it inside
both context managers and consume it in the task that opened it. Do not run
another query on the transaction while its stream is open.

MariaDB uses an unbuffered cursor here. Processing still takes time on the event
loop, including validation. Streaming bounds the batch size; it does not move
CPU-heavy work into another thread.

## Set timeouts for database work

Configs have two separate timeouts, both defaulting to 30 seconds:

- `acquire_timeout` limits waiting for and setting up a connection.
- `operation_timeout` limits each driver operation.

`db.transaction(timeout=5.0)` overrides both for that transaction. It is **not**
a five-second deadline for the whole Python block. Each driver operation gets
a fresh budget; application code between calls is not timed.

A timeout can leave it unclear whether a write committed. Check
[commit outcomes](error-handling.md#commit-outcomes) before retrying. Never retry
just because an exception looks temporary.

## Choose durability, isolation, and locks

Use the linked guides for these deliberate choices:

- [SQLite durability](engine-settings.md#sqlite-durability-policy): WAL uses
  `synchronous=NORMAL` by default. Choose `durability="full"` for the stronger
  file-backed policy. Storage hardware still matters.
- [Isolation and read-only transactions](error-handling.md#transaction-isolation-and-access-mode):
  backend support differs. `read_only=True` is not a substitute for database permissions.
- [MariaDB row locks](error-handling.md#locking-selects): `.for_update()` supports
  blocking, nowait, and skip-locked policies for supported SELECTs. Keep the read
  and its write in the same transaction. SQLite has no emulated equivalent.

## Shut down cleanly

Stop accepting new work, let active work finish or cancel it deliberately, then
close the Database. An async Database context manager does the closing for you.
Call `await db.close()` when your application owns that lifetime manually.

Closing does not decide whether application work should commit, and it does not
forcibly end active transactions. Keep the event loop alive until cleanup finishes.
See [connection replacement, credential rotation, and shutdown](connection-lifecycle.md)
for failure and retry details.

Next: [service recipes](service-recipes.md) or [handling errors](error-handling.md).
[All guides](README.md)

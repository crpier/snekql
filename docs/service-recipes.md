# Deploying a service and adopting an existing database

Start with the [API reference](api-reference.md) and
[backend capability matrix](backend-capabilities.md). These recipes use SQLite
so they run without a server. They are source-checkout examples, not new
`snekql` framework integrations or installed package entry points. Copy the
modules into your application and update their `examples.*` imports.

The HTTP recipe is validated with FastAPI 0.141.1, Starlette 1.6.0 and httpx 0.28.1
on Python 3.14. Tests exercise the real ASGI app and lifespan without a network
listener. They do not certify every framework version or ASGI server deployment.
FastAPI and httpx are development dependencies here, never snekql runtime
requirements. An application using the recipe must install its own framework and
ASGI server.

## Deployment owns schema; startup owns connectivity

[`service_database.py`](../examples/service_database.py) contains a Table Model,
validated command data, a literal migration chain and two entry points:

- `await deploy(config)` connects, applies the chain, verifies history and verifies
  the model. Run it once in the authorized deploy job before releasing replicas.
- `async with open_service(config) as database` connects and verifies only. A
  missing migration history or schema mismatch fails startup. It does not fix the
  database behind the operator's back. Exit closes the Database even on failure.

A source-checkout deploy job can run:

```python
import asyncio
from pathlib import Path

from examples.service_database import deploy
from snekql import sqlite

asyncio.run(deploy(sqlite.Config(database=Path("service.db"))))
```

Use one persistent database path shared by the intended processes. Distinct
`:memory:` configurations are distinct databases, not a way for a deploy job to
prepare another process's database. Do not generate migrations from current
models at startup. Deployed migration bodies and checksums must remain stable.

For rolling releases, use the explicit reviewed suffix rules in
[rolling migrations](rolling-migrations.md). Passing a readiness check does not
prove that an old application understands a new schema. Back up the database and
plan irreversible migration recovery before deploying.

## FastAPI lifespan and dependency

[`service_app.py`](../examples/service_app.py) exports `create_app(config)`. A
small application module can contain:

```python
from pathlib import Path

from examples.service_app import create_app
from snekql import sqlite

app = create_app(sqlite.Config(database=Path("service.db"), pool_size=2))
```

Point the application's ASGI server at that module's `app`. Constructing it does
not open a database. Each server process enters lifespan and owns its own
Database. The dependency returns that Database, not a shared Transaction or a
connection borrowed from another library. Shutdown revokes the dependency and
closes the Database.

`POST /entries` accepts a bounded batch such as:

```json
{"entries": [{"entry_id": 7, "label": "ready"}]}
```

The route opens one explicit transaction and commits **before returning HTTP
201**. A duplicate primary key returns a value-free 409 after rollback, including
rollback of earlier entries in that batch. Other runtime failures return a
value-free 500. A failed commit is not permission to retry blindly; reconcile the
record and Commit Outcome evidence first. This example does not provide a
complete idempotency protocol, authentication or authorization.

Do not change the dependency into a request-wide yielded Transaction without
reviewing framework teardown timing. If commit runs after response delivery,
the client may receive success for a failed write. Streaming responses and
background tasks must not outlive a borrowed request transaction either. Own
those transactions explicitly in the task that performs the database work.

For MariaDB, use that namespace's Config, Model, constructors and query verbs
throughout, replace the SQLite `STRICT` migration with reviewed MariaDB DDL, and
configure credentials/TLS outside source control. Do not pass a MariaDB Database
to these SQLite model/query functions. The lifecycle pattern applies to both
backends; this particular HTTP example is tested on SQLite. Native MariaDB
behavior remains covered by the backend suite and [test-server examples](testing-mariadb.md).

## Background worker

[`service_worker.py`](../examples/service_worker.py) consumes an async iterable of
`EntryInput` commands. It verifies once at startup, owns a Database for that
worker, and opens a fresh transaction for each delivered command. No transaction
is held while waiting for the next delivery. A failed job stops this simple
worker; prior committed jobs remain committed. Cancellation propagates through
the transaction and Database context managers.

A production queue adapter must acknowledge a delivery only after its transaction
exits successfully. Database commit and broker acknowledgment are separate
operations. A crash between them can cause redelivery. Choose an application
idempotency/outbox strategy; a unique key alone does not prove that a duplicate
has the same intended payload. Do not implement automatic replay merely because
an exception looks transient. The [retry example](../examples/transaction_retry.py)
shows how Commit Outcome limits retry eligibility.

Scale with separate transaction scopes, not by sharing a live Transaction between
tasks. Budget the sum of all replica/worker pool capacities, plus the existing
layer's pools and deploy jobs. A pool limit is per Database, not a host-wide
connection budget.

## Database fixtures and transaction testing

[`service_fixtures.py`](../examples/service_fixtures.py) contains function-scoped
snektest fixtures. `empty_config()` owns a temporary file path; `fresh_database()`
runs the real literal migrations and readiness checks. It closes the Database
before the directory fixture tears down. There is no model-driven `create_all`
or scaffold-based recreation of deployed history.

The copyable tests in [`test_service_recipes.py`](../tests/test_service_recipes.py)
show request tests, independent-pool commit visibility, explicit rollback,
failed-COMMIT behavior, worker transaction boundaries, and fixture consumption.
Tests open a new transaction to inspect committed results rather than keeping
one outer rollback transaction around code that owns separate connections.
The native COMMIT failure test injects a driver fault; normal request tests use
real SQLite and the real FastAPI ASGI stack.

From the checkout:

```sh
uv sync --locked --all-extras
uv run snektest tests/test_service_recipes.py tests/test_api_reference.py
uv run ty check
```

HTTPX's ASGI transport does not start lifespan itself. The tests explicitly enter
`application.router.lifespan_context(application)` before issuing requests.
The app's typed dependency therefore runs against the same initialized Database
that production lifespan owns. These tests run as part of the normal suite.

## Incremental adoption

1. Inventory tables, codecs, NULL/default semantics, collation and transaction
   boundaries in the existing application. Choose a small query path to move;
   do not replace schema ownership and every query at once.
2. Declare models for only the selected tables. Review the [compatibility audit](schema-compatibility-audit.md).
   A successful partial `verify` is not proof of every CHECK, trigger or data
   invariant; retain the existing layer's validation where it still owns those.
3. Keep the current migration system as the sole owner initially. Run its deploy
   job, then use [`open_existing(config)`](../examples/incremental_adoption.py)
   for snekql readiness. That function verifies models without creating or
   stamping a snekql migration history. Do not call `verify_migrations` for a
   history snekql does not own.
4. Move reads first where practical. Compare decoded results, ordering and query
   costs on representative data. Move one complete write transaction at a time,
   with rollback and uncertain-commit behavior tested before rollout.
5. If schema ownership later moves to snekql, perform a separate reviewed
   [baseline adoption](migration-baselines.md) with backups, quiesced writers,
   populated-adoption tests and fresh-replay tests. Never stamp arbitrary old
   migrations to make a startup check pass.

SQLAlchemy, another driver or an existing repository can point at the same
physical database, but its pool and snekql's pool remain separate. Their
transactions do not join, share rollback, or become atomic through nesting Python
context managers. The executable coexistence test commits through raw aiosqlite,
rolls back a later snekql transaction, and confirms that the external commit
remains. No bridge for borrowing SQLAlchemy connections is provided.

Keep operations that must be atomic in one layer's transaction. Coordinate
cross-layer effects through an explicit application protocol; do not imply
cross-database or cross-broker atomicity. With SQLite, avoid holding one layer's
write transaction while awaiting another layer's writer. With either backend,
review total pool capacity, isolation, retries, deadlines and migration ownership
before enabling both paths in production.

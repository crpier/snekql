# Migrations

A migration is an async Python function identified by a stable revision ID.
It can execute reviewed SQL, inspect data, or call application-owned checks.
snekql manages the connection, ordering, migration history and transaction
completion. Your code decides what work is necessary.

Opening a Database does not create tables or run migrations. Fresh databases
replay the complete chain. Migration functions must not generate historical SQL
from current models at runtime.

## Scaffolding the first table

**Start here for a new application.** Declare the models, generate the initial
DDL, then review and commit it inside a migration function:

```python
from snekql import sqlite

print(sqlite.scaffold([User]))
```

Copy the generated statements into `migration.execute(...)` calls. For example,
a reviewed initial migration might look like:

```python
from snekql import sqlite


async def create_user(migration: sqlite.MigrationContext) -> None:
    await migration.execute("""
              CREATE TABLE "user" (
              "id" INTEGER PRIMARY KEY AUTOINCREMENT,
              "email" TEXT NOT NULL
              ) STRICT
          """)


MIGRATIONS = {"001_create_user": create_user}
```

Generate once during development, not at application startup. `scaffold` emits
initial table/index DDL; it does not diff models, generate ALTER statements or
apply changes. The committed migration is an immutable release artifact.

The [runnable tutorial](getting-started.md) contains a complete model and query.
[Service recipes](service-recipes.md) separate deployment from replica startup.

## Lifecycle

Deployment explicitly applies the chain and checks its resulting contract:

```python
async with await sqlite.Database.initialize(config) as db:
    await db.migrate(MIGRATIONS)
    await db.verify_migrations(MIGRATIONS)
    await db.verify([User])
    await check_application_invariants(db)
```

These operations answer different questions:

- `migrate`: execute pending functions and record successful revisions.
- `verify_migrations`: require the expected recorded revision chain.
- `verify`: compare the supported structural facts against current models.
- Application checks: validate additional data, catalog or external conditions.

Initialization proves connectivity, not readiness. Verification is partial, not
proof that arbitrary Python effects occurred. Callers decide when their required
checks establish readiness. Do not verify intermediate revisions against today's
models: intermediate schemas can legitimately differ.

Replicas that do not migrate run history/schema/application checks before
accepting work. Migration execution remains a deliberate deployment decision.

## One complete linear chain

Supply an ordered mapping of revision IDs to async functions:

```python
async def add_status(migration: sqlite.MigrationContext) -> None:
    await migration.execute(
        "ALTER TABLE user ADD COLUMN status TEXT NOT NULL DEFAULT 'active'"
    )


MIGRATIONS = {
    "001_create_user": create_user,
    "002_add_status": add_status,
}
```

Only pending functions execute, sequentially, after migration coordination and
history validation. Checks that must run on every deployment belong outside the
functions. Work inside a migration can hold database locks while it runs; keep
that work bounded and use asynchronous I/O or an executor for blocking I/O.

Every call declares the complete canonical chain for this code version, not an
independent feature subset. Mapping iteration order is authoritative; IDs are
opaque, case-sensitive UTF-8 strings of 1–255 characters, without NUL. Names and
function references are snapshotted before database acquisition. Functions must
accept one context argument and return `None`.

## Revision history

`snekql_migrations` records positive one-based `position`, byte-exact `name`,
and an observability timestamp `applied_at`. History must be an exact ordered
prefix of the declaration before pending work runs. Holes, removed/reordered/
renamed IDs, unknown revisions and history ahead of the declaration are errors.

**There are no body checksums.** Changing a function under an applied ID does
not rerun it or produce an error. Keep deployed functions and the helpers they
use immutable; make a new revision for corrections. Historical model imports,
mutable configuration and external resources can change behavior without changing
identity. Authors own reproducibility of their release artifacts.

SQL-string declarations and older history layouts are unsupported. There is no
adoption, conversion, stamping or compatibility path for those formats.

`migrate` returns an immutable `MigrationResult` with ordered `applied` and
`already_applied` tuples.

## Migration context

`MigrationContext` exposes the managed migration connection, not a pool:

- `await migration.execute(sql, params=...) -> int`: execute one statement and
  return its driver row count (which can be `-1` for statements without a count).
- `await migration.fetch_all(sql, params=...) -> list[tuple[object, ...]]`:
  execute one statement and fetch native tuple rows, without model decoding.

Parameters use native placeholders: SQLite `?` or named parameters; MariaDB `%s`
or named percent placeholders. Omitting parameters preserves literal percent
signs in MariaDB SQL; supplying parameters enables driver interpolation.

Execute multiple statements with multiple awaited calls in the same function.
A SQLite CREATE TRIGGER containing internal semicolons is one statement.
The context has no commit, rollback, nested-transaction or pool methods.
Transaction-control SQL, session reconfiguration, temporary-object creation and
access to migration history are restricted. Contexts expire when the function
exits, including failure/cancellation, and cannot be used by child tasks.

## Status and pending plans

```python
status = await db.migration_status(MIGRATIONS)
```

The immutable result contains ordered `applied` and `pending` IDs plus
`history_present`. Inspection does not execute functions, create history or
reserve a plan. Missing history does not mean application tables are absent.

### Command line

```sh
uv run python -m snekql migrations status \
  --database myapp.deploy:open_database --migrations myapp.schema:MIGRATIONS --json
uv run python -m snekql migrations plan \
  --database myapp.deploy:open_database --migrations myapp.schema:MIGRATIONS
```

The trusted database export is a zero-argument async-context-manager factory
that yields a Database. Importing either export executes trusted application
module code; bodies are not invoked by inspection. `plan` lists pending IDs.
There is no SQL-preview option: inspecting arbitrary Python must not execute it
or imply its SQL can be predicted. Output is emitted only after cleanup.

## Read-only verification

`await db.verify_migrations(MIGRATIONS)` requires the exact declared head without
executing bodies or changing history. It does not verify schema or data effects.

## Rolling deployments

A replica can explicitly approve a known later suffix:

```python
await db.verify_migrations(
    known,
    policy="compatible",
    approved_later=reviewed_later,
)
```

The complete known prefix must be applied; any later applied revisions must be
an ordered prefix of the approved suffix. This does not authorize migration of
unknown revisions or skip structural/application checks. Approvals identify IDs,
not fingerprints of Python behavior.

### Interaction with schema verification

History compatibility is not schema compatibility. Independently verify the
model contract required by that replica and application-specific invariants.

## Failure and transaction behavior

A failed function stops the chain and is not recorded. Previously committed
revisions remain applied. A retry skips recorded revisions and invokes pending
functions again. Preserve exception causes for diagnostics; do not interpret a
failure as proof that no effects occurred.

### SQLite

Each pending function and its history insertion share a `BEGIN IMMEDIATE`
transaction. Competing runners recheck history under the writer lock before
executing a function. Database effects roll back on failure, including DDL.
Cancellation or a lost acknowledgement around commit can arrive after success;
inspect history before deciding whether to retry.

#### Table rebuilds

Use separate context calls for create/copy/drop/rename statements. Keep foreign
key enforcement enabled; reviewed deferred constraints may support a particular
rebuild, but do not assume every rebuild sequence is safe.

### MariaDB

A connection-scoped advisory lock coordinates the migration run. Transactional
InnoDB DML and history commit together. DDL can implicitly commit earlier work;
a failed or interrupted function can leave unrecorded persistent effects.
Review and reconcile them before retrying. The runner retains ownership of
transaction and lock completion and discards connections with uncertain lock
cleanup.

### External actions

Filesystem, network and other Python effects are not rolled back by either
backend. A function may run again after failure or a crash. The library does not
promise exactly-once external actions; use application-specific idempotency,
reconciliation or explicit operator review.

## Recovery and deployment procedures

See [interrupted-migration recovery](migration-recovery.md) and the executable
[recovery example](../examples/migration_recovery.py).

## Existing databases without history

A reviewed initial [baseline](migration-baselines.md) can establish a new chain
for an existing untracked database. This is not old snekql-history conversion.
`IF NOT EXISTS` is not schema validation; review before recording history.

## Deployment and tests

Tests replay the committed chain like production, then verify schema and
application invariants. Do not bypass migrations with model-direct creation or
recompute deployed SQL from current models. See [service fixtures](service-recipes.md).

[All guides](README.md)

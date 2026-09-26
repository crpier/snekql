# Migrations

A migration is a named SQL change you keep in source control. snekql runs changes
in order and records their names and checksums, so later deployments can apply
only what is new.

You write and review the SQL. snekql does not turn model changes into ALTER TABLE
statements, and opening a Database does not create tables. An empty database is
built by running the complete migration chain.

Start with the [runnable tutorial](getting-started.md) for one table. For an
application, separate [deployment from service startup](service-recipes.md).
Existing databases need a [baseline](migration-baselines.md), and interrupted
migrations need [recovery review](migration-recovery.md), not a blind retry.

## Lifecycle

`Database.initialize(...)` only opens connectivity. A deploy applies and checks
the complete migration declaration, then separately checks the live schema
against current Table Models:

```python
MIGRATIONS = {
    "001_create_user": (
        'CREATE TABLE "user" ('
        '"id" INTEGER PRIMARY KEY AUTOINCREMENT, '
        '"email" TEXT NOT NULL'
        ") STRICT"
    ),
    "002_add_user_status": (
        'ALTER TABLE "user" ADD COLUMN "status" TEXT NOT NULL DEFAULT \'active\''
    ),
}

db = await Database.initialize(database=Path("app.db"))
result = await db.migrate(MIGRATIONS)
await db.verify_migrations(MIGRATIONS)
await db.verify([User])
```

These checks answer different questions:

- `verify_migrations(MIGRATIONS)` proves that recorded names, positions, and
  exact SQL checksums are at this code version's complete head.
- `verify([User])` checks the live tables against the current model
  contract. It does not prove that data migrations, triggers, or other effects
  ran.

Replicas that do not apply migrations should run `initialize ->
verify_migrations -> verify` before accepting traffic.

## One complete linear chain

`migrate()` accepts an ordered `dict[str, str]`. Every call supplies the one
complete canonical declaration for that code version. Mapping insertion order is
authoritative; names are opaque and are never parsed as versions.

Do not compose independent subsets per feature, environment, or process:

```python
# Correct: the later code version still declares the complete prefix.
MIGRATIONS = {
    "001_create_user": CREATE_USER_SQL,
    "002_add_status": ADD_STATUS_SQL,
}

# Incorrect: this is not an independently composable migration subset.
await db.migrate({"002_add_status": ADD_STATUS_SQL})
```

The mapping is synchronously copied and validated before connection acquisition.
Names and bodies must be exact built-in strings and valid UTF-8. Names must be
non-empty and at most 255 characters; bodies must contain SQL. Later mutations
of the caller's dictionary cannot alter an in-progress run.

Once a migration has been applied anywhere, never remove, reorder, rename, or
edit it. Append a new entry instead. A body that failed before its history row
was recorded remains pending and may be fixed.

## Migration History v2

The `snekql_migrations` table stores one row per migration:

| Column | Meaning |
| --- | --- |
| `position` | Positive, unique, one-based declaration ordinal |
| `name` | Non-empty unique caller identity, compared byte-exactly |
| `checksum` | Lowercase SHA-256 of the exact UTF-8 SQL body |
| `applied_at` | Server-side UTC timestamp for observability only |

MariaDB stores names and checksums with unpadded binary comparison. Both
backends enforce the correctness-bearing shape in their history DDL.

Before pending SQL runs, `migrate()` requires recorded history to equal the
declaration prefix:

```python
actual == expected[: len(actual)]
```

It rejects holes, reordered or removed entries, renamed migrations, edited
bodies, unknown rows, and history longer than the declaration. An empty
declaration still inspects history and therefore fails against non-empty
history.

`migrate()` returns an immutable `MigrationResult`:

```python
MigrationResult(
    applied=("003_add_audit",),
    already_applied=("001_create_user", "002_add_status"),
    legacy_adopted=False,
)
```

Both tuples follow declaration order. `legacy_adopted` is true when the call
adopted existing non-empty v1 names with the declared checksums or completed a
previously consented MariaDB staging upgrade. This trusts legacy records; it is
not the reviewed-baseline workflow for an untracked schema.

## Status and pending plans

Inspect the complete declaration without applying it:

```python
status = await db.migration_status(MIGRATIONS)
print(status.history_present)
print(status.applied)  # ordered tuple of recorded names
print(status.pending)  # ordered tuple of remaining names
```

Both backend namespaces export the frozen `MigrationStatus` result. The
operation snapshots and validates declarations before connection acquisition,
then requires history to match an exact ordered, checksummed prefix. It rejects
legacy, staged, malformed, or divergent history with `MigrationHistoryError`.
It never creates history, adopts a baseline, executes migration bodies, or
acquires the migration writer/advisory lock.

Absent history returns `history_present=False`, no applied names, and every
name pending. A valid empty history table returns `history_present=True`.
Neither case proves that the application schema is empty. Likewise, pending
MariaDB DDL may already have committed some effects without recording history.
Status does not inspect those effects or prove that a migration can execute.

This is point-in-time information, not a reservation or an executable plan
object. Another deploy may advance history immediately afterward. Apply with
`db.migrate(MIGRATIONS)`, which obtains its normal lock and rechecks history.
`verify_migrations()` remains the separate readiness check that requires the
configured head or approved compatibility range.

### Command line

Export an ordered declaration and a zero-argument factory returning an async
context manager from an importable application module. The context manager must
yield a SQLite or MariaDB `Database` and close it on exit. For example,
`app/deploy.py` can define:

```python
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from snekql import sqlite

MIGRATIONS = {
    "001_entries": "CREATE TABLE entries (id INTEGER PRIMARY KEY)",
    "002_note": "ALTER TABLE entries ADD COLUMN note TEXT",
}


@asynccontextmanager
async def open_database() -> AsyncIterator[sqlite.Database]:
    async with await sqlite.Database.initialize(database=Path("app.db")) as db:
        yield db
```

Then inspect it with:

```bash
snekql migrations status --database app.deploy:open_database --migrations app.deploy:MIGRATIONS
snekql migrations plan --database app.deploy:open_database --migrations app.deploy:MIGRATIONS
snekql migrations plan --database app.deploy:open_database --migrations app.deploy:MIGRATIONS --json --sql
```

`status` lists applied and pending names. `plan` lists pending names. Both accept
`--json` and emit the same status fields:

```json
{"history_present": true, "applied": ["001_entries"], "pending": ["002_note"]}
```

SQL is omitted by default. Only `plan --sql` includes pending bodies; with JSON
it adds a `sql` object mapping pending names to exact original bodies. SQL may
contain secrets, so treat that output accordingly. The CLI snapshots the
exported declaration before entering the database context, and waits for cleanup
before printing a successful report.

Exit codes are `0` for successful inspection, even with pending migrations,
`1` for inspection/configuration/cleanup failure, and `2` for invalid command
arguments. Failures produce no success document. Command error messages omit
arbitrary exception text and tracebacks; use the Python interface when detailed
exception diagnosis is needed.

References must use `module:attribute`; expressions and factory arguments are
not accepted. These are trusted Python imports, not a sandbox. Module imports
and factories can execute application code. Keep them free of migration or
other write side effects and avoid printing to stdout when using JSON. Normal
connection initialization still applies backend settings and may create a
SQLite database file. Do not put credentials in command arguments; load them
inside your application's factory. Use a normal `@asynccontextmanager` factory,
not an async function returning a context manager that would need another await.

## Read-only verification

`verify_migrations(MIGRATIONS)` defaults to `policy="strict"`, requiring exact
equality with the declaration's full head. It does not create the history table, acquire the migration lock,
upgrade legacy history, adopt a baseline, or execute migration SQL.

It fails when:

- a non-empty declaration has no history table;
- any migration is pending or divergent;
- history is v1, an upgrade staging shape, or an unknown shape;
- an empty declaration encounters non-empty history.

An empty declaration succeeds when no history table exists.

## Rolling deployments

Strict verification remains the default and can be requested explicitly:

```python
await db.verify_migrations(MIGRATIONS, policy="strict")
```

An older application can permit specific later changes without accepting unknown
history. Supply its complete known declaration and a separately reviewed,
ordered suffix:

```python
KNOWN = {
    "001_entries": "CREATE TABLE entries (id INTEGER PRIMARY KEY)",
}
APPROVED_LATER = {
    "002_note": "ALTER TABLE entries ADD COLUMN note TEXT",
}

await db.verify_migrations(
    KNOWN,
    policy="compatible",
    approved_later=APPROVED_LATER,
)
```

The check requires all of `KNOWN` to be applied, followed by zero or more entries
from the start of `APPROVED_LATER`. Every recorded position, name, and exact SQL
checksum must match. It rejects missing known migrations, holes, changed or
reordered history, skipped approvals, and anything beyond the approved suffix.
Names remain opaque; there is no version-name comparison or wildcard approval.

`approved_later` is required with `policy="compatible"`. An empty dictionary
permits no later history. Strict policy rejects any non-`None` approval argument,
including `{}`, rather than silently ignoring it. Both declarations use the
existing declaration and backend body validation rules, and their names must not
overlap. Both are snapshotted before connection acquisition. Invalid arguments
raise `MigrationDeclarationError`; rejected history raises `MigrationHistoryError`.
An empty known chain needs no history table, even if later migrations are approved.
Legacy or malformed history still fails.

Verification remains read-only. It does not execute pending approvals, acquire
the migration lock, create history, or adopt a baseline. `migrate()` still
requires the complete canonical chain and does not accept these policy arguments.
Old application replicas should verify, not run their shorter chain as migrators.

A rolling deployment can follow this order:

1. Review the next changes against every application version that will remain
   active or be eligible for rollback. Ship exact suffix approvals with those
   applications or through a controlled deployment configuration.
2. Run one deploy job with the complete new declaration. Apply it using
   `migrate()` and verify its exact head using strict policy.
3. Start new replicas. Old replicas can restart or roll back their application
   code while recorded history stays within their approved range.
4. Before a breaking contract migration, drain the incompatible application
   versions and remove them from rollback eligibility. Do not approve the
   contract migration for those versions. Their later startup checks will fail.

An approval is an application-specific decision, not a claim that SQL is additive
or backward compatible. snekql does not analyze migration bodies to make that
judgment. An incorrectly approved breaking migration can pass history verification.
Application rollback does not undo migrations or data changes.

### Interaction with schema verification

`db.verify([Model])` remains a separate structural check with its own policy.
Compatible migration history does not relax it. An extra column or index on a
modeled table can still fail strict schema verification, even if the migration
was approved for rolling deployment. Changes to unmodeled tables may not appear
in that check at all.

Keep strict schema verification where the model still matches. If a rollout
intentionally changes modeled structure, inspect the result of
`db.verify(..., policy="warn")` and apply an explicit application decision about
acceptable drift. Warning mode reports drift but does not enforce that only
approved differences occurred. Do not treat it as a blanket compatibility gate.
Test old and new reads, writes, defaults, constraints, and data semantics against
the migrated database; neither history approval nor schema verification proves
those behaviors.

Verification is a point-in-time check, not a migration lock held while the
application serves traffic. Deployment coordination must prevent a later breaking
migration from racing with incompatible running replicas.

## Failure and transaction behavior

`MigrationDeclarationError` reports invalid declarations before database I/O.
`MigrationHistoryError` reports malformed, divergent, legacy, or pending
history. `MigrationError` means a migration body failed, including a failed SQLite unit commit. Migration lock failures
use `MigrationLockError`, with `MigrationLockTimeoutError` for acquisition
timeouts.

The chain commits one successful migration at a time. If a later migration
fails, earlier rows and changes stay committed, the failing migration is not
recorded, and later migrations do not run.

### SQLite

Each pending migration runs in its own transaction:

1. `BEGIN IMMEDIATE` takes the writer lock before history is read.
2. History is ensured or atomically upgraded and checked again.
3. Every statement in the one pending body executes in order.
4. Its history row is inserted.
5. The body and history row commit together.

This serializes cooperating runners across independent connections. A body can
contain multiple persistent statements against the main database. All schema
changes, data changes, and its single history row commit together. A later
statement failure rolls back earlier statements in that body, but not previously
committed migration bodies. Deferred foreign-key violations at commit also roll
back the unit and raise `MigrationError`.

Statements are separated using SQLite's completeness scanner, not by splitting
on every semicolon. Trigger bodies, quoted semicolons, escaped quotes, and SQL
comments retain their meaning. The last statement may omit its terminating
semicolon. Empty statements and comments are ignored, but the body must contain
at least one SQL statement. Incomplete statements and forbidden operations are
rejected before acquisition; other SQL errors may be discovered during execution.
The checksum still covers the exact original body, including comments and spacing.
Never regroup already-applied migrations into a new multi-statement body.

Transaction control, `VACUUM`, `ATTACH`, `DETACH`, PRAGMAs, temporary application
objects, and access to package-owned Migration History remain prohibited. Every
statement is validated and runs under the authorizer. snekql executes statements
individually inside its transaction; it never uses `executescript()` and its
implicit transaction behavior. This is a trusted SQL migration interface, not a
sandbox for user-defined functions or external side effects.

Cancellation during the body rolls back the unit. Cleanup stays shielded, and a
connection whose cleanup cannot be confirmed is discarded. Cancellation around
commit can arrive after the unit has committed. Recheck history before deciding
whether it applied; do not assume every cancelled call implies rollback.

#### Table rebuilds

Keep a copy/drop/rename operation and index recreation in one body. For example,
a populated child table can be rebuilt while foreign keys remain enabled:

```python
REBUILD_CHILD = """
CREATE TABLE child_new (
    id INTEGER PRIMARY KEY,
    parent_id INTEGER NOT NULL REFERENCES parent(id),
    label TEXT NOT NULL,
    note TEXT NOT NULL DEFAULT 'added'
);
INSERT INTO child_new (id, parent_id, label)
    SELECT id, parent_id, label FROM child;
DROP TABLE child;
ALTER TABLE child_new RENAME TO child;
CREATE UNIQUE INDEX child_label ON child(label);
"""

# Append to the complete canonical declaration, not an independent subset.
MIGRATIONS = {**PREVIOUS_MIGRATIONS, "003_rebuild_child": REBUILD_CHILD}
await db.migrate(MIGRATIONS)
```

This example assumes the child table has no inbound foreign keys and no triggers
or views that need reconstruction. Authors must preserve those objects explicitly
where present. Foreign keys stay enabled; the runner does not silently disable or
defer them. Rebuilding a referenced parent can fail or invoke `ON DELETE` actions
when the old table is dropped. Do not assume this child-table recipe is safe for
parent tables, self-references, or cyclic relationships. Design and test those
changes with their actual constraints and data, including cascade behavior.

### MariaDB

MariaDB holds one connection-scoped `GET_LOCK` across history upgrade,
preflight, application, recording, and commits. Lock release is shielded and
must return success; otherwise the physical connection is discarded.

Transactional InnoDB DML and its history insert use one commit. MariaDB DDL
still commits implicitly, so a crash after successful DDL but before history
recording can cause that DDL to run again. Keep DDL idempotent where practical.
Multiple-statement bodies remain supported, and earlier DDL in a body can remain
committed if a later statement fails. Bodies cannot issue transaction control,
change required session settings, call advisory-lock functions, or execute
dynamic SQL because those operations could escape snekql's DML/history
transaction or leave a pooled connection misconfigured.

### Raw SQL and percent signs

MariaDB migration bodies are sent as raw SQL, without driver parameter
interpolation. Write literal percent signs, `LIKE 'prefix%'` and modulo
expressions such as `11 % 4` normally. Do not double percent signs for the
driver: SQL `'100%%'` stores two percent signs. Internal history and lock queries
still use bound parameters, including opaque migration names containing `%`.

Before upgrading from an affected version such as 0.7.0, audit historical bodies
for doubled-percent workarounds. Those versions incorrectly collapsed `%%` to
`%`. The corrected runner preserves both characters, so fresh replay can produce
different data or schema defaults even though the body checksum is unchanged.
Already-recorded bodies are not executed again; history verification does not
prove that an old database and a fresh replay have equivalent data.

Never edit applied bodies or recorded checksums to hide that difference. When the
historical bodies remain valid raw SQL, append an explicit migration that brings
both old and freshly replayed states to the intended result, and test both paths.
Do not apply a blanket percent replacement to application data.

If a workaround made a historical expression invalid as raw SQL, for example
`11 %% 4`, a corrective tail cannot repair a fresh replay that fails earlier.
Plan a controlled legacy-runner bootstrap followed by upgrade at the verified
head, or a separately managed baseline/rebuild procedure, before deploying the
new runner for that chain. snekql does not automatically rewrite history or infer
which percent signs were workarounds. Existing installations can skip already
recorded bodies, but fresh-install procedures still need this explicit plan.

## Legacy history adoption

History created before v2 contains only `(name, applied_at)`. It cannot prove
the original order or SQL bodies. Ordinary `migrate()` therefore rejects a
non-empty v1 table with instructions to opt in:

```python
result = await db.migrate(MIGRATIONS, adopt_legacy=True)
```

Adoption is a one-time statement of trust in the current declaration. It is not
historical verification. Legacy names must equal the set of names in one
declared prefix; unknown names, holes, inserted predecessors, and overlong
history are rejected. Positions and checksums are assigned from the current
declaration, and existing timestamps are preserved.

SQLite rebuilds v1 atomically. MariaDB uses restartable v1, staging, and final
v2 shapes because its DDL commits implicitly. Once exact staging exists, a
restart continues without asking for consent again and never overwrites a
populated checksum. An empty v1 table may upgrade without consent.
`verify_migrations()` never adopts or upgrades.

Back up the database and stop old application versions before adoption. An old
runner does not understand v2 history.

## Recovery and deployment procedures

- [Reconcile interrupted migrations](migration-recovery.md), including MariaDB
  DDL that committed without history and ambiguous commit acknowledgements.
- [Expand, backfill, and contract](rolling-migrations.md) with tested bounded
  batches, durable checkpoints, dual writers, and a coordinated contract gate.

## Existing databases without history

Start a reviewed initial baseline only when establishing the application's first
canonical snekql chain. Execute the same hand-authored body on fresh and existing
databases; never stamp an older chain as if it ran. See the
[reviewed baseline checklist and tested example](migration-baselines.md).
Legacy-history adoption is a different operation and does not validate schema
or historical data effects.

## Scaffolding the first table

`scaffold([Model])` is a development-time printer for initial DDL:

```python
from snekql.sqlite import scaffold

print(scaffold([User]))
```

Copy its output into source control and review it. Choose separate history
entries or group related SQLite statements into an atomic body, then treat the
literal SQL as immutable. Do not call `scaffold([CurrentModel])` while the application starts.
Model metadata can legitimately improve over time; recomputing historical SQL
would then change a v2 checksum.

Later changes remain hand-authored `ALTER`, `CREATE INDEX`, `UPDATE`, and other
raw SQL. snekql does not generate model diffs or down migrations.

## Deployment and tests

A release job commonly runs:

```text
initialize -> migrate -> verify_migrations -> verify
```

Application replicas commonly run:

```text
initialize -> verify_migrations -> verify
```

Tests should use an isolated database per canonical chain and replay the same
committed migration declaration as production. A test suite must not rely on
globally unique names to combine unrelated subsets in one history table; exact
prefix semantics deliberately reject that composition.

The bundled `basic` (SQLite) and `mariadb` examples contain committed,
one-statement Migration bodies and run the complete migrate → verify-history →
verify-schema path. Print them with `snekql --example basic` and
`snekql --example mariadb`. The repository suite executes both declarations and
checks that fresh replay and prefix-then-upgrade produce the same final catalog
shape on each backend.

[All guides](README.md)

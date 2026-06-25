# Migrations

snekql applies **migrations**: named, hand-authored, ordered changes — to schema
or data — that the runtime applies exactly once and records in a snekql-owned
Migration History. snekql runs and tracks migrations; it never generates them.

Migrations are the **sole schema-creation authority**: a table comes into
existence only by running a migration body. There is no automatic table creation
from Table Models. A fresh database is built by **replaying the whole migration
chain**.

## The lifecycle: initialize → migrate → verify

`Database.initialize(...)` is **connect-only**: it opens connectivity and a
connection pool and hands out transactions, and does no schema work at all. You
apply migrations with `db.migrate(...)` and check the resulting schema against
your models with `db.verify(...)`. Always show `migrate` and `verify` together:

```python
db = await Database.initialize(database=Path("app.db"))

await db.migrate(
    {
        "001_create_user": 'CREATE TABLE "user" (...) STRICT',
        "002_add_user_status": 'ALTER TABLE "user" ADD COLUMN "status" TEXT',
        "003_backfill_status": 'UPDATE "user" SET "status" = \'active\'',
    },
)
await db.verify([User, AuditLog])
```

`db.migrate(migrations)` takes an ordered `dict[str, str]` mapping a migration
**name** to its raw SQL body. Insertion order is the apply order.

### What `db.migrate` does

1. Holds the migration advisory lock (see [Concurrency](#concurrency)).
2. Ensures the Migration History table (`snekql_migrations`) exists.
3. Reads the set of already-applied names.
4. Computes the pending set: mapping keys not yet recorded as applied.
5. Runs each pending migration's body in mapping insertion order.
6. Records each migration's name in the Migration History after it succeeds.

`db.migrate` is models-free: it creates and changes schema, nothing more.
Checking the schema against your models is the separate job of `db.verify` (see
[schema-drift.md](schema-drift.md)), which is where the Schema Policy lives.

## Scaffolding the first CREATE TABLE

Hand-writing the initial `CREATE TABLE` for a model is tedious, so snekql ships a
dev-time **scaffold** that emits that DDL as text for you to own. It is a pure
function — no database, no diffing, no `ALTER` generation. You paste its output
into your migration set, and from that moment it is hand-authored like any other
body: append-only and immutable.

```python
from snekql.sqlite import scaffold

print(scaffold([User]))
# CREATE TABLE "user" ("id" INTEGER PRIMARY KEY AUTOINCREMENT,
#   "email" TEXT NOT NULL) STRICT;
# CREATE INDEX "ix_user_email" ON "user" ("email");
```

Each statement (the table, then each index) is a separate migration body, because
a body runs exactly one statement. The scaffold emits only the *initial* create;
later schema changes are migrations you write by hand.

## One canonical migration set per code version

Keep a single migration mapping per code version — never per-environment
mappings. The same chain replays everywhere, so every database is built the same
way. The Migration History is keyed by name, so set difference (pending = keys −
applied) is all that decides what runs.

## Deploy and replica topologies

The library blesses no deploy topology; the advisory lock keeps every arrangement
safe. Two common shapes:

- **Deploy step.** A release job runs `initialize → migrate → verify` once,
  applying the chain and confirming it against the models before traffic.
- **Replica boot.** Each app replica runs `initialize → verify` *without*
  migrating, confirming the already-migrated schema matches its build and failing
  fast on a forgotten migration.

You may instead let every replica call `migrate` and trust the lock; the choice
is yours. Documentation recommends migrating from one place and having replicas
only `initialize → verify`.

## Identity, ordering, and the append-only rule

- A migration's **identity is its name** (the dict key). Ordering is dict
  insertion order. There is no numeric/positional identity and no checksum.
- The mapping is **append-only**. Once a migration has run against any database,
  never rename it, never reuse its name for different SQL, and never change its
  body. Renaming makes snekql re-run the "new" name; changing a body silently
  diverges already-migrated databases from new ones. This is the sharpest
  correctness constraint migrations push onto you.
- Duplicate names are impossible by construction (they are `dict` keys).

## Idempotency and failure

snekql does **not** wrap a migration body and its history row in a single
transaction — you own any transaction control inside your SQL. As a result:

- A migration body and its bookkeeping are applied separately. If the process
  crashes between a body succeeding and its history row being written, that
  migration runs again on the next `migrate`. **Write idempotent migrations.**
- On the first failing migration, `migrate` halts and raises `MigrationError`
  naming the migration. Migrations that already succeeded stay recorded, so a
  fixed retry resumes from the failure point.
- On MariaDB, DDL auto-commits, so a multi-statement DDL body is not atomic;
  prefer single-statement or idempotent bodies.

## Concurrency

snekql coordinates concurrent migration runs so that several instances calling
`db.migrate(...)` at once are safe. Coordination is always on — there is nothing
to opt into.

The whole apply flow — ensure history, read applied, run pending, record — runs
while holding a backend advisory lock. The instance that wins the race applies the
pending migrations; the instances that lose **wait** for it, then re-read the now
complete Migration History and apply only what is still pending. No migration is
applied twice across instances.

**MariaDB** uses a connection-scoped named advisory lock (`GET_LOCK` /
`RELEASE_LOCK`). This is what makes concurrent `db.migrate(...)` against one
MariaDB database safe: without it, two instances could read the same empty
history and both apply the same migration, causing duplicate-DDL or double-data
errors. The lock name is namespaced per database, so migrations on unrelated
databases sharing a server do not block each other. A loser waits up to the
backend's `acquire_timeout`; if the holder never finishes within that window the
loser raises `MigrationLockTimeoutError` having applied nothing — a retry once the
holder is done observes the completed history. Because the lock is connection
scoped, it is released on success, on failure, and on disconnect (a crashed
instance frees it server-side).

**SQLite** has no advisory-lock primitive. Concurrent runs against one database
file instead serialize through SQLite's single-writer file lock, and the
configured `busy_timeout` makes a losing writer wait rather than immediately raise
"database is locked". This serialization is the de facto coordination on SQLite;
for a strong single-applier guarantee, still prefer running migrations from one
place.

## Testing with migrations

Tests build their schema by replaying the migration chain — the same construction
path as production — so a broken migration fails a test. There is no model-direct
schema shortcut anywhere in the library. A large suite can build the schema once
per session and isolate each test cheaply (a documented pattern, not a library
feature) rather than replaying the chain per test.

## Raw SQL only

Migration bodies are raw SQL in v1 — write `ALTER TABLE`, `CREATE INDEX`,
`UPDATE`, and so on by hand. A snekql-native schema-change builder may follow.

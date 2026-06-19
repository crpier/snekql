# Migrations

snekql applies **migrations**: named, hand-authored, ordered changes — to schema
or data — that the runtime applies exactly once and records in a snekql-owned
Migration History. snekql runs and tracks migrations; it never generates them.

You pass migrations to `Database.initialize(...)` as an ordered `dict[str, str]`
mapping a migration **name** to its raw SQL body. Insertion order is the apply
order.

```python
db = await Database.initialize(
    database=Path("app.db"),
    models=[User, AuditLog],
    migrations={
        "001_create_user": 'CREATE TABLE "user" (...) STRICT',
        "002_add_user_status": 'ALTER TABLE "user" ADD COLUMN "status" TEXT',
        "003_backfill_status": 'UPDATE "user" SET "status" = \'active\'',
    },
)
```

## What happens at startup

When `migrations` is provided, snekql:

1. Ensures the Migration History table (`snekql_migrations`) exists.
2. Reads the set of already-applied names.
3. Computes the pending set: mapping keys not yet recorded as applied.
4. Runs each pending migration's body in mapping insertion order.
5. Records each migration's name in the Migration History after it succeeds.
6. Verifies your `models` against the resulting schema under the Schema Policy.

Omitting `migrations` preserves the prior behavior exactly: snekql auto-creates
missing tables from `models` and verifies the rest.

## Applying migrations from a dedicated deploy step

`Database.initialize(migrations=...)` applies migrations as a side effect of
booting the app. For a release/deploy pipeline you usually want a step that
*only* applies migrations, without standing up the full runtime. Use
`Database.migrate(...)`:

```python
await Database.migrate(
    database=Path("app.db"),
    migrations={
        "001_create_user": 'CREATE TABLE "user" (...) STRICT',
        "002_add_user_status": 'ALTER TABLE "user" ADD COLUMN "status" TEXT',
    },
)
```

`Database.migrate` shares the exact apply runner and idempotency semantics as the
`initialize` path — it ensures the Migration History, computes the pending set,
runs each pending body once in insertion order, and records each success — but it
takes **no `models`**, runs **no schema startup or drift verification**, opens no
connection pool, and returns nothing. It applies migrations and exits. Drift
verification stays with `initialize`, where the `models` are available to verify
against.

It accepts the same backend selection as `initialize` (a `database=` path for
SQLite, or a backend `Config` as the first argument).

## Migrations are the sole schema-creation authority

When you pass `migrations`, snekql no longer auto-creates tables from `models`.
Migrations create the schema; the models are still **verified** afterward. A model
with no matching migration is reported as schema drift — under `strict` this fails
startup, which is the correctness net that keeps your migration list converging to
your models. See [schema-drift.md](schema-drift.md).

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
  migration runs again on the next startup. **Write idempotent migrations.**
- On the first failing migration, startup halts and raises `MigrationError`
  naming the migration. Migrations that already succeeded stay recorded, so a
  fixed retry resumes from the failure point.
- On MariaDB, DDL auto-commits, so a multi-statement DDL body is not atomic;
  prefer single-statement or idempotent bodies.

## Concurrency

snekql coordinates concurrent migration runs so that several instances calling
`initialize(migrations=...)` (or `migrate(...)`) at once are safe. Coordination is
always on whenever migrations are provided — there is nothing to opt into.

The whole apply flow — ensure history, read applied, run pending, record — runs
while holding a backend advisory lock. The instance that wins the race applies the
pending migrations; the instances that lose **wait** for it, then re-read the now
complete Migration History and apply only what is still pending. No migration is
applied twice across instances.

**MariaDB** uses a connection-scoped named advisory lock (`GET_LOCK` /
`RELEASE_LOCK`). This is what makes concurrent `initialize(migrations=...)` against
one MariaDB database safe: without it, two instances could read the same empty
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
place with [`Database.migrate(...)`](#applying-migrations-from-a-dedicated-deploy-step).

## Raw SQL only

Migration bodies are raw SQL in v1 — write `ALTER TABLE`, `CREATE INDEX`,
`UPDATE`, and so on by hand. A snekql-native schema-change builder may follow.

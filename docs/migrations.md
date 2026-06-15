# Migrations

snekql applies **migrations**: named, hand-authored, ordered changes — to schema
or data — that the runtime applies exactly once and records in a snekql-owned
Migration History. snekql runs and tracks migrations; it never generates them.

You pass migrations to `Database.initialize(...)` as an ordered `dict[str, str]`
mapping a migration **name** to its raw SQL body. Insertion order is the apply
order.

```python
db = await Database.initialize(
    logger=logger,
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

v1 does not coordinate concurrent migration runs across instances. Run migrations
from a single place; concurrent `initialize(migrations=...)` against the same
MariaDB database is undefined in v1.

## Raw SQL only

Migration bodies are raw SQL in v1 — write `ALTER TABLE`, `CREATE INDEX`,
`UPDATE`, and so on by hand. A snekql-native schema-change builder may follow.

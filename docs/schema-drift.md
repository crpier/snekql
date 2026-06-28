# Schema verification and drift

`db.verify(models, *, policy=...)` checks the live schema against your Table
Models. It is the **only** feedback loop tying the hand-written migration chain
back to the models — it catches "you changed the model but not the migration" and
"you rolled the app forward past the migration that feeds it". Verification never
creates anything: [migrations](migrations.md) are the sole schema-creation
authority.

Run `verify` after `migrate`, and show them together — forgetting `verify`
silently drops the migration↔model net:

```python
db = await Database.initialize(database=Path("app.db"))
await db.migrate({"001_create_user": 'CREATE TABLE "user" (...) STRICT'})
await db.verify([User, AuditLog])
```

## Verification is a partial, structural check

`verify` is a **semantic, structural tripwire, not a proof of schema equality**.
It compares only the facts snekql controls — the table shape — and is
deliberately blind to everything else. Comparison is semantic: columns and
indexes match by name regardless of declaration order, and cosmetic DDL
differences (identifier quoting, whitespace, type-keyword case, column/index
ordering) are ignored. A table legitimately built or evolved by migrations is
recognized as matching whenever it is semantically equal to the model.

`verify` **does** compare:

- table presence;
- per column: name, storage type / affinity-class, nullability, primary-key,
  auto-increment, *whether* a server default exists, collation;
- per index: name, columns, uniqueness;
- per foreign key: local column → target table/column;
- table storage-option tokens (SQLite `STRICT`, MariaDB `ENGINE=InnoDB`).

`verify` **does not**, and across backends *cannot*, see:

- default **values** — only *whether* a default exists, so a changed default
  value passes;
- `CHECK` constraints;
- generated-column expressions;
- triggers and views;
- exact SQLite types (affinity collapses `VARCHAR(255)` and `TEXT`);
- data.

A migration that sets a wrong default value, adds a `CHECK`, or installs a
trigger therefore **passes** verification. This is a bound of each backend's
catalog introspection, documented and deliberate — not a bug. Treat `verify` as a
structural net for the drift that breaks queries, not a behavioral guarantee.

## How drift is detected

1. Generate the expected table shape (columns, indexes, foreign keys, and
   table-level storage options) for each model.
2. Read the live table shape from the selected backend's catalog (SQLite via
   `PRAGMA`, MariaDB via `INFORMATION_SCHEMA`).
3. Diff the two shapes. Columns and indexes match by name independent of
   declaration order; only the facts snekql controls are compared.
4. Report each divergence, naming the specific table, column, index, or foreign
   key, and treat any divergence — including a missing table — as schema drift.

Because generated SQLite tables are always `STRICT`, an existing SQLite
non-`STRICT` table is reported as a storage-option divergence; MariaDB likewise
requires the `InnoDB` engine. Extra, missing, renamed, or uniqueness-changed
indexes on managed tables are also schema drift. SQLite verifies foreign-key
constraints against the model; MariaDB foreign keys are created with the table
but not verified, because MariaDB auto-creates a backing index for each
constraint.

The Migration History table (`snekql_migrations`) is snekql-owned and is never
verified; keep it out of the `models` you pass to `verify`.

Verification is **read-only on both backends and leaves no schema change**,
however it fails. SQLite runs the inspection inside a transaction it always
rolls back (it never commits during verify); MariaDB reads `INFORMATION_SCHEMA`
with no transaction. That asymmetry is invisible to callers: because `verify`
only reads, a failed or drift-raising `verify` leaves the schema exactly as
`migrate` left it. The partial-state question therefore lives entirely in
[migrations](migrations.md#idempotency-and-failure), never in `verify`.

## Schema Policy

The Schema Policy lives on `verify` — it is the choice of how the step that
*detects* drift handles it.

`policy="strict"` is the default. Drift raises `SchemaVerificationError`:

```python
await db.verify([User], policy="strict")
```

`policy="warn"` logs each divergence and continues:

```python
await db.verify([User], policy="warn")
```

Use `warn` when adopting snekql in an environment where you want observability
before enforcing drift failures.

## Deploy and replica use

- A **deploy step** runs `initialize → migrate → verify`, applying the chain and
  confirming it against the models before traffic.
- An **app replica** runs `initialize → verify` (no migrate) to confirm the
  already-migrated schema matches this build's models and fail fast on a
  forgotten migration.

Both follow the caller's topology (see [migrations.md](migrations.md)).

## What verification does not do

`verify` does not:

- create, alter, or drop anything;
- generate migrations;
- preserve or transform data.

To evolve a table, write a [migration](migrations.md) and apply it with
`db.migrate({...})`; then `db.verify` confirms the post-migration schema against
your models.

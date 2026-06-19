# Schema startup and drift

snekql has two complementary startup mechanisms: **startup schema management**
(create missing tables, verify the rest) and **migrations** (apply hand-authored
ordered changes). See [migrations.md](migrations.md) for the migration model.

When `Database.initialize(..., models=[...])` runs, snekql creates missing tables
and verifies existing tables and indexes against the shape generated from the
table models. Verification is *semantic*: each backend reads its own catalog
into a shared schema shape (SQLite via `PRAGMA`, MariaDB via
`INFORMATION_SCHEMA`) and compares that shape to the one the models expect, so a
table is recognized as matching whenever it is semantically equal — regardless
of cosmetic DDL differences such as identifier quoting, whitespace, type-keyword
case, or column and index ordering.

When you pass `migrations={...}`, migrations become the sole schema-creation
authority: snekql no longer auto-creates tables from `models`, but it still
verifies them afterward, so a model with no matching migration is reported as
drift. See [migrations.md](migrations.md).

## What happens at startup

```python
db = await Database.initialize(
    database=Path("app.db"),
    models=[User, AuditLog],
    schema_policy="strict",
)
```

snekql will:

1. Preserve the order of the `models` sequence.
2. Reject duplicate resolved table and index names.
3. Create missing tables and indexes.
4. Verify existing tables and exact index sets.
5. Skip verification for objects created during the same initialization pass.

## Drift detection strategy

Drift detection compares semantic shapes, not rendered DDL:

1. Generate the expected table shape (columns, indexes, foreign keys, and
   table-level storage options) for each model.
2. Read the live table shape from the selected backend's catalog.
3. Diff the two shapes. Columns and indexes match by name independent of
   declaration order; only the facts snekql controls are compared.
4. Report each divergence, naming the specific table, column, index, or foreign
   key, and treat any divergence as schema drift.

A table legitimately created or evolved by migrations is therefore recognized
as matching whenever it is semantically equal to the model, so cosmetic
differences do not produce false-positive drift. Genuine divergence — a model
column, index, or foreign key with no corresponding schema change — is reported
precisely.

Because generated SQLite tables are always `STRICT`, an existing SQLite
non-`STRICT` table is reported as a storage-option divergence; MariaDB likewise
requires the `InnoDB` engine. Extra, missing, renamed, or uniqueness-changed
indexes on managed tables are also schema drift. SQLite verifies foreign-key
constraints against the model; MariaDB foreign keys are created with the table
but not verified, because MariaDB auto-creates a backing index for each
constraint.

## Policies

`schema_policy="strict"` is the default. Drift raises
`SchemaVerificationError`. SQLite schema setup is transactional and rolls back
created tables on startup failure. MariaDB DDL may auto-commit, so failed MariaDB
startup can leave already-created schema objects in place; rerun startup after
cleaning up or applying an application-owned migration.

```python
await Database.initialize(
    database=Path("app.db"),
    models=[User],
    schema_policy="strict",
)
```

`schema_policy="warn"` logs drift and continues startup.

```python
await Database.initialize(
    database=Path("app.db"),
    models=[User],
    schema_policy="warn",
)
```

Use `warn` when adopting snekql in an environment where you want observability
before enforcing drift failures.

## What startup schema management does not do

On its own (without `migrations=...`), startup schema management does not:

- alter existing tables;
- generate migration files;
- preserve or transform data during schema changes.

To evolve an existing table, write a [migration](migrations.md) and pass it to
`Database.initialize(migrations={...})`; the models are then verified against the
post-migration schema under `strict`.

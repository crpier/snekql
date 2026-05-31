# Schema startup and drift

snekql v1 has startup schema management, not migrations.

When `Database.initialize(..., models=[...])` runs, snekql creates missing tables
and verifies existing tables and indexes against deterministic SQLite DDL
generated from the table models.

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

V1 keeps drift detection deliberately simple:

1. Generate expected `CREATE TABLE` and `CREATE INDEX` SQL for the model.
2. Read existing table and index SQL from SQLite metadata.
3. Normalize only table formatting controlled by snekql.
4. Compare generated SQL with stored SQL.
5. Treat mismatch as schema drift.

Because generated table DDL always includes `STRICT`, existing non-`STRICT`
tables are schema drift. Extra, missing, renamed, reordered, or uniqueness-
changed indexes on managed tables are also schema drift.

## Policies

`schema_policy="strict"` is the default. Drift raises
`SchemaVerificationError` and rolls back schema setup.

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

## What snekql does not do

snekql v1 does not:

- alter existing tables;
- generate migration files;
- compare semantic schema differences beyond deterministic DDL equality;
- preserve or transform data during schema changes.

If a table drifts, write and run an application-owned migration, then start the
runtime again under `strict`.

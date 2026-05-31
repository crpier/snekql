# Schema startup and drift

snekql v1 has startup schema management, not migrations.

When `Database.initialize(..., models=[...])` runs, snekql creates missing tables
and verifies existing tables against deterministic SQLite `STRICT` DDL generated
from the table models.

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
2. Reject duplicate resolved table names.
3. Create missing tables.
4. Verify existing tables.
5. Skip verification for tables created during the same initialization pass.

## Drift detection strategy

V1 keeps drift detection deliberately simple:

1. Generate expected `CREATE TABLE` SQL for the model.
2. Read existing table SQL from SQLite metadata.
3. Normalize only formatting controlled by snekql.
4. Compare the generated SQL with the stored SQL.
5. Treat mismatch as schema drift.

Because generated DDL always includes `STRICT`, existing non-`STRICT` tables are
schema drift.

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

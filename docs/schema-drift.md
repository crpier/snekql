# Schema startup and drift

snekql v1 has startup schema management, not migrations.

When `Database.initialize(..., logger=logger, models=[...])` runs, snekql creates missing tables
and verifies existing tables and indexes against backend metadata generated
from the table models. SQLite compares deterministic DDL stored by SQLite;
MariaDB compares normalized `INFORMATION_SCHEMA` table, column, and index
metadata.

## What happens at startup

```python
db = await Database.initialize(
    logger=logger,
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

1. Generate the expected backend table and index shape for the model.
2. Read existing table and index metadata from the selected backend.
3. Normalize only formatting or metadata details controlled by snekql.
4. Compare the generated shape with the stored backend metadata.
5. Treat mismatch as schema drift.

Because generated SQLite table DDL always includes `STRICT`, existing SQLite
non-`STRICT` tables are schema drift. MariaDB drift is detected from normalized
column and index metadata. Extra, missing, renamed, reordered, or uniqueness-
changed indexes on managed tables are also schema drift.

## Policies

`schema_policy="strict"` is the default. Drift raises
`SchemaVerificationError`. SQLite schema setup is transactional and rolls back
created tables on startup failure. MariaDB DDL may auto-commit, so failed MariaDB
startup can leave already-created schema objects in place; rerun startup after
cleaning up or applying an application-owned migration.

```python
await Database.initialize(
    logger=logger,
    database=Path("app.db"),
    models=[User],
    schema_policy="strict",
)
```

`schema_policy="warn"` logs drift and continues startup.

```python
await Database.initialize(
    logger=logger,
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

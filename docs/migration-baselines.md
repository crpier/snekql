# Reviewed baselines for existing databases

A reviewed baseline starts an application's first snekql Migration Declaration.
It does not record a fictitious execution of earlier migrations. Fresh databases
and existing databases execute the same initial SQL body through `migrate()`.
The existing database keeps its reviewed schema and business data; fresh replay
creates the intended schema.

The tested [baseline example](../examples/migration_baseline.py) implements this
workflow for a dedicated, one-table account database on SQLite and MariaDB.
It is application code to copy and adapt, not a new library method or a generic
schema-equivalence checker.

## Choose the right workflow

| Starting point | Action |
| --- | --- |
| Fresh database | Replay the complete canonical declaration with `migrate()`. |
| Existing schema, no snekql history, no already-deployed snekql chain | Review and execute a new initial baseline. |
| Valid snekql history | Keep the existing chain and apply its pending suffix. |
| Legacy snekql history | Use the separately reviewed `adopt_legacy=True` workflow. |
| Malformed history or partially committed MariaDB DDL | Stop and reconcile actual effects. Do not stamp or delete history. |

Even an empty snekql history table excludes this one-time adoption workflow.
`migration_status(...).history_present=False` says nothing about application
tables, data, or previous tools. Never replace an already-deployed canonical
chain with a new baseline to onboard another database.

Retired external migration-tool tables are not snekql history. Preserve their
records and explicitly review their ownership and retirement. The example
rejects every extra object; an application with intentionally unmanaged objects
needs an explicit reviewed inventory policy, not a wildcard exclusion.

## Review before recording history

1. Back up the database and test restoration. Record the database identity,
   engine version, application revision, and intended ownership scope.
2. Stop writers, background jobs, schema tooling, and deployers. Use a newly
   initialized Database exclusively for adoption, not an active application's
   pool. Keep the maintenance window open until all post-checks finish.
3. Confirm that snekql history is absent. Do not create an empty history table
   as preparation and do not use `adopt_legacy=True` for an untracked schema.
4. Inventory owned tables, indexes, constraints, views, triggers, generated
   expressions, defaults, collations, engine options, and other relevant catalog
   facts. Include routines and scheduled events where supported. Use credentials
   with sufficient metadata visibility; an invisible object is not an absent one.
5. Write the initial SQL as committed literals. Each existing object that SQL
   preserves must match the reviewed contract. `CREATE ... IF NOT EXISTS`
   silently accepts mismatched objects, so it is not a preflight check.
6. Run `verify()` for the facts Table Models represent. Separately check all
   relevant unsupported facts and data invariants. A successful `verify()` is
   not blanket approval, and `policy="warn"` does not authorize a mismatch.
7. Preserve review evidence independently of generated model output: catalog
   exports, explicit expected facts, data-check results, and human sign-off tied
   to the exact baseline SQL. Do not automatically replace expected snapshots
   with whatever the live database currently reports.
8. Test fresh replay, populated adoption, and rejection of mismatched schema and
   invalid data. Existing data may differ from fresh data, but both must satisfy
   the declared application invariants.
9. Execute the reviewed baseline with ordinary `migrate()`. Then run
   `verify_migrations()`, `verify()`, and application-specific post-checks before
   resuming traffic.

The preflight and migration are separate operations. snekql's migration lock
coordinates cooperating migration runners only; it does not keep application
writers or unrelated DDL out of the review window. The adoption procedure
requires external coordination rather than pretending those operations are
atomic together.

## What the example checks

The example owns `baseline_account(id, balance)` with a nonnegative-balance
CHECK. Its adoption functions require absent history and an already-present,
model-compatible table. They also check facts beyond model verification:

- SQLite compares the persistent object inventory and stored CREATE SQL against
  an independently reviewed literal. Extra tables, indexes, views, and triggers
  fail review. Only SQLite's reserved `sqlite_` objects are excluded.
- MariaDB compares `SHOW CREATE TABLE` against independently reviewed output and
  rejects extra tables, views, triggers, routines, and events in the database.
- Both scan balances for negative values. Having a CHECK in the catalog does
  not prove old rows satisfy it; constraint enforcement could previously have
  been disabled.

Catalog matching is deliberately conservative. Equivalent formatting or a new
MariaDB version's display format may fail review. Investigate and review the
change rather than normalizing away facts or accepting all output. This example
is not a claim of portable, complete schema equivalence. Adapt it for the actual
schema and server settings under review.

No adoption SQL executes when those preflight checks fail. Successful adoption
runs `CREATE TABLE IF NOT EXISTS` and records only `001_reviewed_baseline`.
It does not update or reseed balances. MariaDB may emit an expected
"table already exists" warning for that statement.

```python
from pathlib import Path

from examples.migration_baseline import adopt_sqlite
from snekql import sqlite

# Maintenance entry point, after backup and human review, not service startup.
async with await sqlite.Database.initialize(
    sqlite.Config(database=Path("existing.db"), pool_size=1)
) as db:
    result = await adopt_sqlite(db)
```

For MariaDB, use `adopt_mariadb()` with a newly initialized MariaDB Database.
These repository examples are not installed as library modules; copy the
reviewed application code into your deployment tooling.

Fresh databases use the same literal declaration without the adoption helper:

```python
from examples.migration_baseline import SQLITE_MIGRATIONS, SQLiteAccount

await db.migrate(SQLITE_MIGRATIONS)
await db.verify_migrations(SQLITE_MIGRATIONS)
await db.verify([SQLiteAccount])
```

Later releases append migrations to this chain. Do not change the baseline's
name, position, or body once recorded anywhere.

## Interrupted adoption

A preflight failure leaves migration history absent. Once `migrate()` begins,
normal backend guarantees apply. SQLite records a body atomically with its
history row. MariaDB can leave an empty history table or committed DDL after an
interruption. An interrupted commit can also have succeeded without the caller
receiving confirmation.

Reinspect history and the actual catalog/data before choosing a recovery step.
Do not repeatedly invoke the one-time adoption helper against present history,
remove history to make the helper run again, or stamp unexecuted migrations.
After renewed review, use the complete unchanged declaration with the normal
migration workflow when replay is known to be safe. Restore or repair explicitly
when it is not. Keep writers stopped until reconciliation and post-checks finish.

See [migration recovery](migration-recovery.md) for the reconciliation decision
table and a tested MariaDB pure-DDL recovery example.

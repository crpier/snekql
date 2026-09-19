# Expand, backfill, and contract

The [rolling migration example](../examples/rolling_migration.py) renames
`rollout_customer.name` to `display_name` without changing its meaning. It uses
literal migration chains for SQLite and MariaDB and an application-owned
checkpoint table for a resumable backfill. It does not add a library scheduler,
retry loop, generated migration, or down migration.

Expansion and bridge deployment can overlap compatible application versions.
The final contract in this example uses a maintenance cutover. It does not
promise zero downtime or preserve incompatible old writers during contraction.

## Deployment sequence

1. **Prepare compatible readiness checks.** Review the exact expanded migration
   suffix before allowing old replicas to accept it with compatible history
   verification. Do not approve the contract suffix for old code. Model
   verification is independent: adding a column can fail an old model's strict
   schema check even when history is approved. Update the readiness strategy
   deliberately; `policy="warn"` alone is not compatibility approval.
2. **Expand from one deploy job.** Apply `SQLITE_EXPANDED` or `MARIADB_EXPANDED`.
   It adds nullable `display_name`, creates the checkpoint table, and seeds its
   singleton row. Checkpoint seeding is a separate transactional DML migration,
   not DML bundled behind implicitly committing MariaDB DDL. Confirm complete
   expanded history and review the resulting schema.
3. **Roll out the bridge application.** Insert and update both columns to the
   same value in one transaction. While old-only writers remain, read `name`
   as the authority: an old writer can change it without refreshing an
   already-filled `display_name`. Switch to `COALESCE(display_name, name)` only
   after draining those writers and reconciling any mismatches they left.
4. **Drain every old-only writer.** Include background jobs, scripts, queues,
   old connections, and delayed work. Ensure the bridge deployment writes both
   columns before starting the backfill. If mixed deployment produced stale
   non-null targets, explicitly repair them from the authoritative old column
   under a reviewed procedure. The backfill intentionally will not overwrite
   those targets.
5. **Backfill in bounded transactions.** Call the relevant `backfill_*_batch()`
   until `done` is true, with pauses between committed batches. Monitor locks,
   latency, replication lag, and disk space. Retry policy belongs to the operator
   or job runner, not the migration engine.
6. **Stop and drain all writers and batch workers.** Back up before destructive
   contraction. Run `contract_sqlite()` or `contract_mariadb()` while traffic is
   stopped. These helpers require the expanded history and scan every row for
   null or disagreeing values before applying the contracted chain.
7. **Verify and start the new-only application.** Check complete contracted
   history, current models, and application-specific schema/data facts. Start
   code that reads and writes only `display_name`. Do not restart old or bridge
   writers after the old column is removed.

The bridge write is one SQL operation, for example on SQLite:

```python
async with db.transaction() as tx:
    await tx.execute(
        sqlite.raw(
            "UPDATE rollout_customer SET name=:name, display_name=:name WHERE id=:id",
            params={"name": new_name, "id": customer_id},
        )
    )
```

MariaDB uses `%(name)s` and `%(id)s` placeholders. Inserts must also supply both
columns. Concurrent writer/backfill tests verify that either lock order
preserves the bridge writer's current value.

## Durable progress

IDs must be positive and immutable; the example enforces positivity in SQL.
One checkpoint row stores the last scanned ID. Each batch:

- Locks the checkpoint before selecting the next ordered page.
- Reads at most the requested page size, capped at 1,000 rows.
- Copies the current old value only where the target is null.
- Advances the checkpoint even when a row was already filled by the bridge.
- Commits row updates and the checkpoint together before returning progress.

SQLite uses an immediate transaction to serialize writers. MariaDB locks the
checkpoint and page with `FOR UPDATE`; all participating tables must remain
InnoDB. Competing workers serialize on the checkpoint. Changing primary keys,
engines, triggers, or the copy rule requires a new review of the algorithm.
The simple schema has no inbound foreign keys, secondary indexes, or triggers;
the SQLite contract rebuild is not a general recipe for those objects.

```python
from anyio import sleep
from examples.rolling_migration import backfill_sqlite_batch

while True:
    progress = await backfill_sqlite_batch(db, batch_size=100)
    if progress.done:
        break
    await sleep(0.05)
```

Use `backfill_mariadb_batch` for MariaDB. These repository examples must be
copied into application deployment tooling; they are not installed library
modules. Pausing between batches releases transaction locks. A caller may stop
after any acknowledged batch and resume with a new Database instance.

On failure or cancellation before commit, neither copied values nor checkpoint
advancement survive. If the commit reply is lost, do not infer rollback.
Reconnect and inspect durable progress. This particular operation is
reconcilable because data and checkpoint commit together and it has no external
side effects. Tests simulate a lost response after the server commits and
resume from the recorded checkpoint. Do not generalize that behavior into
blind retries for arbitrary application transactions.

`done` means the page scan reached its currently visible end. It is not approval
to contract. An old-only writer could insert a null target behind the checkpoint
or modify an already-scanned source. The final data scan catches these cases;
it compares MariaDB values byte-exactly, including trailing spaces. Stop and
repair mismatches rather than repeatedly resetting the checkpoint or silently
overwriting populated target values.

## Contract and failure handling

SQLite contracts through one atomic copy/drop/rename body, then removes the
checkpoint table in that same body. MariaDB modifies the new column to NOT NULL,
drops the old column, and removes the checkpoint table using DDL with implicit
commits. MariaDB contraction can be partially applied without its history row.
Follow the [recovery procedure](migration-recovery.md); do not blindly rerun the
contract helper or treat this destructive body as idempotent.

The preflight scan and migration are separate operations. Only the external
maintenance window prevents writers from changing data between them. Ordinary
`migrate()` does not enforce application-specific backfill gates; deployment
must use the reviewed contract procedure rather than directly applying its
literal declaration to a populated database.

Fresh databases replay the complete contracted declaration normally. Their
empty tables need no data backfill. This is the same canonical SQL history,
not a separate model-generated bootstrap path. Before contract, rolling back
application code may be possible while the old storage is intact. After
contract, recovery needs an explicit forward fix or a reviewed restore, not an
automatically generated down migration.

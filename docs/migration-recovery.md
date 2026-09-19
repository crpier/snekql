# Recovering an interrupted migration

A pending history row is not proof that its SQL never ran. This matters most on
MariaDB: DDL commits implicitly, including preceding DML in the transaction.
The schema or data can change even when snekql never records the migration.
A lost commit response can also leave both the body and history committed.

The tested [MariaDB recovery example](../examples/migration_recovery.py) handles
one narrow case: adding a nullable column with a previously reviewed,
idempotent `ALTER TABLE ... ADD COLUMN IF NOT EXISTS`. It is an operator-invoked
procedure, not automatic migration retry or a generic repair interface.

## Reconcile before retrying

1. Stop deployers, writers, backfills, and other schema tooling. Preserve the
   failing application's declaration and database identity. Back up the current
   database before attempting repair; retain the pre-deploy backup too.
2. Reconnect with a newly initialized Database. Call
   `migration_status(COMPLETE_DECLARATION)`. Do not change applied names, order,
   checksums, or history rows to make validation pass.
3. Inspect actual effects independently of history. Review catalog definitions,
   constraints, indexes, triggers, data transformations, and external effects
   relevant to the failed body. Read-only status does not perform this review.
4. Classify the observed state and choose a recovery action from the table below.
   Keep traffic stopped while inspecting and acting; the migration advisory lock
   does not protect this whole maintenance procedure from unrelated writers.
5. After recovery, verify the complete history, verify representable schema
   facts against the current models, and run application-specific catalog/data
   checks. Resume traffic only after all checks pass.

| Recorded history and observed effects | Action |
| --- | --- |
| Expected row exists with the exact checksum | Do not repeat the body. Normal `migrate()` skips it; verify its effects before proceeding. |
| Row missing, proven no effects | Rerun only after reviewing the complete body's replay conditions. |
| Row missing, effects match reviewed replay-safe states | Rerun the same unchanged declaration through `migrate()` after review. |
| Row missing, partial or non-idempotent effects | Do not blindly rerun. Restore or make an explicit reviewed repair, then reconcile again. |
| History malformed or divergent | Stop. Restore or investigate authoritative history and release artifacts; do not use baseline adoption to bypass it. |

An error saying history could not be recorded does not distinguish a rejected
write from a lost acknowledgement after commit. Reconnecting and inspecting
history resolves that ambiguity when the database is available.

## Why `IF NOT EXISTS` is insufficient

It prevents some duplicate-object errors; it does not prove the object's type,
constraints, collation, or other facts match the intended result. The example
compares `SHOW CREATE TABLE` against independently reviewed before/after
snapshots before allowing replay. It rejects a preexisting `note BIGINT` column
where the declaration requires nullable text. An already-recorded migration
must match the after-state, not merely either state.

The accepted snapshots are deliberately version- and formatting-sensitive. A
new server representation requires review, not automatic replacement of the
expected snapshot. The example covers a pure column-addition statement only;
do not extend its approval to data migrations or arbitrary SQL scripts.

This mixed body is unsafe to replay merely because its DDL is idempotent:

```sql
UPDATE accounts SET balance = balance + 10;
ALTER TABLE accounts ADD COLUMN IF NOT EXISTS note TEXT;
```

The `ALTER TABLE` can commit the increment before history insertion fails.
Blindly rerunning can increment balances twice. Tests reproduce that behavior
against a real MariaDB server. Keep transactional DML separate from implicitly
committing DDL, and use application-specific idempotency or reconciliation for
non-idempotent effects. Do not assume every statement within one MariaDB body
shares a rollback boundary.

## Repair and restore boundaries

Prefer restoring the affected database to a verified pre-migration state when
there is no defensible replay or repair procedure. Restoration can discard
later writes, so it requires an explicit data-loss decision and reconciliation
of any external effects.

A forward repair must document exactly which persistent effects already
occurred and which are missing. It is not permission to insert a history row
manually. If the unchanged pending body cannot safely execute after repair,
stop and design an application-specific migration strategy. No generic stamp
or generated down migration is provided.

SQLite migration bodies and their history rows are atomic, but cancellation
around commit can still arrive after success. Inspect history before deciding
whether a cancelled unit applied. External side effects in user-defined SQL
functions are not made transactional by either backend.

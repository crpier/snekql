# Recorded migration recovery

This guide is only for **`snekql.experimental.migrations`** packages and their
original prepared plans. For `db.migrate(MIGRATIONS)`, use
[raw-SQL migration recovery](migration-recovery.md). The families do not share
history, locks, recovery authority, or an automatic conversion path; use separate
deployment targets.

Start with the [recorded workflow and finite support](recorded-migrations.md).
Neither a returned timeout nor a lost connection tells you whether remote work
stopped, rolled back, committed, or reached its durable execution marker.

## Before doing anything else

1. Stop competing schema deployers and incompatible affected-data writers. Keep
   authorization/metadata visibility stable. Preserve the package, **original
   prepared plan**, logs, ledger, and independent observations before intervention.
2. Retain and close/join the old connection lifetime as described below. Do not
   issue rollback, cursor cleanup, session-policy SQL, or retries on an unsafe
   interrupted connection. Local disposal does not certify remote quiescence.
3. Open a **fresh** migration connection using the same target configuration and
   endpoint identity. Do not switch endpoints to reconstruct an original plan.
   Direct independent database observation is useful, but does not authorize replay.
4. Load the saved original with `Prepared.load(...)`. A new `prepare()` call is
   not a replacement. Missing or corrupted original evidence requires operator
   investigation; matching structure alone cannot recreate an execution receipt.

Use `target.status()` on a fresh connection to inspect durable progress. An
`uncertain` phase describes an incomplete durable history, not permission to
retry. `acknowledged_steps` means ledger progress, not that the original caller
received a success packet. A final MariaDB completion marker may have committed
before a later COMMIT acknowledgement was lost; a fresh apply of the same
original can truthfully return `"already_applied"`. Do not infer that outcome
merely from a timeout or completed-looking schema.

## SQLite interruption

SQLite execution is transactional within the qualified declaration/environment.
After independent writer exclusion and a fresh connection, inspect durable
history and data. If execution did not commit, the **same saved original** can
be applied once when the target still satisfies it. A completed receipt yields
`"already_applied"`; a mismatch refuses rather than silently re-preparing.

`inspect_recovery`, `resume`, and structural reconciliation are MariaDB-specific;
do not use them to invent SQLite partial acknowledgements. Actual DELETE/WAL
client-death qualification is not host/power/volume-loss qualification. WAL may
retain uncommitted bytes; rollback is not deletion or secure erasure. A pinned
reader may continue seeing its older snapshot after a fresh writer commits.

## MariaDB: classify before recovery

```python
from snekql.experimental import migrations as m

# original came from the saved Prepared envelope, not from prepare() again.
lifetime = m.connect(config)
async with lifetime as target:
    recovery = await target.inspect_recovery(
        original,
        schema_writers_excluded=True,
    )
    print(recovery.disposition, recovery.explanation)
    print(recovery.acknowledged_steps)
await lifetime.wait_closed()
```

This is an inspection, not an automatic retry policy. Keep the owning loop and
lifetime supervised on errors; see the cleanup section below. The disposition
is bounded by the current catalog, durable markers, declaration/environment,
transactional obstacles, and rendering profile:

| Disposition | Meaning and next action |
| --- | --- |
| `retry_remaining` | The catalog matches the last durable acknowledgement and remaining work has a proved recovery route. Review the classification, then explicitly call `target.resume(recovery, schema_writers_excluded=True)`. |
| `finish` | All steps are acknowledged but completion needs recording. Review, then explicitly call `resume(...)`. This is not a request to replay the data work. |
| `reconcile_structural` | Exactly the next planned structural contraction is observed without its acknowledgement. Review the original and before/observed catalog/profile evidence; explicitly accept only that proved structural outcome. |
| `ambiguous` | No automatic recovery is authorized. Investigate and preserve evidence; do not replay, stamp, edit ledger rows, or claim completion. |

For a reviewed structural reconciliation, on a fresh admitted target:

```python
accepted = await target.reconcile(
    recovery,
    reason="Reviewed the original contraction and independent catalog evidence",
    schema_writers_excluded=True,
)
# accepted is a fresh Recovery classification, not a migration receipt.
# Re-evaluate accepted.disposition before an explicit target.resume(...).
```

Use a meaningful review reason, not an unattended default. Reconciliation records
acceptance of proved structure; it never asserts that unacknowledged data work
ran, rewrites prior receipts, or authorizes an uncertain UPDATE to be replayed.
The final `is_admin` DROP/required-`role` transition is a representative selected
case, not a generic DDL recovery theorem. Triggers, stored routines, non-InnoDB
tables, changed policy/rendering, or an unmatched catalog can make recovery
ambiguous or refuse it outright.

Do not call `apply(original)` blindly on an incomplete MariaDB execution. Do not
replace its plan hash, increment acknowledged counts, delete the ledger, or
accept schema equality as a receipt. There is no automatic repair/stamping path.
Fresh recovery operations may legitimately use transactions; the prohibition is
on cleanup SQL queued on the **interrupted unsafe connection**, not on every
subsequent session.

## Cleanup and primary errors

The owner exists before opening:

```python
lifetime = m.connect(config)  # inert; retain this outside the deployment task
```

Pass it to your supervised deployment task rather than creating it inside a
helper whose failed entry loses the owner. Within that task, preserve the primary
error if an exit/join attempt also fails:

```python
async def apply_reviewed(lifetime: m.Connection, original: m.Prepared) -> str:
    try:
        async with lifetime as target:
            result = await target.apply(original)
    except BaseException as primary:
        try:
            await lifetime.wait_closed()
        except BaseException as cleanup_error:
            primary.add_note(f"Migration cleanup also failed: {cleanup_error!r}")
        raise
    else:
        await lifetime.wait_closed()
        return result
```

The supervisor still owns `lifetime` after this function raises. If a join
expires or is cancelled, keep the **same owning loop** live and arrange a later
explicit `await lifetime.wait_closed()` when appropriate. Each call has a fresh
operation-timeout budget and can independently fail. A cancelled/expired waiter
does not cancel retained cleanup or another waiter. Report primary outcome,
cleanup outcome, and remaining uncertainty separately.

This function is not a complete shutdown supervisor. In particular, wrapping it
in `asyncio.run(...)` and immediately stopping the loop after failed cleanup does
not guarantee a drain. There is no global join, automatic retry, all-task-cancel
guarantee, general failed-physical-close recovery, or remote native quiescence
certificate. A successful local join neither proves server rollback/lock release
nor establishes application readiness.

## Resume service only with separate evidence

After explicit completion or an already-applied result, check current application
models with the ordinary backend's `verify(...)`, exercise current typed
reads/writes, and check application-specific data invariants and codecs. Preserve
unmanaged objects and earlier receipts; compare earlier receipt values to this
target's own pre-transition evidence, not another target's hashes.

Neither structural reconciliation, receipt equality, a released advisory lock,
nor `wait_closed()` proves application readiness. Do not relabel timestamp/data
encodings or claim a stronger historical guarantee than the original execution
provided.

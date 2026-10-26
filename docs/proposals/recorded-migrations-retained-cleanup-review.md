# Recorded migrations: retained cleanup and live-loop policy (#477)

Status: **bounded G3 lifecycle implementation/candidate-policy checkpoint**, not global
shutdown/failed-close qualification, G4 completion or G5/release approval. Follows
[real COMMIT outcomes](recorded-migrations-commit-outcomes-review.md).

## Real public gap and vertical RED/GREEN

SQLite interrupted I/O already closed logical admission and retained an independently owned
physical close. But context exit returned immediately whenever Target was logically closed,
without observing that known close result. A caller catching its operation timeout could exit
connect SUCCESSFULLY while the actual worker still slept in SQLite's busy handler. Successful
logical exit was not an adequate lifetime result for its known physical cleanup.

Real DELETE writer lock, original role003 waiting in BEGIN, configured I/O0.15 vs busy3:
caller catches migration-execute timeout, independent Linux wchan still observes SAME busy
worker, then caller ends context. Clean RED: `context exit skipped retained physical cleanup`.
No fabricated state/history, mocked migration driver, GC/private production flag assertions,
new callbacks or late data-replay claims. This is an experimental lifetime-policy gap, not
corruption/false completion/server defect or proof that old exit promised physical quiescence.

Minimal implementation: one private `_join_close(task)` shares existing normal-close shield+
fresh operation-timeout behavior. Context exit ALSO joins its known retained SQLite close,
including after active guard owner discards while exit waits. No rollback/cursor/policy SQL
is queued on the unsafe connection. Native socket closure and abandoned physical opening
ownership remain separate. No new method/Config knob/facade/generic runtime/task supervisor.

## Precise candidate lifetime contract

- Public operation failure invalidates unsafe Target immediately; its close task owns disposal.
  Returning from that operation is NOT physical close/worker stop/rollback evidence.
- Context exit stops new/queued admission, drains active owner under fresh acquire_timeout,
  then observes normal OR ALREADY-RETAINED close under fresh operation_timeout. Caller body
  pauses/previous driver I/O do not consume this new close budget. No cumulative context timer.
- A normal SUCCESSFUL Target lifetime exit observes its known physical-close task's SUCCESS.
  It is not a global thread/FD/process barrier, drain of other targets, or observation of an
  abandoned opening that never yielded a Target. Even after close returns, worker-TID exit
  is an independently observed OS fact, not an instantaneous scheduling guarantee.
- Close-budget expiry surfaces existing DatabaseOperationTimeoutError/`migration close` when
  no primary body error is pending. Failed/cancelled join preserves retained task ownership;
  expiry is NOT close success, physical interruption, rollback or authorization for reuse.
- Primary body I/O error/cancellation survives secondary close failure (existing connect failure
  precedence/logging). Direct caller-task cancellation during the close wait remains primary; shield prevents it from
  cancelling the retained physical owner. Structured caller cancellation still permits bounded
  shielded cleanup before propagating/catching its original cancellation.
- Actual close failures are observed/logged and, when joined, propagated without masking a
  primary failure. NO retry/automatic repair/force-success; a failed close is not disposal proof.
  This unit does not inject/qualify every physical-close failure or every global cancellation.

## Public original-role journey and finite cases

`test_migration_retained_cleanup.py`: literal001/002/003, visible typed flags1/2, saved ORIGINAL003
BEFORE apply, ALL own earlier001/002 columns/bytes retained. Real independent writer chooses
DELETE/BEGIN IMMEDIATE. OS records actual worker and busy wait; Target's operation deadline
returns while physical worker lives. Caller chooses context/error handling explicitly:

1. Finish: context exit stays pending while writer holds lock. Release OWN writer within fresh
   close budget; SAME known close completes, independently observe worker-TID disappearance,
   NULL-role rollback/no003/earlier own receipts intact. No late admitted package work.
2. Deadline: caller handled operation failure; exit consumes NEW close0.15 and raises migration
   close timeout rather than succeeds. Actual SAME busy worker STILL exists after caller return.
3. Primary: caller reraises IDENTICAL original migration-execute timeout; secondary close timeout
   logs/does not replace it. Same independently observed continuing busy worker.
4. Task: cancel context task while it joins; CancelledError survives, actual close retained.
5. Scope: structured caller cancellation in body remains primary despite shielded close-budget
   expiry. Outer scope catches cancellation; physical worker still busy, not force-closed.

After EACH failed/expired exit the caller keeps loop alive, releases OWN blocker, independently
observes worker disappearance before trusting fresh state. SQLite atomic no003 plus original
catalog supports SAME original explicit fresh apply, then already_applied/sorted complete status/
ordinary typed1admin2user3user. No native-recovery/portable-identity/host-loss inference. Existing
[opening journey](recorded-migrations-sqlite-opening-review.md) separately observes retained
late opening worker+FD disappearance before fresh role deployment/normal process exit.

## Explicit G3 live-loop/shutdown decision

**Candidate support requires a live default asyncio loop until retained physical work is
finished or the operator has deliberately chosen a separate process-level stop/recovery path.**
The library owns individual opening/close work; caller owns its tasks, blocker/writer exclusion,
loop/process lifetime and original evidence. Normal Target exit now observes its known close
where possible, but no successful global-quiescence certificate or public process supervisor
is introduced. Do NOT cancel all loop tasks/stop the loop and assume shielded cleanup survived.

Explicitly OUTSIDE first-promotion qualification: global all-tasks cancellation while SQLite
opening/close remains pending, event-loop close before physical work settles, failed-close
recovery, guaranteed library cleanup under abrupt interpreter/host termination, unavailable
OS/filesystem waits and universal cleanup after SIGKILL. Shielding/retention is not immortality, cross-process backup or a force
stop. Raw abandoned opening never yielded Target: no Target exit can join it; caller must keep
loop alive for its existing retained owner and arrange separate lifetime supervision. No hidden
promise that asyncio.run can immediately terminate safely after every opening/I/O failure.

These restrictions are deliberate candidate support/operational preconditions, NOT silently
implemented global shutdown. G5 must review the ergonomics/adequacy of this finite interface
and may reject promotion or choose separately designed lifecycle access; no speculative public
join/repair framework is added here. Finite qualification does not excuse a physical-close
failure or unknown outcome: remain stopped/uncertain and observe using original evidence.

Together with owned opening/admission/coordination/deadlines/session/file policy/metadata,
context ownership and COMMIT decisions, this records the remaining G3 ENGINEERING POLICY within
explicit limits. It does not approve G3 as a release contract or qualify excluded shutdowns.
G4 maintained matrix/WAL active death/native DDL loss, G5 interfaces/ADR0023/coexistence/release
approval remain. Consumer guides deferred; no artifact/epoch/layout/adoption/dependency expansion,
merge/tag/publication, historical receipt upgrade or changed released runtime policy.

## Completed final-source local validation

- **948 normal +948 forced-lazy experimental**, **1,784 fast**, **150 focused normal +150
  forced-lazy**, all exit0/zero failures/errors/fixture/session teardown failures. Separate
  actual10.10.7 negative version-floor runs: **1+1**, not positive maintained-version evidence.
  Native normal/lazy suites ran sequentially with distinct external disk TMPDIRs and
  context-aware warnings. No Actions checks requested, polled, awaited or claimed.
- **Ten completed final-source operator processes**, five cases in normal/forced-lazy, plus
  **five actual archived6d2fb38 processes** using verified archive module/target hashes and SAME
  final observer. Archive context returns immediately while SAME busy worker lives; even task
  cancellation arrives after its context has already returned. Fixed close timeout/primary/
  scope cases spend about0.1506–0.1511s in the fresh close stage; direct task cancellation is
  observed after the initial30ms probe. Finish completes about0.078s after its caller releases
  the blocker following that probe. Finite measurements, not scheduling guarantees.
- Every process independently observes own earlier receipts/NULL roles unchanged, worker/FD
  disappearance BEFORE fresh ORIGINAL application, sorted complete/current typed use and
  orderly asyncio.run return with no ResourceWarning/loop-closed/ignored-exception stderr.
  Caller keeps loop alive; these processes DO NOT certify abrupt/global-cancel shutdown.
- Whole-tree ty/ruff/format(**681**)/diff pass. **565** Python/program hashes unchanged throughout
  final suites/traces; **69** historical JSON artifacts unchanged against6d2fb38. **112** local
  links across SIX distinct changed Markdown files pass. Only production change is Target's
  known-close join; no other production/module/dependency/layout/package bytes changed.
- Evidence `.snektest/477-retained-cleanup/` and matching external-cache scripts include originals,
  trace state/receipts/results, archive/source provenance, completed summaries and empty actual
  owned-server audit. Initial observer's `none` versus real default `normal` lazy-mode label was
  corrected BEFORE it opened a database; excluded under `before-observer-lazy-label/`, not a
  runtime failure. Earlier style/noqa setup changes precede the stable final-source runs.

Local Linux/default asyncio/GIL CPython3.15.0/SQLite3.53.1/aiosqlite0.22.1 evidence; native existing
regressions use local13.0.2. Not the maintained-version/filesystem matrix, induced failed physical
close, unavailable-loop/global-cancel/host-death support, WAL process death, native DDL lost ACK,
all tests/full-suite/CI or release approval. Historical evidence and query-mapping independence
remain unchanged.

## Actual WAL process-death follow-through

The [WAL interruption checkpoint](recorded-migrations-wal-interruption-review.md) now exercises
real uncommitted role UPDATE-trigger spill/NORMAL-FULL, validated physical WAL frames, actual
client SIGKILL, independent rollback/no003 and fresh SAME original completion/current app.
This qualifies a selected database outcome after client death, NOT library-managed cleanup or
global graceful shutdown under abrupt termination; those G3 exclusions remain. Pinned WAL readers keep their old snapshot without blocking the fresh writer. Production code
unchanged; no fabricated runtime RED/fix or power-loss inference. G4 maintained environment
matrix/native DDL lost ACK and G5 interface/lifecycle/ADR/coexistence/release approval remain.

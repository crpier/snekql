# Recorded migrations: checked-out driver deadlines (#477)

Status: experimental, bounded G3 follow-through, not production/merge approval. Follows the
[defined execution interpretation](recorded-migrations-execution-epoch-review.md),
[original evidence](recorded-migrations-prepared-evidence-review.md) and
[supported-scope proposal](recorded-migrations-supported-scope.md). No new operation, parser,
compiler epoch, wire format, ledger layout, adoption authority or consumer guide.

## What is implemented

The dedicated target now uses Config.operation_timeout for a fresh caller-side deadline around
EACH checked-out driver interaction: cursor creation, execute, fetch, cursor cleanup, transaction
begin/commit/rollback, and normal SQLite context close. Statement-based coordination and policy
queries pass through the same guarded I/O. Time in application code between operations and pure
package validation/compilation is not charged to a whole-context/package wall-clock deadline.
No new public timeout option, runtime facade or database abstraction is added.

Expiry raises the existing DatabaseOperationTimeoutError with operation/timeout evidence.
Timeout or cancellation immediately invalidates the target, including read-only inspection.
Native sockets close; SQLite requests interrupt and owns a separate queued physical close task,
with its result observed even after the caller stops waiting. Closed admission is NOT evidence
of physical close. SQLite's busy/worker operation can finish later; context cleanup must not
queue rollback, cursor close or policy-restoration SQL behind an unsafe pending operation.
Normal close waits only within its own budget; an unsafe detached close is not rejoined behind
the expired operation's deadline and is never made reusable. Cleanup failure during an existing
failure is logged without replacing that primary failure. Known-safe rollback/policy cleanup
uses bounded I/O; the dedicated connection is discarded if that cleanup becomes uncertain.

These are checked-out I/O/connection-safety changes, not complete Config/runtime integration.
The [per-operation deadline ADR](../adr/0017-per-operation-deadlines-fail-closed.md) remains the
reference, but this checkpoint does not declare its entire migration contract discharged.

## Public-seam TDD and actual observations

Tests live in `tests/experimental/test_migration_io_deadlines.py`. Ordinary logical models,
committed historical role packages and independent actual database/OS observations are used;
no hand-built declaration states, fabricated receipts, mocked steps or private production faults.

### Blocked SQLite BEGIN

A real independent writer holds BEGIN IMMEDIATE. Target apply must expire at its configured
operation deadline, not wait for the longer SQLite busy/acquisition setting. The old code's RED
is **configured operation deadline ignored**. The watchdog merely detects that missing deadline;
it does not cancel the operation or prove rollback. Fixture finally releases the lock/joins work.

After implementation, the expired target refuses reuse, fresh inspection sees no receipt, and
release cannot resume the stopped coroutine's package work. Tests then independently observe
actual Linux database descriptors disappearing and a fresh writer-lock acquisition before
explicit fresh prepare/apply. Repeated terminal apply is already_applied; current typed queries
work. This physical observation is not a private task flag or an outer-timeout inference.

### Reader-blocked SQLite COMMIT: timeout is NOT rollback

A fresh file is observed in **DELETE mode**. An independent read transaction pins its old
snapshot while the target performs schema/history work and waits at COMMIT. The first I/O
implementation still missed this direct control call: second RED is **configured COMMIT deadline
ignored**. Begin/commit/rollback calls now use guarded I/O too.

The corrected test requires a migration commit deadline error, refuses reuse, preserves original
plan bytes, and proves the existing reader still sees only its old external directory table.
After reader release AND independently observed physical disposal, a fresh target determines
what happened. It may see atomic complete schema/receipt or no applied package. Only that fresh
evidence chooses already_applied versus explicit fresh preparation/application. No branch is
selected from the timeout alone, and the library does not automatically replay uncertain work.

The separate completed trace under `.snektest/477-io-deadlines/final-trace/sqlite-commit/` actually
observed the sharp case: **commit deadline at about0.155 seconds, then a COMPLETE receipt and
already_applied on fresh inspection**. The reader remained pinned until after the deadline.
The package COMMITTED after its awaiter reported timeout. Descriptor disposal, original bytes
and subsequent current typed use were observed. This is a real client-deadline/late-COMMIT case,
not a server/process death, WAL qualification or a claim that every timeout behaves this way.

### Native partially modified role backfill

The SAME committed001 accounts/002 nullable role/003 frozen typed backfill+contraction packages
from the process-interruption journey are deployed; authoring output is not regenerated. Visible
ordinary initial/expanded/current mappings seed and observe real typed application values.

Hold row2 with a separate InnoDB transaction. Independently observe the actual first UPDATE in
LOCK WAIT with **trx_rows_modified>=1** (row1 has already changed), then let its configured driver
deadline expire instead of killing/injecting a migration step. The target becomes unusable.
Release the blocker; independently wait for the interrupted server connection to disappear.
Typed observations prove both role values rolled back to NULL while flags remain.

Durable003 progress is STILL uncertain/acknowledged0. Ordinary preparation refuses blind retry.
A fresh connection loads the unchanged ORIGINAL versioned plan, inspects retry_remaining/0,
explicitly resumes, and current typed queries read1 admin/2 user. The completed standalone trace
under `final-trace/native/` additionally compares all earlier receipt columns/values before/after.
Original plan bytes are unchanged. Socket disposal did NOT erase uncertainty or invent completion.
No native DDL/COMMIT acknowledgement-loss or server-restart window is newly claimed here.

### Cancellation and per-I/O budgets

Task and AnyIO-scope cancellation of SQLite inspection under an actual exclusive schema lock
remain cancellation, invalidate the target, and retain physical cleanup ownership. Fresh inspection
works after independent descriptor disposal. Existing real native cancellation/reconciliation/
inspection regressions continue at the same public seams. A caller pause longer than the driver
budget between prepare/apply/status does not expire the context: each interaction gets a fresh
budget, not one wall-clock migration deadline.

Cleanup review also found two validation errors that said `transaction rolled back` BEFORE
rollback acknowledgement. With bounded cleanup that is not necessarily known. A public preserving
role-rebuild case with an independently created orphan in an unowned child table exercises the
FK refusal; its diagnostic RED is **premature cleanup claim**. Both FK and copied-value validation
errors now state their observed refusal and **completion not recorded**, not a physical rollback
claim. Fresh status and typed old-column reads establish actual retained state. This diagnostic
regression does NOT claim an actual failed/timed-out rollback was induced; none was injected.

Static signatures/Param names and lint/format/extraction corrections during authoring are fixture/
audit corrections, not extra runtime defects. Only completed reports/exits support validation counts.

## Remaining G3 and qualification work

- The subsequent [native-opening checkpoint](recorded-migrations-native-opening-review.md)
  adds a native acquisition budget, partial ownership and shared mandatory TLS. SQLite opening/
  partial-open ownership and local guard/coordination wait semantics still need an explicit
  contract. Acquire_timeout is not redefined as a universal physical-stop guarantee.
- SQLite journal/durability policy and native session/config/admission/visibility policy are not
  completed merely by accepting the shared Config. This change does not switch migration targets
  to WAL or claim all ordinary runtime settings are honored.
- Public known-versus-unknown commit-outcome reporting around post-commit cleanup, shutdown/
  detached physical-cleanup expectations and further real failure windows need deliberate review.
  A durable complete receipt is not rewritten to rollback/uncertain after a cleanup failure;
  absence of an acknowledgement is not retroactively certified from a matching endpoint.
- Deadlines are cooperative caller-await budgets, not CPU/memory/total-work limits or proof that
  a SQLite worker/native server statement stopped physically at the deadline. Applications must
  not treat an expired awaiter as quiescence or authorize automatic replay from it.
- Finite maintained-version qualification, actual WAL active death, selected native receipt-loss
  window, historical-source ergonomics, remaining cross-version evidence policy and final
  interface/ADR/coexistence/release approval remain. Original sensitive evidence still needs
  caller-owned secure atomic/durable storage and the database ledger; these tests do not prove
  filesystem/host-loss durability.

Query mapping/ownership remain independent; strict SQLite adoption and preservation boundaries,
all catalog/construction/recovery gates, package/Prepared references and execution epoch one stay
unchanged. Prototype remains incomplete/draft; no merge/tag/publication is authorized.

## Completed local validation

- **883 normal +883 forced-lazy experimental**, **1,784 fast**, **10 focused normal +10
  forced-lazy**, all exit0 with zero failures/errors/fixture/session teardown failures. Focused
  runs include seven new cases and three existing real native cancellation/reconciliation/
  inspection cases. Normal/lazy native suites were sequential with distinct external TMPDIRs
  and context-aware warnings. Final production/test source hashes stayed unchanged.
- Whole-tree ty/ruff/format/diff pass; all **68** previous package/Prepared JSON references remain
  byte-identical. Actual final-source SQLite/native traces retain original plan files, observed
  deadlines, fresh outcomes/current typed rows and full earlier native receipt equality.
- Before the diagnostic review, a separate completed882/882 run passed; that earlier source
  checkpoint is retained separately and is NOT substituted for final883/883 validation. Initial
  plain-assert diagnostic RED was made descriptive; signature/lint/Param corrections are not
  additional runtime-defect evidence. No private execution fault or rollback failure was injected.

Local environment remains Linux/default asyncio/GIL CPython3.15.0, SQLite3.53.1, MariaDB13.0.2,
Pydantic2.14.0, aiosqlite0.22.1, aiomysql0.3.2/PyMySQL1.2.0. These completed suites/traces do NOT
establish a local full-suite, maintained-version matrix, WAL crash/native lost-ack qualification
or exact-head CI success. Pending/unregistered checks are not awaited or counted as success.

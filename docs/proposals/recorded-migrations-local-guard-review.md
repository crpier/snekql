# Recorded migrations: local target-guard acquisition (#477)

Status: experimental, bounded G3 follow-through, not production/merge approval. Follows
[SQLite physical opening](recorded-migrations-sqlite-opening-review.md),
[native opening](recorded-migrations-native-opening-review.md) and the
[supported-scope proposal](recorded-migrations-supported-scope.md). Server coordination-lock
acquisition, session/durability and remaining outcome/shutdown policy are still incomplete.

## Local waiting is not checked-out driver I/O

Each public target operation now gets a fresh Config.acquire_timeout budget for waiting for
that target's local guard. Expiry raises the existing PoolTimeoutError with the phase-specific
message **timed out acquiring migration target guard**. Status, prepare, apply, recovery
inspection, reconciliation and resume share the same small private admission context. Existing
argument/refusal checks remain; this adds no public option, facade, scheduler or lock registry.

The acquisition scope covers ONLY awaiting the local guard, ending before the admitted body
runs. It is not a timer around a complete public operation, package or target context. Once
admitted, the operation retains the existing fresh per-driver-I/O operation_timeout budgets.
Physical opening has its own acquisition scope; this is not one cumulative deadline combining
opening, local waiting, server coordination and application time.

A caller whose guard wait expires or is cancelled has not touched the driver. It MUST NOT
invalidate the connection, queue cursor/rollback/policy SQL, release another task's guard or
interrupt the operation currently using that connection. Only a successful guard acquisition
owns its matching finally-release. Task/scope cancellation while queued remains caller
cancellation, not an I/O timeout or an uncertain migration outcome manufactured by the waiter.
Cancellation after actual admission remains subject to the existing I/O/disposal policy.

This implements local admission, not a new fairness/priority guarantee. Participating operators'
server advisory locks/SQLite writer transactions remain separate; the guard neither fences
external schema/data writers nor establishes application readiness. Caller-owned task/context
lifetimes and shutdown policy remain necessary.

## Real public-seam TDD

`tests/experimental/test_migration_local_guard.py` contains the visible consumer lifecycle.
It loads the SAME committed native001 accounts/002 nullable role/003 typed backfill+contraction
packages, seeds ordinary typed initial rows and retains ORIGINAL versioned Prepared bytes.
The initial/current application declarations are the real mappings in the preceding I/O
workflow tests, not hand-built recorded states or patched model snapshots.

An independently owned InnoDB transaction locks row2. The actual target starts apply003.
Independent native observations first establish its UPDATE in LOCK WAIT with at least one row
already modified. This is a real active owner, not a fabricated held Python lock or mocked step.
Only then does a second task call the same target's public status interface.

Before implementation, that caller remains queued past acquire_timeout: the retained RED is
**local migration guard acquisition deadline ignored**. The watchdog detects missing library
behavior; its timeout is not the guard deadline action and does not cancel the active owner.
Fixture finally releases its own blocker and joins only its own tasks, including on a RED.

The corrected interface expires the queued caller at its acquisition budget, not the longer
operation budget, while the active owner remains pending. Independent observation then proves
the SAME server connection STILL in LOCK WAIT with a modified row. The waiter did not close,
roll back, release or otherwise disturb that owner's wire/session/transaction state.

Five cases exercise queued status, prepare and apply expiry plus task and caller-scope
cancellation of queued status. Cancellation cases act before the guard deadline; task
CancelledError survives and the caller's own scope catches its scope cancellation. No private
production-helper assertions, injected faults, fake Recovery objects or fabricated receipts are
used. Recovery methods use the shared admission context and retain their existing real workflow
regressions; contention at every recovery verb is not separately claimed qualified here.

After that proof, release row2. The ORIGINAL active apply completes on the SAME target. Its
Prepared bytes remain unchanged; normal prepare/repeated apply returns already_applied and
sorted status reports001/002/003 complete. Ordinary typed application use reads1 admin/2 user
and inserts/reads3 user. Historical package bytes are unchanged. The owner's lifetime exceeds
the much shorter guard-acquisition budget, proving the timer did not encompass its whole body.
Application models remain present in this process; author-source removal was established by
prior separate-process journeys, not newly by this test.

## Remaining G3 and finite promotion

- Server coordination acquisition is deliberately unchanged. Native GET_LOCK still uses the
  existing driver/server wait path, and SQLite BEGIN IMMEDIATE remains guarded driver I/O.
  Their precise acquisition versus I/O budgets, diagnostics and known-versus-unknown lock
  ownership need a separate explicit policy. A local queue expiry is not a server lock timeout.
- SQLite journal/durability and native session/config/metadata admission remain separate.
  Accepting Config does not imply every ordinary runtime setting is applied to migration targets.
- Known/unknown commit outcomes around post-commit cleanup, detached cleanup/live-loop
  requirements, bounded shutdown and selected actual failure windows remain. Exiting a target
  context while caller-owned operations are still active is not made safe by this guard change.
- Maintained-version/filesystem qualification, actual WAL active death, selected native lost
  acknowledgements and final interface/ADR/coexistence/release approval remain G4/G5. No
  physical-stop, complete runtime integration, data replay, history repair or host-loss promise.

Query mapping stays independent of ownership. Existing construction/catalog/recovery gates,
strict adoption/preservation boundaries and historical epoch-one interpretation remain. No
operation/parser/adoption/format/layout/dependency or consumer-guide expansion. The prototype
is still incomplete/draft; no merge, tag or publication is authorized.

## Completed local validation

- **896 normal +896 forced-lazy experimental**, **1,784 fast**, **15 focused normal +15
  forced-lazy**, all exit0/zero failures/errors/fixture/session teardown failures. Focused runs
  combine the five local-guard cases, seven checked-out-I/O cases and three SQLite physical-
  opening cases. Native suites were sequential with distinct external TMPDIRs/context-aware
  warnings; **552** Python/program source hashes stayed unchanged through final suites/traces.
- Whole-tree ty/ruff/format/diff pass; **73** local links in changed engineering documents pass.
  All **68** historical package/Prepared JSON references remain byte-identical to the prior
  checkpoint. No historical artifact, compiler epoch, ledger layout or dependency was changed.
- Ten completed standalone final-source traces repeat all five cases in normal/forced-lazy
  processes. Guard0.15/operation5 yields queued expiry about0.150–0.153 seconds; queued-apply
  elapsed also includes public Prepared loading. Cancellation elapsed about0.05 includes the
  intentional controller pause, not just cancellation latency. The SAME owner connection is
  observed modified1/LOCK WAIT before and after the waiter, then completes on the SAME target.
  Owner elapsed is about0.337–0.458 seconds, exceeding the short acquisition budget without
  a whole-body timeout. All earlier001/002 receipt columns/values, original plan files and
  package bytes are retained; current typed1admin/2user/3user succeeds in every trace.

Evidence is under `.snektest/477-local-guard/` with matching external-cache scripts. Local Linux/
default asyncio/GIL CPython3.15.0 and MariaDB13.0.2 are not maintained-version qualification.
GitHub Actions are disabled by the maintainer; no CI checks are requested, polled, awaited or
claimed as success. This is not full-suite, all-recovery-verb contention, server coordination,
WAL/native lost-ack, physical shutdown or complete G3 qualification.

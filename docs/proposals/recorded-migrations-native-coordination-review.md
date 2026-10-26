# Recorded migrations: native coordination wait (#477)

Status: experimental, bounded G3 follow-through, not complete G3 or production/merge approval.
Follows [local guard admission](recorded-migrations-local-guard-review.md) and the
[supported-scope proposal](recorded-migrations-supported-scope.md). Query mapping stays
independent of ownership; neither local nor advisory locks fence nonparticipating writers.

## Server wait and interrupted driver I/O are different

The dedicated native target now passes Config.acquire_timeout to GET_LOCK without integer
truncation. A fractional budget such as0.25 seconds is a real fractional server lock wait,
not an immediate zero-second refusal. A server result0 means known non-acquisition and now
raises the existing MigrationLockTimeoutError, identifying **migration advisory lock**.
It is not a PackageError about historical intent and does not invalidate the synchronized
contender. Successful result1 still enters the existing coordinated flow. Other unexpected
results retain the existing refusal; this checkpoint adds no new response/SQL grammar.

The server wait is NOT an end-to-end client RPC deadline. Existing fresh operation_timeout
budgets still govern each driver call, including GET_LOCK execution. A shorter driver budget
can expire before the server's acquisition wait ends. That raises DatabaseOperationTimeoutError
with operation **migration execute**, invalidates that contender and closes its native socket.
Task/caller-scope cancellation during actual driver waiting also invalidates only that target,
with cancellation semantics preserved. No unsafe rollback/cursor/release SQL is queued.

Physical opening and local guard acquisition have their own acquisition scopes. This adds no
cumulative deadline combining opening/local wait/server wait/cleanup or the whole admitted body.
Native server acquire_timeout bounds server lock waiting; a stalled network/driver is bounded
by operation_timeout, not by a new client-wide acquisition clock. Resolving/approving that exact
end-to-end coordination policy remains G3, not silently inferred from Config acceptance.

Caller-await expiry/socket closure is NOT proof the server query stopped. A server may remain
in its existing GET_LOCK until its own timeout or another wakeup before observing disconnect.
An independent observer must establish actual absence before physical-disposal claims. The
winner's separate session and partially modified transaction must remain intact throughout.

## Public-seam workflow and actual RED

`tests/experimental/test_migration_native_coordination.py` uses visible initial/current typed
models from the preceding real I/O workflow, committed native001/002/003 role packages and
ORIGINAL versioned Prepared evidence. It seeds accounts1 admin/2 user with typed initial
writes. Both target-specific preparations occur BEFORE starting003; no prepare is fabricated
against an already uncertain target.

An independently owned transaction locks row2. The owner's actual apply003 begins its typed
UPDATE; INNODB_TRX proves LOCK WAIT with>=1 row modified. Only then does the separately connected
contender apply its own original Prepared. There is no held private Python lock, hand-built
TableState, model_copy patch, mocked driver or injected production step.

Before implementation, the retained RED is **fractional advisory-lock acquisition wait
truncated**:0.25 was converted to integer0. This is a real runtime assertion, not collection,
fixture/type/lint failure or deliberate safe schema refusal. Minimal production change retains
the float and maps known result0 to the existing coordination-timeout error. New regressions
also protect already-existing interrupted-I/O disposal behavior; they are not five new bugs.

Five cases independently observe the actual contender **User lock / SELECT GET_LOCK** server
wait before taking the next action:

1. **Known refusal:** spends the fractional acquisition wait and raises MigrationLockTimeoutError.
   The contender remains usable for public status, which truthfully sees the ACTIVE owner's
   uncertain003 evidence. That receipt is not a declaration that the owner has failed.
2. **Grant:** release row2 before the acquisition budget. The owner completes; the waiting
   contender acquires, rechecks history and returns already_applied using its unchanged
   original Prepared. No replay or stale-catalog reprepare is needed for an already complete
   package. A lock grant alone is not permission to skip the history recheck.
3. **Driver deadline:** operation0.35 versus server acquisition1.25 expires actual GET_LOCK I/O,
   rejects further target status as closed and independently awaits server disconnect.
4. **Task cancellation:** cancel only the actual GET_LOCK contender task; preserve CancelledError,
   reject its target and independently await server disconnect.
5. **Caller scope:** cancel the contender's own AnyIO scope; it catches its cancellation,
   rejects that target and independently awaits server disconnect.

For all non-grant cases the SAME owner server connection is still LOCK WAIT/modified>=1 after
waiter handling, including physical disconnect observation for unsafe contenders. Only then
release row2; the owner completes. Known-safe contenders reuse their SAME target/original;
unsafe ones use a fresh target with ORIGINAL evidence, observe already_applied and never retry
unacknowledged data work. Sorted owner status reports001/002/003 complete. Ordinary typed
application use reads1 admin/2 user and inserts/reads3 user; package/Prepared bytes are retained.
Cleanup releases only the test's blocker and joins its own tasks even on a RED.

## Remaining policy and promotion

- SQLite writer coordination and busy-refusal diagnostics are unchanged. Its worker busy wait,
  unknown BEGIN outcome, interrupt/queued close and journal mode are different from native
  advisory waiting. This checkpoint does not claim backend parity or qualify all recovery verbs.
- Native/SQLite end-to-end admission budgets, native session/config/metadata admission,
  journal/durability, positive release ownership and known/unknown commit outcomes around
  post-commit cleanup still need explicit policy/selected failure-window evidence.
- Caller-owned task/context lifetimes and bounded shutdown remain. Known lock refusal is not
  a native data-recovery disposition; an interrupted would-be coordinator must not manufacture
  a second uncertain execution or infer the active winner stopped. No fairness or writer fencing.
- Maintained finite matrix, WAL active-backfill death, selected native lost acknowledgements
  and final interface/ADR/coexistence/release approval remain G4/G5. Local MariaDB13.0.2 is not
  maintained-version qualification. Original Prepared persistence still needs secure caller
  storage and does not authenticate input or prove host/volume-loss recovery.

No format, epoch, ledger layout, parser, adoption, dependency or consumer-guide expansion.
Existing construction/catalog/history/recovery gates remain. Prototype/draft only; no merge,
tag or publication. Maintainer-disabled GitHub Actions are not polled or awaited as evidence.

## Completed local validation

- **901 normal +901 forced-lazy experimental**, **1,784 fast**, **25 focused normal +25
  forced-lazy**, all exit0/zero failures/errors/fixture/session teardown failures. Focused
  coverage combines native coordination/local guard/checked-out-I/O/native and SQLite opening.
  Native suites were sequential/distinct external TMPDIRs with context-aware warnings.
- Whole-tree ty/ruff/format/diff pass; **75** local engineering links; **553** Python/program
  source hashes stable across final suites/traces/commit readback. All **68** historical
  package/Prepared JSONs remain byte-identical to the prior checkpoint. No dependency changes.
- Ten completed final-source standalone traces repeat the five cases in normal/forced-lazy
  interpreters. The actual GET_LOCK waiter is independently captured. Known refusal at server
  budget0.25 returns about0.256 seconds; the SAME contender session remains present/idle and
  public status works. Actual queued grant returns already_applied after winner completion.
- Driver budget0.35 versus server wait1.25 returns about0.358 seconds with **User lock /
  GET_LOCK STILL PRESENT** after caller failure. Independent absence is established only about
  1.115 seconds from the contender's start, not at caller expiry. Task/scope cancellation also
  leaves an actually observed server waiter after caller return; independent absence is about
  1.065–1.071 seconds from start. Cancellation elapsed includes public Prepared load and
  controller observation, not pure cancellation latency. Observed absence is polling evidence,
  not the precise physical stop instant or a universal server/OS cancellation guarantee.
- In every non-grant trace the SAME owner connection is still modified1/LOCK WAIT AFTER all
  contender handling/disconnect observation. ALL active ledger columns/values remain unchanged
  while that owner is blocked. Release row2; it completes on the SAME target. ALL earlier001/002
  receipt columns/values match their own pre-003 values; original owner/contender Prepared files
  and package bytes remain. Normal typed1admin/2user/3user succeeds in all ten traces.

Evidence: `.snektest/477-native-coordination/`, matching external-cache scripts and empty owned-
server audit after completion. Local Linux/default asyncio/GIL CPython3.15.0/MariaDB13.0.2 is not
maintained-version qualification. Actions remain maintainer-disabled: no checks requested,
polled, awaited or counted as success. No full-suite/matrix/all-recovery-verb contention,
SQLite-coordination/WAL/native lost-ack/grant-at-cancel/release-failure/shutdown qualification.

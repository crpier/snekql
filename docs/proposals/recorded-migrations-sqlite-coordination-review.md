# Recorded migrations: SQLite writer coordination (#477)

Status: **bounded experimental G3 checkpoint**, not complete runtime integration or
production/merge/release approval. Follows the
[native coordination checkpoint](recorded-migrations-native-coordination-review.md).

## Decision and actual RED

A completed `BEGIN IMMEDIATE` response with exact `SQLITE_BUSY` now raises the existing
`MigrationLockTimeoutError` with **timed out acquiring migration SQLite writer lock** and
retains the synchronized target. It is not an interrupted await or an uncertain package.
Previously the same public role application exposed raw `OperationalError`; the real RED
expected the phase-specific lock error and received that driver error. This is a bounded
acquisition-diagnostic gap, NOT evidence of data loss, false completion or missing busy waits.
The existing driver busy timeout already used the fractional acquisition value correctly.

Only the actual SQLite numeric result `SQLITE_BUSY` from `BEGIN IMMEDIATE` is mapped. No
message matching or blanket OperationalError/SQLITE_LOCKED/extended-BUSY conversion. Errors
from package work, COMMIT or observation are not relabeled as acquisition. The driver remains
responsible for its busy-handler clock; the independently active per-I/O `operation_timeout`
can win first. No new end-to-end client acquisition clock, shared/cumulative timer, polling
scheduler, public policy object, generic runtime or convenience facade.

The normal coordinated failure path preserves the primary error, rolls back only a safe
connection and restores rebuild policy. Interrupted I/O still invalidates the target and owns
physical SQLite disposal without queueing rollback/policy SQL on the unsafe connection.
Caller cancellation remains cancellation. An interrupted pending BEGIN can outlive its caller
and even acquire the writer transaction later; no package continuation is admitted, and the
owned close releases it. Caller completion/interrupt are not physical-stop evidence.

## Representative workflow, not additional verifier surface

`tests/experimental/test_migration_sqlite_coordination.py` uses unchanged committed SQLite
001 accounts /002 nullable role /003 typed backfill+contraction packages, real Initial/Account
query mappings and public connect/prepare/original apply/status/ordinary typed query seams.

1. Apply001, seed normal typed rows1admin-flag/2user-flag, observe actual DELETE mode after
   ordinary runtime use, apply002 and retain the original003 Prepared envelope BEFORE waiting.
2. An independently owned aiosqlite transaction executes real `BEGIN IMMEDIATE`. It takes the
   database writer reservation without changing schema/data; not a fake/private Python lock,
   fabricated receipt/state, patched driver or injected migration step.
3. OS observation identifies the dedicated target worker by thread-set difference around
   physical opening and observes its actual `hrtimer_nanosleep` while SQLite's busy handler
   waits. That Linux observation establishes the tested cancellation window; no private
   driver/target attribute is inspected, no global lease/timeout/process setting changed.
4. Five dispositions: exact BUSY at acquire0.2/operation3 retains SAME target/status/original;
   release/grant completes the ORIGINAL; operation0.15/acquire2 fails closed; task and caller
   scope cancellation preserve semantics and reject further use of their unsafe target.
5. Join owned tasks/release only the owned writer. For unsafe targets close the contexts and
   independently observe database descriptors disappear BEFORE a fresh target. Fresh status
   must equal the pre-003 evidence: no late package/receipt. Explicit ORIGINAL apply then
   completes. Safe targets continue on SAME target. Repeated apply observes already_applied.
6. All001/002/003 statuses complete, packages/original evidence retained and ordinary typed
  1admin/2user/read+insert3user succeeds. Models stay present; this is not new source-removal,
   codec evolution or historical interpretation evidence; those were earlier checkpoints.

Only the known BUSY diagnostic is new behavior. Grant/cancellation/deadline/disposal cases
protect existing behavior, not four additional bugs. A missed formatted-signature replacement
while expanding the initial green test was an authoring NameError, not a runtime defect.

## Limits and remaining work

- File-backed DELETE on the observed local Linux/kernel/default asyncio/SQLite build. Actual
  `wchan` spelling/thread identities are finite test-environment observations, not a portable
  library requirement. No WAL active-death, other OS/filesystem/event-loop/maintained matrix,
  all recovery-verb contention, power-loss/failed-close/shutdown qualification follows.
- No automatic retry/replay, stamping, new uncertainty receipt or source reconstruction on
  known refusal. Original Prepared is target-specific; history/catalog checks still apply.
- Busy acquisition and per-I/O deadlines differ; local guard/physical opening have separate
  acquisition scopes. Grant-at-cancel/cleanup outcomes still require fresh evidence; no
  physical-stop bound follows from an awaited deadline or retained cleanup task.
- Participating locks do not fence external schema/incompatible affected-data writers. Caller
  exclusions and separate application-readiness/codec checks remain necessary. SQLite's single
  writer serializes compatible transactions too; no online-schema-change promise.
- G3 still needs the explicit end-to-end coordination policy choice, session/config/metadata
  admission, journal/durability, positive lock-release/commit outcome and bounded shutdown/
  live-loop policy. G4 finite matrix/failure windows and G5 interface/ADR/release approval stay
  open. No parser/format/epoch/ledger/adoption/dependency/consumer-guide expansion.

## Completed final-source local validation

- **906 normal +906 forced-lazy experimental**, **1,784 fast**, **30 focused normal +30 lazy**,
  all exit0/zero failures/errors/fixture/session teardown failures. Focused coverage combines
  five SQLite coordination cases with native coordination/local guard/checked-out I/O/native
  and SQLite physical opening. Native suites were sequential/distinct external TMPDIRs with
  context-aware warnings; whole-tree ty/ruff/format/diff pass.
- **554** Python/program hashes stable across final suites, ten standalone normal/lazy traces
  and commit readback; **68** historical package/Prepared JSONs unchanged; **76** local links.
  Earlier development reports under `before-status-normalization/` are excluded from these
  results: a test was corrected to compare sorted status rather than assume portable ordering.
  Its deliberate manifest mismatch is not a runtime defect; all final-source suites reran.
- Every trace independently captures the identified target worker in `hrtimer_nanosleep`
  BEFORE disposition. Exact known BUSY code5/nameSQLITE_BUSY at acquire0.2 returns about
  **0.209s**, same target/status still usable; worker is idle afterward. Release/grant lets
  ORIGINAL application complete, with repeated apply observing already_applied.
- Operation0.15 returns about **0.156s** while that SAME worker is STILL `hrtimer_nanosleep`
  and database descriptors remain. Task/scope cancellation also returns while it is still
  sleeping. These are real continuing busy waits, not a private fake. Cancellation elapsed
  includes public Prepared load/controller observation, not pure cancellation latency.
- Release the OWN writer; close owned contexts. Independently observed worker disappearance
  AND zero database descriptors precede any fresh application. Unsafe-mode observations after
  disposal retain ALL original ledger columns/values and actual rows `(1,1,NULL),(2,0,NULL)`:
  no late backfill, schema contraction or new003 receipt. Explicit ORIGINAL apply on a fresh
  target then completes. Disposal elapsed includes controller release/context closing and is
  polling evidence, NOT a guaranteed physical-stop deadline or exact disposal instant.
- ALL earlier001/002 receipt columns/values match their OWN pre-003 values in every trace.
  Original plan/package bytes retained; ordinary typed1admin/2user/3user succeeds in all ten.
  The ordinary runtime can switch the journal later; that is not WAL interruption evidence.

Evidence: `.snektest/477-sqlite-coordination/` and matching external-cache scripts. Final
validation/trace runners finished; owned-server audit empty. Local default asyncio/GIL
CPython3.15.0/Linux/SQLite3.53.1/MariaDB13.0.2, not maintained-version qualification. Actions
remain disabled: no CI requested, polled, awaited or claimed. No merge/tag/publication.

## Native UTC admission follow-through

The [native UTC checkpoint](recorded-migrations-native-utc-review.md) applies/readbacks the
shared ordinary runtime UTC policy before yielding a dedicated native target, through owned
per-I/O deadlines. Actual frozen role/clock work under non-UTC server defaults now agrees with
ordinary DATETIME/TEXT UtcDatetime reads/writes; SQL-mode rendering evidence is not normalized
away and old rows/receipts are never repaired. This is only UTC session admission, not version/
metadata/strictness/enforcement admission or complete G3. Journal/durability and remaining
outcome/shutdown policy, G4/G5 and release decisions remain open.

# Recorded migrations: bounded context-exit drain (#477)

Status: **bounded experimental G3 lifecycle checkpoint**, not global shutdown/quiescence,
G4/G5 qualification or release approval. Follows
[shared native version admission](recorded-migrations-native-version-review.md).

## Real gap and lifecycle policy

Leaving connect while a caller-owned apply task was blocked immediately closed the native
socket. Real original role003 UPDATE held row1/LOCK WAIT on row2; context exit returned before
the caller could release its blocker and let original work complete. Clean RED:
`context exit discarded active original role work instead of draining`. It demonstrates an
abrupt lifetime boundary, NOT corruption/false completion or that disconnected native work
physically stopped. Caller tasks remain caller-owned; a Target does not supervise/cancel them.

Context exit now:

1. Stops NEW public admission immediately with PackageError/`migration target is closing`.
   Already-queued public callers recheck AFTER acquiring the local guard, so they cannot sneak
   new SQL between the current owner and close. Closed/unsafe targets still report closed.
2. Drains the currently admitted operation, including its own rollback/release/policy cleanup,
   under a NEW acquire_timeout guard-wait budget. Active owner can keep using its I/O while
   closing; the closing flag is not premature physical/unsafe closure. Only acquired guard
   ownership is released. Other Target instances are not globally shut down or fenced.
3. After drain, closes native socket or starts/joins owned SQLite physical close with a fresh
   operation_timeout. If active work already discarded itself, its existing detached cleanup
   owns disposal; no rollback/cursor/policy SQL is queued on the unsafe connection.
4. On expired drain: discard connection and raise PoolTimeoutError/`timed out acquiring
   migration target shutdown guard`. On failed/cancelled drain: discard and retain that failure/
   cancellation. No unbounded wait, user-task cancellation, forced success, automatic replay or
   claim that closing the client physically stops a SQLite worker/native server operation.

Existing connect failure precedence preserves the PRIMARY body exception if drain/close also
fails, logging cleanup failure. Success then failed shutdown surfaces shutdown error without
rewriting acknowledged evidence. Guard wait is not checked-out I/O, and normal physical close
has its own budget. Cancellation of the public context's task must not abandon a logically
closing but physically reusable/admitted connection.

## Three vertical real RED/GREEN cycles

- Native blocked role work: abrupt old context close vs graceful guard drain/new admission stop.
- Intermediate UNBOUNDED drain: context still waits beyond intended acquire budget; clean RED
  `context exit drain acquisition deadline ignored`, then fresh bounded wait/discard. This is
  a safeguard for the introduced drain, not a claim shipped old code waited unboundedly.
- Cancellation while waiting: intermediate close left owner live/admitted after close task
  cancellation. RED `cancelled shutdown left the active session admitted`, then discard on
  failed/cancelled guard wait. Task cancellation remains primary; library does not cancel apply.

The first bounded test incorrectly waited for native server disappearance while its row
blocker remained held. Actual native session can keep waiting after socket close; observer
15s timeout was a TEST cleanup-order assumption, NOT failure of the close deadline. Final
workflow releases its OWN blocker then independently observes physical disappearance/data
before choosing original recovery. Development report retained/excluded; final sources rerun.

## Public representative workflow

`test_migration_context_exit.py` retains visible literal001/002/003, normal typed flag rows1/2,
ORIGINAL003 saved before apply, ALL own earlier001/002 columns and original package/plan bytes.
No private production-helper assertions, fabricated state/history, mocked driver or migration
callbacks. Actual caller context coroutine exits while separately caller-owned apply runs.

- Native finish: actual UPDATE LOCK WAIT/modified>=1; close pending leaves SAME server owner
  alive. New status refuses immediately; status already queued BEFORE exit refuses after guard
  grant without SQL. Release blocker, original apply returns applied, context closes, actual
  session absence; fresh original already_applied/sorted complete status/current typed1admin/
  2user/3user. No mid-operation socket cut or owner result suppression.
- Native drain timeout: operation_timeout10 vs fresh close guard0.15. Refuse new work, expire
  PoolTimeoutError, failed original apply reports a real driver error without being cancelled
  by library. Release OWN blocker, observe physical absence and actual rollback/NULL roles;
  fresh public003uncertain/ack0, blind apply refuses; inspect ORIGINAL retry_remaining0, EXPLICIT
  resume completes, then repeat/status/current typed use. Timeout alone is not rollback proof.
- Native close-task cancellation: same real blocked work; preserve CancelledError/discard, join
  caller apply's real error, release blocker/observe physical state before same original recovery.
- Native PRIMARY body error: same blocked work, guard drain expires, but identical caller
  RuntimeError survives; failed cleanup logs/discards. Same observed uncertainty/original recovery.
- SQLite DELETE finish: independent writer holds BEGIN IMMEDIATE, OS observes actual busy worker.
  Exit stops admission/drains guard rather than queues close behind active worker; release writer,
  SAME original applies/context closes. Independent descriptor disposal after owned writer closes,
  fresh original already_applied and ordinary typed use. Not SQLite drain-timeout/failed-close/
  WAL-active-death/portable OS-wait qualification. In-memory volatile policy remains unchanged.

## Explicit budget decision (candidate policy, G5 approval still pending)

Retain SEPARATE physical-opening acquisition, public local-guard acquisition, backend coordination,
checked-out per-I/O/control operations, context-exit guard drain and physical-close budgets.
Do NOT add an implicit end-to-end acquire/package/context timer. Config's acquisition budget
is reused freshly at each relevant acquisition/drain seam; operation budget is reused freshly
for individual I/O/control/physical close. Work/caller pauses before a seam do not consume its
budget. Caller outer cancellation/timeouts remain possible, NOT physical-stop/rollback evidence.
This resolves the G3 engineering budget choice; no new knob/facade or cumulative timer is added.

## Remaining lifecycle limits

This is one Target's context lifetime, NOT process shutdown/task supervision/a global cleanup
join. Caller must join its own operation/queued tasks and keep asyncio loop alive for retained
SQLite opening/unsafe physical cleanup. Logical closure/deadline != disposal; late failed-close,
loop shutdown/global cancellation/host death remain unqualified. No force release, replay,
portable plan identity/backup or retrospectively stronger history. Metadata/other native
prerequisites, broader COMMIT/lost-ack outcomes and remaining detached-cleanup/shutdown rules,
G4 finite matrix/WAL active-backfill death/native lost-ack and G5 approval remain open.
No new artifact/epoch/layout/parser/adoption/dependency/consumer-guide scope or release action.

## Completed local evidence (final source)

- Experimental: **931 normal + 931 forced-lazy**, fast1784, focused133+133; zero failures,
  errors or fixture/session teardown failures. Separately repeated actual10.10.7 version-floor
  regression1normal+1lazy, not full old-server/matrix qualification. Normal suites use current
  installed13.0.2 with old-server selector unset. Existing focused ordinary fake-probe/fault
  regressions remain; not all focused cases are real I/O.
- **10 fixed** normal/lazy role traces and **five actual archived462db89** runtime traces with
  project interpreter/verified module/source paths. Fixed native successful close drains in
  ~0.177–0.191s; selected guard deadlines ~0.1505–0.1511s; task-cancel close ~0.050s after test's initial
  50ms observation. These are finite observations, not a scheduling/wall-clock guarantee.
  Deadline/task/primary traces independently observe SAME native server still in LOCK WAIT
  AFTER caller context return, then release OWN blocker/observe disappearance/actual rollback
  before original inspect/resume. Old native closes early/original uncertain; explicit original
  recovery retained, not old policy passing. Old SQLite status waits behind the active guard;
  BEGIN reaches writer-acquisition refusal before status rejects closed, then fresh original
  applies without an old003receipt. No old SQLite recovery replay/late COMMIT claim.
- Initial archive observer over-specified SQLite failure as PackageError; actual public apply
  reported MigrationLockTimeoutError from busy BEGIN. Observer assertion corrected to retain
  real error, ALL10fixed/five archived traces rerun under same observer hash. Prior observations
  excluded under `before-observer-error-kind/`, not production failures. No source/fixture
  weakening, injected driver, environment repair or fabricated history.
- Whole-tree ty/ruff/format/diff, **562 stable Python/program hashes**, **69 historical JSONs
  unchanged** against462db89, **99 unique changed-Markdown local links**. Working source remained
  unchanged throughout final suites/traces; observer/runtime provenance and exact committed
  source readback retained. Evidence `.snektest/477-context-exit/` and matching external cache.
  All runners/owned servers finished; Actions disabled, not requested/polled/awaited/claimed.

Environment: CPython3.15.0/GIL/default asyncio/Linux/SQLite3.53.1/MariaDB13.0.2, not maintained
LTS/SQLite-floor/all-build/upgrade/MySQL qualification. G3 is **still incomplete**; candidate
budget/lifecycle policy does not accept ADR0023, settle all outcomes/shutdown, or approve G4/G5.

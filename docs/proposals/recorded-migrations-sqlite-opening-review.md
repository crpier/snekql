# Recorded migrations: owned SQLite physical opening (#477)

Status: experimental, bounded G3 follow-through, not production/merge approval. Follows
[native opening](recorded-migrations-native-opening-review.md),
[checked-out I/O](recorded-migrations-io-deadline-review.md) and the
[supported-scope proposal](recorded-migrations-supported-scope.md). This does not complete
coordination acquisition, session/durability, shutdown policy or environment qualification.

## Physical opening and caller admission are different

SQLite `m.connect` now uses the existing acquire_timeout for the physical connection-opening
await. Previously that setting only reached SQLite as a busy timeout, which cannot bound an
OS-blocked file open. Expiry reports the existing PoolTimeoutError identifying opening, as on
the native path. A shorter checked-out operation_timeout does not govern physical opening.
The opening scope ends before constructing/yielding the target; SQLite foreign-key admission
still runs as checked-out guarded I/O with its own fresh operation budget. This is not a new
whole-context or whole-admission deadline.

Cancellation/deadline must NOT cancel aiosqlite's pending connection creation. A real blocked
open may still produce a raw SQLite handle after its caller has gone. The target therefore
shields one owned opening future. On acquisition timeout or caller cancellation it transfers
that future to independently retained cleanup, awaits the eventual result and explicitly closes
any resulting connection. Close must not be queued against an unopened driver: its close method
would have no handle to close yet. No target or package coroutine is resumed by that late result.

The small private live-cleanup set retains and observes these tasks when no Target exists yet.
Late opening failure is observed separately from failure to close a successfully opened handle;
cleanup does not replace the caller's primary timeout/cancellation. This is not a public task
registry, connection pool, new timeout option, alternate runtime or generic transport facade.
Existing ordinary-runtime SQLite opening/settings/pool behavior is not changed in this slice.

Deadline delivery is NOT physical stop. Pending worker/OS activity can continue, including file
creation/opening; the caller cannot infer quiescence or authorize later work just because an
acquisition failed. Cleanup requires the event loop to remain available. Arbitrary global task
cancellation, loop shutdown, host/process death and failed-close policy are not discharged by
retaining an in-process task. Interrupted cleanup is observed/logged, not reported as success.

## Actual public-seam TDD

`tests/experimental/test_migration_sqlite_opening.py` drives visible programs under
`fixtures/sqlite-opening/`. The operator uses `m.connect`, real committed historical role
packages, versioned ORIGINAL Prepared evidence, status and ordinary typed application queries.
Initial/current application mappings are explicit. No hand-built recorded states, fabricated
receipts, driver replacements, private production-helper assertions or injected migration steps.

An owned helper process takes a Linux F_SETLEASE write lease on one owned empty database file.
It reports an actual SIGIO lease-break request when the real SQLite worker attempts open(2),
but retains the lease until the controller releases it or closes stdin. No global lease time,
filesystem setting, unrelated process/database or system configuration is changed. The helper
is not a SQLite implementation: actual SQLite and the kernel perform the blocked operation.
These tests require the observed Linux file-lease/proc facilities; they are not portable OS or
filesystem qualification. Subprocesses explicitly propagate/assert forced-lazy mode.

### First RED: ignored acquisition deadline

The old public interface remains pending after the configured acquisition budget even though
an actual kernel lease wait has been observed. The watchdog reports **SQLite opening acquisition
deadline ignored**; it does not cancel the library call or serve as physical disposal evidence.
Finally releases the owned lease and reaps only the owned processes even on a RED.

### Second RED: a timer alone loses explicit ownership

The first minimal fail_after wrapper returns the right timeout, but cancels the driver's pending
open. After the controller releases the lease, the late connection relies on implicit GC close.
The real child process runs with ResourceWarnings enabled and its stderr reports
**ResourceWarning: unclosed database in <sqlite3.Connection ...>**. This is a genuine second RED,
not a fabricated warning or a mocked close. The explicit-owner implementation removes that
warning while retaining the deadline. The negative-control patch and completed RED reports are
retained under `.snektest/477-sqlite-opening/`.

### Cancellation, physical disposal and fresh deployment

Three cases cover acquisition expiry, task cancellation and caller-owned AnyIO-scope cancellation.
Cancellation cases deliberately wait longer than operation_timeout but less than acquire_timeout,
then cancel the real blocked acquisition. Task cancellation remains CancelledError; the caller's
scope catches its own cancellation. In each case the target body was never entered.

While the caller has already stopped waiting, both the child and its independent controller
observe the same worker TID STILL in the Linux break_lease wait. This directly demonstrates why
caller completion is not physical stop. Only then does the controller release the lease.
The operator observes those actual kernel worker TIDs disappear and real database descriptors
vanish before any fresh acquisition. Child stderr must have no ResourceWarning: disposal is
explicit rather than a GC assumption. No private task/driver closed flag is used as proof.

After those observations, the caller explicitly chooses a fresh budget/connection. Empty status
proves no late migration was admitted. Load the unchanged SQLite001 accounts/002 nullable role/
003 frozen typed backfill+contraction chain, apply001, seed initial typed1 admin-flag/2 user-flag,
then apply002 and reload/apply ORIGINAL versioned003 Prepared bytes. Complete/already_applied and
sorted progress are observed. The normal typed application inserts/reads3 user and reads1 admin/
2 user. Package/Prepared bytes are unchanged; no caller manually stitches declaration states.
Application models are visible in this process, so this is not new author-source-removal proof.

The dedicated connector does not change journal mode or implement a new durability policy.
The ordinary application runtime may apply its existing WAL settings between stages, as it
already does. This functional journey is neither active-WAL process death nor a durability,
receipt-loss, data-replay or native crash qualification.

## Remaining G3 and promotion scope

- Local target-guard waiting and server coordination-lock acquisition still need an explicit
  acquisition policy distinct from physical opening and checked-out per-I/O waits. A queued
  caller must not invalidate a connection actively owned by another operation merely because
  that caller's admission wait expires.
- SQLite journal/durability and further native/session/config/metadata-admission policy remain.
  Passing the shared Config is not proof that every ordinary runtime setting is implemented.
- Known/unknown commit outcomes around post-commit cleanup, bounded shutdown/detached cleanup
  expectations and selected actual failure windows remain. This slice does not induce failed
  physical close, loop shutdown or an abandoned opening that later fails instead of opening.
- Maintained-version/filesystem qualification, actual WAL active death and selected native lost
  acknowledgements remain G4; interface/ADR/coexistence/release approval remains G5. Sensitive
  original evidence still needs caller-owned secure durable storage plus ledger; no backup,
  host-loss, authentication or portability promise follows.

All existing catalog/construction/recovery gates, strict adoption/preservation boundaries and
historical epoch-one interpretation remain. Query mapping stays independent of ownership;
no operation/parser/adoption/format/layout/dependency expansion or consumer-guide promotion.
Prototype remains incomplete/draft; no merge, tag or publication is authorized.

## Completed local validation

- **891 normal +891 forced-lazy experimental**, **1,784 fast**, **15 focused normal +15
  forced-lazy**, all exit0/zero failures/errors/fixture/session teardown failures. Focused runs
  combine three SQLite-opening cases, five native-opening cases and seven checked-out I/O
  cases. Native suites ran sequentially with distinct external TMPDIRs/context-aware warnings.
- Whole-tree ty/ruff/format/diff pass; the two visible subprocess programs also pass explicit
  ty checks as Python files. **551** Python/program source hashes stayed unchanged throughout
  final suites/traces; **68** historical JSON references are unchanged against the previous
  checkpoint. **69** local links in changed engineering documents/fixture notes pass.
- Six completed final-source operator traces repeat deadline/task/scope in normal and forced-
  lazy processes. All independently observe continuing kernel lease waits after caller return,
  then worker-TID exit/database-FD disappearance and no ResourceWarnings before fresh role
  deployment/current typed1admin/2user/3user. All original plan files are retained. The configured
  acquisition0.15 cases report elapsed about0.158/0.160 seconds, including waiter observation;
  cancellation elapsed values include the controller pause, not just cancellation latency.

Evidence is under `.snektest/477-sqlite-opening/` with matching external-cache scripts. The local
Linux7.2/default asyncio/GIL CPython3.15.0, SQLite3.53.1 and aiosqlite0.22.1 observations do not
establish the maintained-version/filesystem matrix, all opening failures, loop shutdown, physical
close failure, WAL/native lost-ack or a full-suite/CI-success claim. Pending/unregistered checks
are not awaited or treated as success.

# Recorded migrations: positive bounded native coordination release (#477)

Status: **bounded experimental G3 checkpoint**, not full outcome/shutdown policy, G4/G5
qualification or release approval. Follows
[SQLite journal/synchronization](recorded-migrations-sqlite-durability-review.md).

## Real defect and release policy

The experimental target sent one RELEASE_LOCK and ignored its result. MariaDB counts recursive
ownership: a successful1 can mean one level released while the SAME session still owns the
migration lock. A real owned server init_connect acquired three levels before target use;
public apply acquired one more, completed original role003 and returned applied, but an
independent observer's GET_LOCK(name,0) returned0 while the target stayed open. Actual RED:
`native migration returned with coordination still owned`. This is a coordination leak, not
observed data loss, corrupt receipt or server defect. The released runner already drains
recursive ownership ([ADR0002](../adr/0002-advisory-locked-concurrent-migrations.md)); its driver
owner is not reused because that would bypass the experimental target's owned I/O deadlines.

Track successful acquisition LOCALLY to the coordinated scope; release only after positively
acquired BEGIN/GET_LOCK. Known native acquisition refusal must not enter release confirmation
or invalidate a synchronized contender. SQLite rebuild FK restoration remains independent of
whether BEGIN succeeded. Existing per-operation/guard/unsafe-disposal gates remain intact.

For native acquired scopes, drain ONLY this migration lock name until at least one1 is followed
by0 (another session may have acquired after us) or NULL (unowned/nonexistent). A first0/NULL or
unexpected shape raises existing MigrationLockError, and the outer policy owner discards the
connection. No RELEASE_ALL_LOCKS, arbitrary other-name release, blanket retry or force success.
Query/fetch/cursor close remain owned by Target._query, never raw cleanup driver SQL.

## A fresh bounded release operation, not a package deadline

A drain loop with a new deadline per individual query could run arbitrarily long. One fresh
`operation_timeout` budget encloses the ENTIRE release-control operation, while its internal
I/O remains owned/deadlined too. It starts AFTER body work/rollback and is not cumulative with
physical opening, local guard/server coordination, prior queries, body pauses or the package.
This is a cleanup/control-operation budget, not a new end-to-end acquire/package/context timer.
Diagnostic on expiry: DatabaseOperationTimeoutError.operation=`migration advisory lock release`.
Timeout/cancellation invalidates the session through the existing owner; no further SQL queued
on that unsafe connection. Physical server disappearance is observed separately, not inferred.

The real finite deadline case preclaims4096 levels in server init_connect through an owned
bootstrap procedure in a separate fixture schema (not invoked by migration work). Without the
outer release-control budget, individual calls keep completing and public apply returns instead
of the expected deadline: the second clean RED. With the budget, it expires after ACKNOWLEDGED
role003 completion, not during COMMIT. The target is closed, but fresh evidence says complete;
SAME original returns already_applied, not rollback, unknown COMMIT or data replay.

If cleanup fails during a body error, existing failure precedence retains the PRIMARY error and
logs/discards cleanup failure. If cleanup fails after success, surface it without rewriting or
rolling back acknowledged receipts. No new public exception/outcome envelope or proof that
every postcommit/cancellation/failed-release/privilege window is qualified. Native unacknowledged
COMMIT/DDL windows remain separate G4 work; known cleanup failure is not unknown commit.

## Public representative workflow / real server observations

`test_migration_native_release.py` owns a real password-authenticated server and a non-SUPER
fixture user with current-schema grants. Independent root connection saves GLOBAL general_log,
log_output and init_connect; restores ACTUAL values in finally and drops owned user/bootstrap
schema. General log is briefly enabled to DISCOVER the actual advisory name from server SQL;
no private production method/lock-name formula asserted, fabricated receipts or mocked driver.
The user authenticates normally and the REAL server executes init_connect before target use.
No fake greeting/version/server, injected migration step or runtime callback facade.

- Literal001, normal typed flag rows1/2, literal002; save ORIGINAL003 before application. Caller
  maintains incompatible writer/schema exclusion. Identity is the observed database, not the
  currently authenticating user; grants here expose the required real metadata.
- Three named cases: successful work, primary catalog refusal, bounded postcommit release expiry.
  Short bootstrap claims migration name three times and an unrelated name once. It is trusted
  server setup, not a new schema capability/permission inferred from models. Deadline case uses
  a separate-schema bootstrap procedure to fit init_connect's4096-character limit, then4096
  real server claims; no migration data step calls it or weakens the current-schema routine gate.
- Success/refusal leave SAME target alive: independent GET_LOCK0 obtains1 and releases ITS own
  grant; unrelated name STILL belongs to original target. Primary PackageError/catalog refusal
  leaves no003; dropping only the caller's deliberate marker restores original catalog, and
  SAME original applies on SAME target. Repeat/status and ordinary typed1admin/2user/3user work.
- Deadline after body completion rejects unsafe target use; independently wait for actual server
  session absence before observing both names free. Fresh admitted target rechecks original
  already_applied. ALL own earlier001/002 receipt columns remain, package/plan bytes retained.

An initial too-long inline init_connect program hit real server1470/4096-char limit during
SETUP, not migration runtime: retained as authoring feedback, not a deadline defect. The real
bounded-release RED uses the actual short CALL/bootstrap procedure. No borrowed external
service/config or unsupported fixture-driver injection. Models stay present; this is not new
model/author removal, writer fencing, general privilege audit or readiness certification.

## Remaining effort

G3 native version/strictness/metadata prerequisites, explicit end-to-end admission choice and
remaining commit-outcome/shutdown/live-loop policy stay open. This resolves positive bounded
native release and one known postcommit cleanup-expiry observation, not every cleanup failure.
G4 maintained matrix/WAL active-backfill death/native receipt-loss windows and G5 interface/
ADR/coexistence/release approval remain. No conversion/repair/replay/stronger old receipt,
new artifact/epoch/layout/parser/adoption/dependency/consumer-guide scope or release action.

## Completed local validation and actual archived comparison

- **921 normal +921 forced-lazy experimental**, **1,784 fast**, **96 focused normal +96 lazy**,
  all exit0/zero failures/errors/fixture/session teardown failures. Focused =earlier93 +three
  real native release cases (includes earlier existing ordinary regression fault injection;
  no new driver/migration-step mocking). Whole-tree ty/ruff/format/diff; native suites/traces
  sequential/distinct external TMPDIRs/context-aware warnings. Not a full-suite/matrix claim.
- **559** Python/program hashes stable through final suites/six fixed normal/lazy traces/
  three actual archived observations/commit readback. ALL **69** prior package/Prepared JSONs
  unchanged against2a3c55e; **91** local links across unique changed Markdown list. External
  observer/archive/module/source provenance independently verified. No artifact/epoch/layout.
- Six final-source traces retain ORIGINAL003 and ALL own earlier001/002 columns/values, real
  pre-claiming session ID, independently observed GET_LOCK0 grant1 while target remains alive,
  retained unrelated ownership after success/primary refusal, primary error/no003 on refusal,
  same-target original application/repeat/status and typed1admin/2user/3user. For deadline,
  actual public call elapsed~0.290–0.295s INCLUDING validation/body work; its fresh RELEASE
  control budget alone is0.15s, not a whole-apply/physical-stop deadline. Target closes, server
  absence independently observed, fresh ORIGINAL already_applied and complete003 receipt.
- ACTUAL archive2a3c55e via project interpreter/verified archive module paths repeats the same
  three server setups/literal roles. Independent GET_LOCK0 returns0 in ALL cases while target
  lives; owner retains migration name after success/primary refusal and no bounded drain in
  large-depth case. Data/completion receipts remain truthful; closing target eventually frees
  names and fresh ORIGINAL already_applied works. This isolates a connection-lifetime lock leak,
  not permanently stranded ownership or data corruption. Archived exit0 means expected-defect
  observation completed, not a passing fixed workflow. Never compare target-specific receipt/
  plan hashes across runs, rewrite earlier receipts or replay data to manufacture evidence.

Evidence: `.snektest/477-native-release/`, matching external-cache scripts. All development/
final/trace/archive runners finished, owned-server audit empty. Setup1470/inline-limit error
and link-scanner duplicate-list guard are authoring/audit feedback, not runtime defects. Final
working production/test/program source stayed unchanged throughout completed qualifying runs.
Local default asyncio/GIL CPython3.15.0/Linux/SQLite3.53.1/MariaDB13.0.2, not maintained LTS
qualification. Actions remain disabled: no CI requested/polled/awaited/claimed. No every-release-
response/failed-cleanup/primary-plus-cleanup-failure/caller-cancel/privilege window, WAL active-
death/power-loss/native lost-ack/shutdown qualification, consumer guides or release action.

## Inherited native strictness follow-through

The [strictness checkpoint](recorded-migrations-native-strictness-review.md) moves the existing
InnoDB strict-mode prerequisite to admission as well as retaining the live required-column
check. Verify inherited STRICT_TRANS_TABLES or STRICT_ALL_TABLES without rewriting sql_mode;
weak sessions refuse BEFORE yield/original-role execution, and NO_BACKSLASH_ESCAPES remains in
actual execution evidence. Ordinary all-table normalization is unchanged. No old receipt/data
repair or new artifact/epoch/layout. Remaining native version/metadata/other prerequisites,
admission/outcome/shutdown policy and G4/G5 remain open.

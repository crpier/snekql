# Recorded migrations: shared native version admission (#477)

Status: **bounded experimental G3 checkpoint**, not full metadata/environment prerequisites,
G4/G5 qualification or release approval. Follows
[inherited native strictness](recorded-migrations-native-strictness-review.md).

## One existing version guard, through owned I/O

Dedicated migration admission now calls the ordinary runtime's existing
`verify_mariadb_version` through the existing owned SessionSettingsProbe BEFORE native policy
settings or yield. Same MariaDB identity parser, same unchanged minimum10.11, same diagnostics;
no new parser/compatibility registry, Config knob or full ordinary initializer. Opening and
checked-out I/O budgets remain separate; version query/fetch/cursor close have ordinary owned
migration per-operation deadlines. Failure closes the owned candidate while retaining primary
error. Strictness/UTC/integrity policy and recorded exact version/mode/rendering profile remain.

Real RED uses ACTUAL MariaDB10.10.7: expecting pre-yield DatabaseRuntimeError got NO exception;
old target could apply unchanged literal001/accounts and create complete history under that
unsupported server. This is an admission-floor mismatch, NOT proof10.10.7 cannot execute that
specific SQL, a server defect, corrupt data or false completion. New guard refuses before
schema/data/history work and does not convert/upgrade/rewrite an earlier unsupported target.

Current diagnostic: `snekql requires MariaDB >= 10.11; connected server is 10.10.7`.
Same shared guard also refuses non-MariaDB/unidentified/malformed versions, but this checkpoint
does not claim a NEW real MySQL/fake-greeting qualification. Existing ordinary probe-unit
regressions remain, not evidence every matching version/build/feature is supported. Version
admission is a floor, not a readiness, codec, metadata privilege or maintained-matrix proof.

## Actual old-server environment, not injected driver behavior

The official10.10.7 linux-systemd-x86_64 archive is external-cache-only and verified against
its official SHA256 manifest. Server/install-db/client run from that actual installation;
normal aiomysql/current project interpreter, real server VERSION() and executable provenance.
No spoofed version/system variable/greeting, patched driver, fake migration step or mocked
server/probe in the new seam test. Owned temporary data/socket/skip-networking server only;
no OS server replacement or global library/config change. No repository dependency bump.

The old CLI needs real legacy libncurses5/libtinfo5; unpack official Debian6.4-4 packages into
external cache, verify their SHA256 against official Packages metadata, select via per-command
LD_LIBRARY_PATH. No system installation, fake symlink ABI or compatibility code in snekql.
Initial current13CLI/old-server readiness failed because current CLI required TLS and old
server did not offer it; real server was READY, independently SELECT VERSION worked with
explicit CLI disable-ssl. Correct fixture uses actual old CLI, NOT weakened Target TLS policy.
An initial snowman insert also exposed old server's default latin1: declare fixture directory
utf8mb4 explicitly. Both are SETUP feedback, not version-admission/runtime defects.

`test_migration_native_version.py` has one explicit environment selector for this ONE actual
negative installation: SNEKQL_TEST_MARIADB_10_10_7. Unset means normal installed-server positive
journey; set means run and ASSERT actual10.10.7 version/refusal. Same committed test source;
no optional silent successful skip, network download in tests, vendored executable or new
production interface. Full native suites run with selector UNSET; negative case has its own
completed normal/lazy reports. Selecting an environment does not inject migration-driver SQL.

## Public representative workflow

An independent real aiomysql observer creates an unowned InnoDB utf8mb4 directory/row7 with
non-ASCII data. Capture SHOW CREATE/data/process-list, load literal role001/002/003 unchanged.

- Actual below-floor server must refuse BEFORE yield/literal001 application. Only the directory
  exists afterward, actual SQL/data unchanged, no accounts/history/implicit adoption/repair;
  independent process-list snapshots show failed session gone, not every physical-close window.
  Ordinary initialization is deliberately NOT bypassed on old server for typed application use.
- Installed positive server runs literal001, normal typed flag rows1/2, literal002, ORIGINAL003
  saved BEFORE application; apply/repeat/sorted complete status/current typed1admin/2user/3user.
  ALL own earlier001/002 receipt columns and original package/prepared bytes remain unchanged.
  EVERY receipt's profile records actual observed VERSION(), not assumed version from CLI/path.
  Unowned directory SQL/data preserved. Mapping/ownership/readiness remain independent; no
  new author/model-removal, portable target/receipt identity or application fencing promise.

## Boundaries and remaining work

Status-only targets also require supported version admission. For refused environments use
suitable independent tooling; no old history stamping/conversion/replay or stronger receipt.
Caller must arrange explicit deployment on an admitted target, not reuse another target's
Prepared identity/evidence or infer all SQL/features supported from its reported version.
Existing native metadata, engine, negative authority and uncertainty/recovery gates remain.

G3 metadata visibility/privileges/other prerequisites, explicit end-to-end admission choice,
broader commit-outcome/shutdown/live-loop policy remain. Full metadata visibility/incompatible
writer exclusion are caller operational obligations, not automatic audits/locks. G4 maintained
LTS matrix/WAL active-backfill death/native lost-ack and G5 interface/ADR/coexistence/release
approval remain. Actual10.10.7 refusal is NOT positive10.11/LTS/upgrade/matrix qualification.
No new artifact/epoch/layout/parser/adoption/dependency/consumer-guide scope or release action.

## Completed local validation and actual archived comparison

- **926 normal +926 forced-lazy experimental**, **1,784 fast**, **128 focused normal +128 lazy**,
  all exit0/zero failures/errors/fixture/session teardown failures. Focused =previous112 +one
  installed-server version journey +fifteen existing ordinary settings/identity/version probe
  regressions. Those existing canned probes/fault-injection regressions are not new real-I/O
  qualification; new Target seam work uses actual servers, no new driver mocking.
- SAME committed version test explicitly selected actual10.10.7 in **separate normal1 +lazy1**
  completed tests, NOT counted as extra full-suite/matrix coverage. Default full native suites
  have selector UNSET/current13.0.2. Whole-tree ty/ruff/format/diff; native runs sequential/
  distinct external disk TMPDIRs/context-aware warnings, no silent skips/full-suite claim.
- **561** Python/program hashes stable through final suites/four fixed normal/lazy traces/two
  actual archived-runtime observations/exact committed-source readback. ALL **69** historical
  package/Prepared JSONs unchanged againstd2b48d9; **96** local links/unique changed Markdown
  list. External observer/archive source/module/interpreter and actual old executable/client/
  bootstrap/tar SHA provenance independently checked. Official10.10.7 tar SHA256:
  `821b143d4a0aeac05e7417810532e40015a0b6e7ca09a35d6f6e9384815e56c8`.
- Four fixed traces: actual/proc executable path/SHA match requested10.10.7 or installed13.0.2;
  failed-session disappearance independently observed, unowned directory DDL/data retained.
  Old-server migration session's actual general log contains ONLY SELECT VERSION() before
  refusal, no policy SET/DDL/lock/history work. General-log globals restored ACTUAL values in
  finally. Current-server ORIGINAL003/all own001/002 columns/package/plan bytes retained,
  every receipt profile records actual VERSION(), repeat/status/current typed1admin/2user/3user.
- ACTUAL archivedd2b48d9 via project interpreter/verified archive modules repeats both server
  environments. On actual10.10.7 it YIELDS, prepares/saves target-specific ORIGINAL001, creates
  accounts+ledger, returns applied/repeat already_applied/public complete001; exact old version
  recorded in its receipt, unowned directory retained. Installed13.0.2 already completes the
  full role journey/current typed use. Archive exit0=expected old-behavior observation, NOT a
  passing new floor policy or below-floor readiness/support promise. No data corruption/false
  completion/unsupported old-receipt upgrade; no cross-target Prepared/receipt comparisons.

Evidence: `.snektest/477-native-version/`, matching external-cache scripts/actual archive and
actual10.10.7 installation/client compatibility libraries. Initial TLS-readiness/latin1 setup
reports retained under `before-client-alignment/`; errors in fixture preparation are not a
migration runtime defect/qualification. Clean RED is `red-floor`, then `green-floor`; final
source never changed during completed qualifying runs. All download/development/final/trace/
archive runners finished, owned-server audit empty. Local Linux/GIL CPython3.15.0/default
asyncio/SQLite3.53.1/MariaDB13.0.2 plus selected negative10.10.7, NOT maintained LTS/upgrade/
MySQL/all-versions/every-feature/privilege/failed-close/shutdown/power-loss qualification.
Actions disabled/no CI requested/polled/awaited/claimed; no merge/tag/publication/release action.

## Bounded context-exit follow-through

The [context-exit checkpoint](recorded-migrations-context-exit-review.md) stops new/queued
admission, drains the active owner under a fresh acquisition budget, then closes. Failed or
cancelled drain discards connection without cancelling caller tasks or erasing the primary
error; actual blocked native/SQLite original-role journeys retain own evidence and explicit
recovery. Separate phase budgets are the candidate decision, not a cumulative package/context
timer. Remaining metadata/outcome/detached-cleanup/global shutdown and G4/G5 stay open.

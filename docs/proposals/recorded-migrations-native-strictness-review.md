# Recorded migrations: inherited native strict-mode admission (#477)

Status: **bounded experimental G3 checkpoint**, not complete native prerequisites, G4/G5
qualification or release approval. Follows
[positive bounded release](recorded-migrations-native-release-review.md).

## Move the existing InnoDB strictness prerequisite to entry

Previously only required-column alteration checked STRICT_ALL_TABLES or STRICT_TRANS_TABLES.
A dedicated native connection could yield under neither flag and begin data work before that
later gate. Real public RED: expecting admission DatabaseRuntimeError instead got the later
PackageError from original role003's required-column check. This is an earlier-admission gap,
not evidence the old required-column gate was absent or that role003 falsely completed.

Native admission now VERIFY-ONLY probes inherited sql_mode through the existing owned
SessionSettingsProbe/shared setting verifier before yielding, requiring EITHER strict flag.
The new private `_INNODB_STRICT_MODE_SETTING` is declared with backend settings and used BOTH
at admission and by the retained live required-column check. It has NO SET statements.
Ordinary initialization remains STRICT_ALL_TABLES normalization with its existing complete
required-mode predicate; no ordinary guarantee is relaxed. Its broader all-table policy and
this InnoDB-only migration prerequisite are deliberately distinct, not two generic runtimes.

Why STRICT_TRANS_TABLES is sufficient here: selected native managed tables must prove InnoDB;
transactional migration data work additionally rejects non-InnoDB tables, triggers and stored
routines in the current schema. Existing engine/observation/postcondition/uncertainty gates
remain. This is NOT a promise for nontransactional writes, external triggers/routines or every
mode-sensitive SQL expression. No NO_ENGINE_SUBSTITUTION admission guarantee is added; engine
postconditions remain live, version/metadata/other prerequisites still need separate policy.

No mode rewriting/flag insertion, GLOBAL repair, SQL rendering normalization or full ordinary
initializer. NO_BACKSLASH_ESCAPES, HIGH_NOT_PRECEDENCE, quoting/rendering/recovery facts stay
visible. UTC normalization and integrity verification continue unchanged on admissible sessions.
Unknown/empty/non-string mode fails closed. Shared diagnostic names sql_mode and expectation
`STRICT_ALL_TABLES or STRICT_TRANS_TABLES enabled (InnoDB migration work)`.

## Representative original-role journey

`tests/experimental/test_migration_native_strictness.py` uses real selected mapping classes,
literal001/002/003, normal typed flag rows1/2, ORIGINAL003 saved BEFORE caller mode change.
The independent real aiomysql observer owns no migration work and does not normalize settings.
It saves/restores ACTUAL GLOBAL mode in finally, not an assumed default.

Four named real-server cases:

- NO_BACKSLASH_ESCAPES alone and empty mode refuse BEFORE connect yields or role execution.
  All own earlier001/002 receipt columns and `(1,1,NULL)/(2,0,NULL)` remain, no003 receipt or
  implicit repair. Independent process-list snapshots show the failed opening's session is
  gone, not universal shutdown/failed-close/instant-physical-stop qualification.
- STRICT_TRANS_TABLES plus NO_BACKSLASH_ESCAPES and STRICT_ALL_TABLES plus that flag admit
  original003 unchanged. Every earlier receipt remains its OWN value; new003 observation
  records the exact inherited canonical session mode, not the ordinary initializer's mode.
- Restore actual prior GLOBAL; SAME original applies after refusal or returns already_applied
  after successful application. Sorted complete statuses, ordinary typed1admin/2user/3user,
  original package/prepared bytes retained. No new author/model removal or portability claim.

The existing encoded-default CHECK-removal regression now requests STRICT_ALL_TABLES PLUS
NO_BACKSLASH_ESCAPES rather than that rendering flag alone. Its original encoded-default
preservation purpose and production check/default/removal gates remain intact; safe earlier
admission refusal is not a runtime defect or a newly exercised post-DDL window. No driver
mocking, private helper tests, fabricated evidence/state patches or new migration callbacks.

## Boundaries and remaining work

Admission affects status-only targets too. Caller must explicitly select suitable native
policy; independent tooling remains available for unsupported sessions. New entry policy does
not repair earlier rows, rewrite receipts/old observations, upgrade historical certification,
automatically replay uncertain data or reconstruct an original plan. Prepared does not freeze
runtime Config or replace mode/rendering observation in the execution ledger.

G3 native version floor, metadata visibility/privileges and other prerequisite/outcome policy,
explicit end-to-end admission choice, broader shutdown/live-loop rules remain. Full metadata
visibility/writer exclusion remain caller operational obligations, not inferred audits/fencing.
G4 maintained finite matrix/WAL active-backfill death/native lost-ack and G5 interface/ADR/
coexistence/release approval stay open. No new artifact/epoch/layout/parser/adoption/dependency/
consumer-guide scope or release action. This is finite strictness admission, not complete G3.

## Completed local validation and actual archived comparison

- **925 normal +925 forced-lazy experimental**, **1,784 fast**, **112 focused normal +112 lazy**,
  all exit0/zero failures/errors/fixture/session teardown failures. Focused =earlier96 +four
  new strictness cases +twelve CHECK-removal regressions (earlier ordinary fault injection
  retained; no new driver/migration mocking). Whole-tree ty/ruff/format/diff; native runs
  sequential/distinct disk TMPDIRs/context-aware warnings. Not full-suite/matrix qualification.
- **560** Python/program hashes stable through final suites/eight fixed normal/lazy traces/
  four actual archived observations/exact committed-source readback. ALL **69** previous
  package/Prepared JSONs unchanged againsta50251c; **94** local links/unique changed Markdown
  list. External observer/archive source/module/interpreter provenance independently verified.
- Eight fixed traces retain ORIGINAL003/all own001/002 columns/packages, actual GLOBAL before/
  selected/restored mode, process-list snapshots after refusal, original-role sorted complete
  status/current typed1admin/2user/3user. Weak refusal leaves rolesNULL/no003; explicit caller
  restoration permits SAME original. Positive strict modes retain exact NO_BACKSLASH_ESCAPES
  profile in003, do not rewrite earlier observations, and repeat already_applied after GLOBAL
  restoration. Receipts/target plans compared to THEIR OWN prior values, never across targets.
- ACTUAL archivea50251c/project interpreter/verified archive modules repeats four setups with
  identical literal001–003. Both weak modes YIELD and commit both role UPDATEs before the old
  required-column gate refuses; actual rows1admin/2user with is_admin retained, raw003started/
  acknowledged2of3, public uncertain, blind original apply refuses inspect-before-recovery.
  No unsupported automatic replay/repair/resume; archived weak runs STOP uncertain. Positive
  strict modes already worked/retained exact mode and current typed use. Archived exit0 means
  expected old-behavior observation, not passing new weak-session policy. This proves a late
  refusal/partial acknowledged work, NOT false completion, corrupt data, unknown acknowledgments
  or absence/weakening of the old required-column gate. New admission avoids those effects;
  it does not retrospectively upgrade/convert/finish old uncertain history.

Evidence: `.snektest/477-native-strictness/`, matching external-cache scripts. Initial weak
RED expected DatabaseRuntimeError but got later PackageError. `before-admission-alignment/`
15pass/1error is the existing rendering-only test's SAFE earlier refusal before adding its
strict flag, not a runtime defect or final-source qualification. All final suites/traces reran
on unchanged final Python/program source. All development/final/trace/archive runners finished,
owned-server audit empty. Default asyncio/GIL CPython3.15.0/Linux/SQLite3.53.1/MariaDB13.0.2,
not maintained LTS qualification. Actions disabled/no CI requested/polled/awaited/claimed.
No general privilege/version/SQL-mode/readiness certification, failed-close/shutdown/all
cleanup/cancellation/native lost-ack/WAL active-death/power-loss qualification or release action.

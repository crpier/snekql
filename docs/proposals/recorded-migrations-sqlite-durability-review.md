# Recorded migrations: SQLite journal/synchronization policy (#477)

Status: **bounded experimental G3 checkpoint**, not power-loss/disk qualification, complete
G3 or release approval. Follows
[native integrity admission](recorded-migrations-native-enforcement-review.md).

## Explicit candidate policy

For dedicated file-backed migration targets, observe/admit and PRESERVE existing DELETE or
WAL. Do not issue PRAGMA journal_mode=WAL or silently convert a reviewed file. New ordinary
SQLite files begin in DELETE; an operator may explicitly select WAL separately. This follows
the proposed finite DELETE/WAL scope, not the ordinary application's WAL-only initializer.
Other observed file modes fail the shared setting verifier; no automatic conversion/fallback.
Only these local modes are exercised, not every unsupported-mode/build refusal path.

Apply AND read back requested Config.durability: NORMAL1 or FULL2, for the admitted connection
before yield. Share the SAME private synchronization-setting factory with ordinary SQLite
runtime, keeping its WAL/busy behavior unchanged. The migration target owns only journal
verification and synchronization selection here; existing FK/UTF-8 admission and native
integrity/UTC gates remain. Do not import the ordinary fixed5000ms busy setting: Config's
migration acquire_timeout still supplies the driver busy handler. Each query/fetch/cleanup
retains fresh owned per-I/O deadlines, after separately bounded physical opening; no cumulative
connect/package/context timer, new public flag/method/protocol/facade or generic runtime.

`:memory:` retains SQLite native journal/sync behavior, not a file durability certificate;
Config already rejects FULL for exact/path-spelled memory targets. File-sync policy is scoped
to each admitted connection, not copied to independent observer/application sessions. A later
ordinary Database.initialize can independently choose WAL, as before. The connect docstring
now states the dedicated-target divergence from ordinary Config's WAL runtime description.

Package/Prepared/ledger bytes/identities/epoch are not rewritten. Prepared is NOT a certificate
of physical storage durability or a frozen Config policy: runtime configuration is selected
by the caller of connect. Reopening with a different supported durability is a caller choice,
not inferred historical equivalence or a promise of old receipts. No old receipt is upgraded.
The prior connector ignored durability and happened to inherit FULL2 on this build; NORMAL now
really requests1 rather than accidentally remaining2. That deliberate behavior change is not
a durability upgrade. FULL requests SQLite synchronization and still depends on filesystem/
storage honoring it; neither readback nor successful COMMIT certifies host/volume/power loss.

## Public TDD and actual connection observation

`test_migration_sqlite_durability.py` loads unchanged literal role001/002/003, applies001,
seeds normal typed flag rows, and has an INDEPENDENT owned SQLite connection explicitly choose
DELETE or WAL. Apply002, create an unowned settings_audit table and real AFTER UPDATE trigger
that SELECTs built-in pragma_synchronous/journal_mode/busy_timeout table-valued PRAGMAs.

Those engine values are evaluated by the ACTUAL migration UPDATE session, NOT an observer's
connection setting, a private production helper assertion, fabricated receipt/step or injected
driver. The trigger is trusted SQL/explicit caller-owned preservation, not an extension to
migration callbacks or new trigger/partial-adoption support. Save ORIGINAL003 with explicit
preserve_unmanaged, apply/repeat/sort complete status, retain trigger through contraction, and
observe three real updates (row1 initial user, row2 user, row1 admin). Independent audit sorted
by id contains row1 twice/row2 once with requested sync, selected journal and200ms busy wait.
ALL own earlier001/002 receipt columns/values remain; original plan/package bytes unchanged.
Normal current app reads1admin/2user/inserts3user afterward; its own WAL choice is separate.

First clean RED under DELETE/NORMAL observed2 instead of requested1. Initial audit multiplicity
expectation mistakenly assumed only two updates and was corrected BEFORE implementation; the
clean RED still differs only in sync2/1. Minimal shared NORMAL passed, then FULL cases exposed
that temporary implementation's missing selection (1 instead of2) in both journals. Sharing
actual ordinary FULL/NORMAL construction passed all four combinations. That incremental FULL
failure is not evidence the PRE-FIX shipped connector downgraded FULL; it had incidentally2.
Static Iterable materialization was authoring cleanup, not a runtime defect. No data loss,
false completion, existing FULL corruption or power-loss defect is established by these REDs.

## Remaining work and limits

This establishes candidate journal/sync admission, NOT G4 WAL active-backfill death or disk
failure qualification. Existing DELETE interruption evidence remains finite. Failed/stalled
policy/readback/close windows, every SQLite build/filesystem and unsupported journal modes are
not all qualified. Timeout/cancellation is not physical quiescence; retained cleanup still
needs a live loop. Caller excludes incompatible data/schema writers through recovery/readiness;
readback is not fencing or metadata/codec/business/data-validity proof.

Remaining G3 native version/strictness/metadata privileges, explicit end-to-end admission
choice and positive release/commit-outcome/shutdown/live-loop rules stay open. G4 maintained
matrix/WAL active-death/native receipt-loss windows and G5 interface/ADR/coexistence/release
approval remain. No historical conversion/repair/replay/stronger certification, new epoch/
ledger field/parser/adoption/dependency/consumer-guide scope or merge/tag/publication.

## Completed local evidence and actual archived comparison

- **918 normal +918 forced-lazy experimental**, **1,784 fast**, **93 focused normal +93 lazy**,
  all exit0/zero failures/errors/fixture/session teardown failures. Focused =earlier70 +four
  new policy combinations +nineteen existing ordinary SQLite durability regressions (including
  their pre-existing fault-injection tests, not new migration-driver injection). Ordinary WAL,
  FULL/replacement/failed verification behavior retained. Whole-tree ty/ruff/format/diff pass.
- **558** Python/program hashes stable throughout final sequential/distinct-TMPDIR native
  suites/eight normal/lazy fixed traces/four actual archived traces/commit readback. ALL **69**
  previous package/Prepared JSONs unchanged against3fc5874; **87** local engineering links
  checked across a unique list of all changed Markdown files. Observer program/archive/module
  provenance separately verified; no new committed artifact/epoch/layout or dependency.
- Eight final-source traces retain ORIGINAL preserving003, all own prior001/002 receipt columns,
  trigger SQL before/after, actual three-update sync/journal/200ms audit, selected DELETE/WAL
  after migration BEFORE app initialization, sorted complete status and current typed app.
  Descriptor absence independently observed before fresh original already_applied admission.
  Original/package bytes unchanged; no cross-target plan/receipt comparison or adoption claim.
- ACTUAL archived3fc5874 through project venv Python/verified archive module paths executes
  SAME literal role chain/retained trigger in four normal-import cases. Both NORMAL requests
  observe2 instead of1, while FULL happens to observe2 as requested. Journals/200ms/typed app/
  receipt retention already work there. This isolates the old ignored-setting mismatch; no
  claim of old data loss or FULL downgrade. Archived exit0 means expected-defect observation,
  not passing new policy. Nothing repairs/relabels/replays old accepted work or upgrades receipts.

Evidence: `.snektest/477-sqlite-durability/`, matching external-cache scripts. All validation/
trace/archived runners finished; owned-server audit empty. Local default asyncio/GIL
CPython3.15.0/Linux/SQLite3.53.1/MariaDB13.0.2, NOT maintained matrix/build/filesystem or power-
loss qualification. Actions maintainer-disabled: no CI requested/polled/awaited/claimed.
Remaining G3/G4/G5 limits above remain; no all-policy-failure/failed-close/WAL active-death/
power-loss/native lost-ack/shutdown/full-suite qualification, consumer guides or release action.

## Positive bounded native release follow-through

The [native release checkpoint](recorded-migrations-native-release-review.md) tracks acquired
coordination scopes and positively drains ONLY that native advisory name within a fresh
release-control operation budget. Actual server bootstrap recursion no longer leaks ownership;
primary refusals survive, unrelated names remain owned, and postcommit release expiry closes
the target without undoing acknowledged receipts. Fresh ORIGINAL evidence observes already_
applied after independent session disappearance. No cumulative package clock or automatic
replay. Remaining native prerequisites/admission/outcome/shutdown policy and G4/G5 stay open.

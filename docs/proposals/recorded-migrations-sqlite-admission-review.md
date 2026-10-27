# Recorded migrations: SQLite encoding/FK admission (#477)

Status: **bounded experimental G3 checkpoint**, not complete journal/durability/runtime
integration or production/merge/release approval. Follows
[native UTC admission](recorded-migrations-native-utc-review.md).

## Decision and actual RED

A dedicated SQLite target now applies AND verifies the same foreign_keys/encoding policy
values used by ordinary runtime connections before yielding. The previous connector sent
PRAGMA foreign_keys=ON without readback and never checked encoding. A real existing UTF-16le
file was admitted despite the shared UTF-8 requirement: the RED expected DatabaseRuntimeError
but no error occurred. This is an admission-contract gap, NOT observed corruption, codec loss,
false migration completion or proof that SQLite itself cannot read UTF-16. The unsupported
file remains usable by independent SQLite; the library does not convert it or adopt its data.

Reuse the existing SQLite connection-setting declarations and existing private migration
SettingsProbe, through Target._query with fresh owned cursor/execute/fetch/close deadlines.
Select ONLY foreign_keys and encoding. Do not run the whole ordinary SQLite initializer:
its fixed5000ms busy_timeout would overwrite the reviewed migration acquisition budget, and
its WAL/NORMAL configuration would silently choose the still-unresolved migration journal/
durability policy. No new flag/public method/adapter protocol, generic runtime, automatic
retry, file conversion or compatibility framework. This extends the real existing shared
policy seam, not a parallel initializer.

Admission happens AFTER bounded physical opening and BEFORE yield; no whole-connect/package/
context/cumulative timer. A setting failure reports the existing DatabaseRuntimeError naming
the setting, expected value and observed value. Existing context-owned close preserves the
primary error and observes cleanup; interrupted admission uses existing unsafe disposal.
No objects/history are created during admission. Only FOREIGN KEY enforcement is enabled;
encoding is verify-only, not an implicit file rewrite. No namespace/model ownership follows.

## Representative public workflow

`tests/experimental/test_migration_sqlite_admission.py` uses real existing SQLite files and
public connect/prepare/apply/status/normal typed queries:

1. Independent owned SQLite creates a UTF-16le or UTF-16be file with unowned directory data
   including non-ASCII text. Observe actual encoding and retain complete file bytes.
2. Public m.connect refuses BEFORE yielding with encoding/UTF-8 diagnostic. After cleanup,
   file bytes match exactly; independent reads retain original directory schema/data, with no
   ledger/managed table. No fabricated state/history or private driver/helper assertion.
3. The caller explicitly selects a DIFFERENT UTF-8 target, not a converted/repaired/relabelled
   original. Apply unchanged literal role001, normal typed seed1/2, literal002 and saved
   ORIGINAL003 contraction. Apply/repeat, sorted complete statuses and normal typed app
  1admin/2user/insert3user work. Packages/original plans remain unchanged. Models stay present;
   this is not new model/author-source removal evidence or transfer/adoption of directory.

The little-endian RED preceded the minimal shared-policy implementation; big-endian coverage
then repeats that same contract. Removing an unused lint suppression is authoring cleanup,
not another runtime defect. Foreign-key SET already existed; new behavior is its readback and
encoding admission, not a claim that every earlier migration lacked FK enforcement.

## Boundaries and remaining effort

- Same local SQLite build/default asyncio/Linux; no every-encoding/build/OS/filesystem or failed
  setting/readback/close/window qualification. Existing shared declaration/probe validation is
  reused, not a claim to have forced every admission failure. A caller deadline is not proof
  the physical worker stopped; cleanup/live-loop limits from prior checkpoints still apply.
- Existing busy-handler acquisition budget remains untouched; native UTC/mode evidence is
  unchanged. No migration journal/synchronous change, no inference that Config.durability is
  honored, and no WAL active-death/power-loss/storage-stack claim. Normal app use may switch
  the valid target to WAL later; that is not migration journal-policy qualification.
- Current admission can refuse previously admitted unsupported files, including read-only
  status access through m.connect. No compatibility conversion, history stamping or repair.
  Independently inspect unsupported files with suitable external tooling/caller policy.
- G3 native version/strictness/enforcement/metadata admission, SQLite journal/durability,
  explicit end-to-end acquisition choice, positive lock-release/commit-outcome/shutdown/live-
  loop policy remain open. G4 finite matrix/failure windows and G5 interface/ADR/release/coexistence
  approval remain. No parser/adoption/dependency/consumer-guide expansion or release action.

## Completed local validation

- **910 normal +910 forced-lazy experimental**, **1,784 fast**, **43 focused normal +43 lazy**,
  all exit0/zero failures/errors/fixture/session teardown failures. Focused = earlier37 +two
  encoding cases +four real ordinary SQLite connection-setting regressions. Native suites
  sequential/distinct external TMPDIRs/context-aware warnings; whole-tree ty/ruff/format/diff.
- **556** Python/program hashes stable across final suites/four normal/lazy standalone traces/
  commit readback; ALL **69** historical package/Prepared JSONs unchanged againstc266d1a;
  **81** local engineering links. No new package version, epoch, ledger field or literal.
- Four final-source standalone little-/big-endian traces in normal/lazy interpreters retain
  actual before/after file SHA/bytes, encoding/UTF-8 refusal BEFORE yield, unchanged directory
  schema/non-ASCII data, no ledger and independently observed descriptor disposal. Descriptors
  are observed, not an assertion that every kernel worker/close-failure window is qualified.
- Explicit DIFFERENT UTF-8 target then loads all three original role packages, saves ORIGINAL003,
  applies/repeats, retains ALL prior001/002 receipt columns/values against OWN earlier values
  and package/plan bytes, sorts complete statuses and performs ordinary typed1admin/2user/3user.
  No directory adoption/data transfer/implicit conversion is performed or inferred. The ordinary
  app later uses WAL; that is not new migration journal/durability/crash evidence.

Evidence: `.snektest/477-sqlite-admission/`, matching external-cache scripts. An initial trace
observer key ambiguously said worker/descriptors although only descriptors were observed;
those reports are retained under `before-observer-label/`, final traces reran with the precise
label. This audit-label correction is not a runtime defect; production/test source unchanged.
Final native/trace runners finished; owned-server audit empty. Local Linux/default asyncio/GIL
CPython3.15.0/SQLite3.53.1/MariaDB13.0.2, not maintained-version qualification. Actions remain
maintainer-disabled: no CI requested/polled/awaited/claimed. No full-suite/matrix/all-admission-
failure/failed-close/WAL active-death/power-loss/native lost-ack/shutdown qualification or
merge/tag/publication. Remaining G3/G4/G5 decisions above remain open.

## Native integrity admission follow-through

The [native integrity checkpoint](recorded-migrations-native-enforcement-review.md) verifies
shared foreign_key_checks/check_constraint_checks/unique_checks1/ON prerequisites before
native Target yield. It does NOT implicitly enable disabled settings or repair GLOBAL state;
UTC remains the sole native normalization, preserving actual SQL-mode/rendering/recovery
facts. Real disabled-default refusals preserve original role plans/earlier receipts/data;
explicit caller restoration permits original work. Version/strictness/metadata, journal/
durability, remaining outcome/shutdown policy and G4/G5 remain open, not implicitly qualified.

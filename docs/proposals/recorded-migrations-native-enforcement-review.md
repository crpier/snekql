# Recorded migrations: native integrity admission (#477)

Status: **bounded experimental G3 checkpoint**, not full native/session/version/metadata
admission or production/merge/release approval. Follows
[SQLite encoding/FK admission](recorded-migrations-sqlite-admission-review.md).

## Decision and real REDs

Before yielding a dedicated native target, VERIFY inherited foreign_key_checks,
check_constraint_checks and unique_checks against the SAME1/ON declarations used by ordinary
native connections. Unlike the ordinary pool initializer, this is VERIFY-ONLY: strip apply
statements from those existing immutable setting values, then run the shared verifier through
the existing target-owned SettingsProbe. A disabled prerequisite refuses with the established
DatabaseRuntimeError naming the setting/expected1/observed0. No implicit enabling, GLOBAL
repair or claim that an older receipt met these prerequisites. UTC remains the sole normalized
native setting; actual SQL modes/rendering/recovery evidence are not overwritten.

The initial real CHECK RED admitted a session inheriting GLOBAL check_constraint_checks=0
and executed original role003, instead of refusing before yield. Minimal CHECK admission then
passed. FK/unique cases independently failed with the same missing-refusal behavior, then the
same shared verify-only selection extended to those prerequisites. This proves an admission
contract gap, not by itself that every disabled flag always bypasses every native constraint.
In particular unique_checks=0 is not a promise that this engine/build accepts duplicates.

Physical opening, local guard/backend coordination and per-I/O budgets remain separate. These
probes run AFTER opening's acquisition scope and BEFORE yield, through the existing owned
cursor/execute/fetch/close deadlines/unsafe disposal. No cumulative/whole-connect clock, new
public option/method, generic runtime, alternate adapter protocol or automatic retry. Existing
context-owned close preserves the primary admission failure. No object/history creation at
admission. Status-only Target access also requires admitted session policy; external suitable
tooling may be needed for unsupported settings. Caller chooses a suitable server policy; the
library never changes GLOBAL state on their behalf.

## Public workflow and retained gates

`tests/experimental/test_migration_native_enforcement.py` uses unchanged literal role001/002/
003 and explicit normal typed flag rows1/2. Save ORIGINAL003 before changing an OWNED server's
GLOBAL prerequisite. Each of three named cases saves/restores the actual previous value in
finally; no other server/config touched. Under0, m.connect refuses BEFORE yield/apply, while
GLOBAL0 and SQL mode stay unchanged. All prior001/002 receipt columns/values and actual rows
(1,1,NULL)/(2,0,NULL) remain intact. Ordinary app access still applies its own session policy
without repairing GLOBAL defaults. No new003/history, inferred replay or fabricated state.

After caller restores its own prior GLOBAL policy, fresh admission applies the SAME original
003, repeats already_applied, sorts complete status, and ordinary typed app reads1admin/2user/
inserts3user. Packages/original plan bytes unchanged; no reprepare/recompile/automatic repair.
Models stay present; this is not new model/author-removal evidence. Caller still excludes
competing schema/incompatible affected-data writers; these checks are not fencing/readiness.

The earlier CHECK-addition and index-removal disabled-default tests now expect stronger
admission-time refusal rather than reaching prepare on unsupported sessions. They retain all
ledger columns and the invalid existing CHECK row-1 with no repair, saving/restoring ACTUAL
prior GLOBAL values instead of assuming1. Four old development-suite errors were these safe
earlier refusals, not new unsafe execution. Final validation reruns after aligning the tests.

Three synthetic missing/view/non-InnoDB reference tests depended on executing migration DDL
with FK checks disabled. Their execution path is now refused at admission; replace them with
FOUR real selected-child/unowned-parent cases (missing/view/MyISAM/MEMORY), not hand-built
states. Under admitted policy the actual engine rejects CREATE, leaves child absent and
uncertain ack0 (never complete/finish), retains ORIGINAL evidence and refuses blind replay.
Missing/view can inspect retry_remaining0; non-InnoDB obstacles remain ambiguous. These are
stronger entry/engine refusals, NOT new execution of the superseded weak-session post-DDL
observer window. Existing native catalog/reference-parent/storage/negative checks and their
other regressions, per-operation CHECK-addition and index-removal guards remain in place; no
production gate is weakened/deleted to make admission pass.

## Boundaries

Not all build/engine/privilege variants or failed/stalled probe/close/cancellation windows are
qualified. Readback verifies session flags, not arbitrary triggers/routines, all external
writers, existing data validity or every physical key/FK prerequisite. No retrospective data
repair/receipt upgrade, blanket success from constraint presence, universal unique_checks=0
behavior or new target portability guarantee. Native version floor/strictness/metadata
visibility/privileges, SQLite journal/durability, end-to-end admission choice and positive
release/commit-outcome/shutdown/live-loop policy remain G3 work. G4 finite matrix/WAL active
backfill death/native lost-ack windows and G5 interface/ADR/coexistence/release approval remain
open. No parser/adoption/dependency/consumer-guide expansion or merge/tag/publication.

## Actual constrained-data witness and archived counterfactual

A separate visible program selects a real CheckedAccount model over the unchanged role chain,
adds004 `ck_role_allowed` excluding `'banned'`, and freezes005 typed UPDATE assigning that
forbidden role to row1. It saves ORIGINAL005 BEFORE execution. This is deliberate invalid
reviewed data work that should be rejected by the declared engine CHECK, not a mocked step,
fabricated receipt or assertion that type checking proves all business constraints.

- With an ACTUAL archive of9e17c08 and the project venv interpreter/verified archive module
  paths, the SAME004/005 package bytes under owned GLOBAL check_constraint_checks=0 execute
 005, return applied/already_applied and record complete. Stored row1 is `'banned'` despite the
  declared CHECK; row2 remains user. This establishes a real CHECK-bypass/data-integrity
  consequence beyond the initial refusal RED. Engine behavior under disabled checks is not
  itself a server defect; admission failed to require the library's integrity prerequisite.
- Current code refuses BEFORE yield/005 work, retaining admin/user, all prior001–004 receipt
  columns/values against OWN prior values and no005 receipt. It does NOT silently enable the
  flag. Restore OWN actual prior GLOBAL value in finally. Explicitly trying the SAME original
 005 under admitted policy then raises real native4025 `ck_role_allowed`, retains rows/prior
  receipts, records started/ack0 (public uncertain), and ORIGINAL inspect reports
  retry_remaining0. Do NOT replace/repair the original or automatically replay invalid work.
- Actual package digests:004 `90d2ca26e717fa49329ebb7848c8fff3212a63d75bef7ef48f2b8840fd51e1b7`;
 005 `075d6b8b08c032dada5d0368908e225bb6fbe9f5e5c085aacfa9dd783e46359f`.
  These are observed workflow outputs, NOT new committed compatibility references or a new
  epoch. No cross-target receipt/plan hash comparison; compare each target only to ITSELF.

No old incorrect data is repaired/relabelled/replayed, no old receipt strengthened, and no
universal duplicate/FK-bypass behavior inferred from this CHECK witness. Models stay present;
no new source-removal evidence. The archived trace's exit0 means expected-defect observation
completed, not passing fixed workflow. Executable packages remain trusted, not sandboxed.

## Completed final-source local evidence

- **914 normal +914 forced-lazy experimental**, **1,784 fast**, **70 focused normal +70 lazy**,
  every exit0/zero failures/errors/fixture/session teardown failures. Focused = earlier43 +seven
  new native policy/reference cases +nine CHECK-addition +eleven index-removal cases. Native
  suites/traces sequential with distinct external TMPDIRs/context-aware warnings; whole-tree
  ty/ruff/format/diff. No full-suite or maintained-version matrix claim.
- **557** Python/program hashes stable through final suites/six normal/lazy admission traces/
  current and actual archived data witnesses/commit readback; ALL **69** prior reference JSONs
  unchanged against9e17c08; **85** local engineering links. External observer-program hashes
  and archive/source provenance verified separately. No new committed artifact/epoch/layout.
- Six final-source traces save ORIGINAL003, independently observe actual process-list session
  absence after refusal, retain ALL own001/002 receipt columns/values and actual flag/NULL
  rows after refusal, preserve actual NO_BACKSLASH_ESCAPES in EVERY receipt, restore OWN saved
  globals and apply SAME original on fresh admission; typed1admin/2user/3user and repeat/status
  work. Session-absence polling is a finite observation, not a universal physical-stop deadline.

Evidence: `.snektest/477-native-enforcement/`, matching external-cache scripts; final/trace/
archived runners finished, owned-server audit empty. Initial development normal909passed/
4safe earlier-refusal errors and earlier focused reports are retained under
`before-admission-alignment/` and EXCLUDED after test source changed; every final suite reran
unchanged. Earlier errors are expectation/policy alignment, not new unsafe-execution defects.
Local GIL CPython3.15.0/default asyncio/Linux/SQLite3.53.1/MariaDB13.0.2, not LTS qualification.
Actions remain maintainer-disabled: no CI requested/polled/awaited/claimed. Remaining G3/G4/G5
limits above hold; no all-admission-failure/metadata-privilege/failed-close/WAL active-death/
power-loss/native lost-ack/shutdown qualification, consumer guide or merge/tag/publication.

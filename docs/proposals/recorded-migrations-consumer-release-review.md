# Recorded migrations: consumer docs and candidate packaging (#477)

Status: **consumer/release documentation and local candidate packaging complete**
(2026-10-27). This follows the [accepted bounded G5 contract](recorded-migrations-g5-decision-review.md),
not a new architecture, stable namespace, release version, merge, or publication decision.
The existing draft PR remains the review vehicle.

## Consumer contract and retrieval

- [Recorded workflow](../recorded-migrations.md): ordinary historical declarations,
  named generated query bindings, editable typed backfills, frozen packages and
  build freshness, then model-free target preparation/original persistence/apply,
  then separate ordinary application verification and typed reads/writes.
- [Recorded recovery](../recorded-migration-recovery.md): original target-bound
  evidence, durable progress versus caller acknowledgement, explicit native
  inspection/reconciliation/resume, SQLite transactional outcomes, primary-error
  precedence, and bounded per-lifetime cleanup with live-loop supervision.
- Preserve `snekql.experimental.migrations`, finite support/exclusions, historical
  codec obligations, and independent mapping/ownership/readiness. No new facade,
  migration callbacks, generic parser, library CLI, supervisor, or timeout knob.
- Keep raw-SQL guides and APIs supported unchanged. Navigation and the bundled
  skill first identify the runner family; separate deployment targets remain a
  caller policy, not a universal mixed-history detector or conversion facility.
- Curate Unreleased notes into the current consumer contract. Earlier prototype
  chronology remains in git history and the engineering reviews, rather than
  presenting superseded restrictions as release instructions.
- Release instructions reflect maintainer-disabled Actions and human-controlled
  publication. No workflow/YAML, dependency, lockfile, version, tag, or publishing
  change is made. Do not claim local builds produced distribution attestations.

## Actual installed consumer recipe

The four linked reading-resource inputs are
[staging](../../examples/recorded_role_stage.py),
[typed authoring](../../examples/recorded_role_author.py),
[original storage](../../examples/recorded_plan_store.py), and
[current application](../../examples/recorded_application.py).
Consumers generate two actual historical query modules; formatted in-checkout
previews allow repository static checking, but are not required deployment inputs.
Use a fresh consumer workspace as instructed, not a scaffold over deployed history.

The installed-wheel test copies those resources outside the checkout and asserts
that the imported library lives under the isolated installed environment. It:

1. Generates/imports real historical bindings, compiles backend-specific packages,
   and runs the documented non-rewriting freshness check.
2. Uses `ty --python <installed interpreter> --error all` on the copied sources;
   an actual wrong-type assignment fails, and a typed intent edit makes the frozen
   package stale without changing any package bytes.
3. Deploys 001, seeds visible old-model rows, removes authoring inputs, and deploys
   002 without importing authoring/current application models.
4. Saves original plans before apply using off-loop private file flush/fsync,
   atomic non-replacing publication and directory fsync. An existing original is
   refused, not overwritten. Every earlier ledger column and the earlier original
   retain this target's own values; no cross-target receipt comparison is used.
5. Joins retained lifetimes and independently uses current ordinary models to
   verify structure, insert `(3, "user")`, and read admin/user/user. This is a
   selected smoke journey, not complete application readiness or a power-loss test.

## Completed stable-source evidence

Evidence: `.snektest/477-consumer-docs/`; external runners are cache-only. Program
freeze: **577 files**. All **136 production Python modules**, the build hook,
`pyproject.toml`/version and `uv.lock` are byte-identical to G5 commit `ba30094`.
All **69 prior historical artifacts/program references** remain unchanged.

| Current check | Completed result |
| --- | --- |
| Packaging/resource/installed tests | 25 normal + 25 forced-lazy; zero failures/errors/teardown failures |
| Installed recipe exact environments | 12 cases/12 environment-mode rows: SQLite 3.45.1/3.53.1 and MariaDB 10.11.19/11.4.13/11.8.9/12.3.3, each normal/all |
| Fresh experimental suites | 956 normal + 956 forced-lazy; zero failures/errors/teardown failures |
| Fast suite | 1784; zero failures/errors/teardown failures |
| Static/build inputs | ty, Ruff lint/format, generated-overload check, lock check and diff check pass |
| Existing isolated artifact script | Exact byte-equal script/input copies outside the checkout; normal/lazy import/CLI/runtime/typing and two real native driver tests pass |
| Built archives | Wheel, sdist and rebuilt wheel inspected; 61 documentation resources (46 Markdown, 15 recipe sources), including both guides and four new recipe inputs |
| Rebuild identity | Wheel rebuilt from sdist has the exact same SHA-256 as the candidate wheel; skill/resources/runtime bytes match inspected inputs |

Native rows retain actual VERSION and `/proc` executable/hash, matching the
previously verified cache builds. SQLite rows report the installed interpreter's
actual SQL engine version. Forced-lazy mode is propagated/asserted in consumers;
no production environment selector, download, fake ABI shim, or silent skip.

Earlier G5's 216-case runtime matrix and selected physical interruption/loss
windows remain evidence for their unchanged runtime/fixture inputs; they are
**not** counted as new runs here. Current new recipe cases and broad suites have
their own completed reports. Normal/lazy native work runs sequentially.

Development RED/probe reports remain retained. The initial matrix attempt failed
before execution because an overly long external TMPDIR exceeded MariaDB's Unix
socket pathname limit; its report is in `before-long-socket-tmp/`. A shorter,
disk-backed operator TMPDIR fixed setup, with no repository program/runtime
change; the entire 12-row recipe matrix then completed. No runtime corruption
claim, manufactured bug, or retrospective archive comparison is made.

## Candidate identity and authority

Archive hashes, exact provenance, report summaries and source/readback manifests
are retained with the evidence. Metadata deliberately remains **0.9.0**. These
local candidates are **not** a claim about the already published 0.9.0 artifacts
or guides, and must not be published under that existing version. The user's
prior `dist/` artifacts are not replaced; candidate output is isolated.

Documentation/packaging follow-through is complete for review. Selecting a
release version/branch, satisfying the complete release checklist, merging,
tagging, publishing, stable-namespace promotion, or converting an existing raw
history still requires separate authority. Actions were not requested/polled.

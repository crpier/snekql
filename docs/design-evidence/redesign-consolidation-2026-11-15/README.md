# Redesign consolidation — 2026-11-15

The maintainer required **one ongoing redesign issue (#603) and one draft PR (#609)**.
The separately opened #606/#608/#610/#612 and #607/#611/#613 were unnecessary work
queues. This cleanup consolidates their actual work into #609, preserves their
original context and retires the redundant pairs without merging them. Separate
migration PR #476 and unrelated work are not part of this cleanup.

## Preservation before closure

- **44 changed-file snapshots** across source PRs #607 (18), #609 (4), #611 (19)
  and #613 (3). Each original file is stored at `<PR>/<original-path>.txt`, adding
  exactly one suffix. No changed path was deleted at these heads.
- `<PR>/pr-metadata.json` preserves each pre-consolidation PR body, head/base commits,
  changed-file list, comments and reviews. The captured OPEN states are historical,
  not a claim that redundant PRs remain open. #609's snapshot is its earlier head,
  not the consolidated branch's current head.
- `issues/606.json`, `608.json`, `610.json`, `612.json` preserve complete pre-closure
  descriptions, comments, assignees and metadata. `tracking-603-before.json` preserves
  the surviving umbrella's description/comments before its cleanup rewrite.
- [manifest.json](manifest.json) records source PR/commit/path, archive path and
  SHA-256 for every snapshot. All 44 were checked byte-for-byte against the original
  git blobs and rechecked after consolidation.

The original branches are retained. Their commits are also recorded here; source
preservation does not depend on an old PR remaining open. Snapshot bytes are not
rewritten to fit later design decisions. Historical bodies or proposals cannot
override the [current checkpoint](../../design-checkpoint.md).

## Consolidated working material

The original research commits were cherry-picked onto #609, followed by the latest
contract/decision documents. Both experiments remain isolated under `research/`,
with their two focused static harnesses under `tests/experimental/`. No overlay was
applied to production `snekql/` and no runtime/API change is implied.

The shared `research/__init__.py` had only a docstring conflict; the existing
bounded-experiment wording was retained. Both original versions are archived.
Current documents were reconciled so that the accepted ordinary SQL nullable
default supersedes the earlier annotation-inference recommendation. No new design
choice was made during cleanup.

Current entry points:

- [Checkpoint](../../design-checkpoint.md): decisions, remaining questions and workflow.
- [Declaration comparison](../../declaration-design-sheet.md): historical rationale;
  its earlier SQL assumptions are explicitly superseded by the accepted contract.
- [Default/nullability contract](../../default-nullability-contract.md): accepted
  nullability rule and remaining migration recommendations.
- [Decimal capability report](../../../research/decimal_capabilities_606/README.md):
  conditional evidence and known failures, not a sound completed capability system.
- [Split-default typing report](../../../research/split_defaults_610/README.md): narrow
  static feasibility; copied bodies do not implement the new argument.

## Retirement and workflow

[retirement.json](retirement.json) records the verified GitHub closures and redirect
comments. PRs #607/#611/#613 are CLOSED with no mergedAt; issues #606/#608/#610/#612
are CLOSED as NOT_PLANNED because their queues are superseded, not because APIs
were implemented. #603 and draft #609 stay open. No branches were deleted.

Both isolated harnesses were replayed together after consolidation: 18 checks passed.
Repository ty, Ruff lint/format, whitespace and local documentation links were checked.
This is not a new runtime/database proof; the Decimal overlay's known unsoundness,
bypasses, regressions and copied-package diagnostics remain explicit in its report.

Continue discussion, bounded investigations, decisions and later authorized edits
in this same issue/PR pair. Do not create another issue or PR for each redesign step.
Cleanup does not authorize production implementation, merges or unrelated closures.

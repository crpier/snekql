# Complete changed-file snapshots of retired research drafts

The maintainer authorized consolidating the nine related research drafts into #604
and closing those drafts, without merging their experimental code. This archive
preserves **all 90 files listed as changed** across #539, #583, #592, #594, #595,
#597, #598, #600 and #602 at the recorded heads, plus each PR's metadata/body.
The separate migration implementation PR #476 is not part of this retirement.

These are historical source snapshots, not current usage instructions, selected
interfaces, supported test modules or patches applied to production. The current
position is in the [design checkpoint](../../design-checkpoint.md); the
[inventory](../../design-research-index.md) explains superseded conclusions.

## Layout and verification

- `<number>/pr-metadata.json`: live metadata captured before closure, including title,
  URL, OPEN state, exact head/base commits, PR body and changed-file list. Its OPEN
  field describes the pre-retirement snapshot, not the current PR state.
- `<number>/<original-path>.txt`: exact bytes of that changed file at the head commit.
  One `.txt` suffix is added even when the original filename already ended in `.txt`.
- [manifest.json](manifest.json): PR, commit, original path, archive path and SHA-256
  for every file. All 90 were verified against both manifest hashes and original git
  blobs before retirement.
- `issues/`: pre-closure bodies, comments and metadata for completed research/documentation
  issues #588, #590, #593, #596, #599 and #601. These preserve their original bounded
  deliverables and claims separately from any later implementation work.

No changed path was deleted at these heads, so there is no omitted deletion payload.
Overlapping files are intentionally preserved per PR, rather than silently combining
incompatible research branches. This is about half a megabyte of source, not nine
copies of the complete repository or virtual environment.

## Reproduction boundaries

These snapshots preserve the complete *changed-file set*, not every dependency or
base repository file needed to run it. To reconstruct a historical experiment, use
the recorded git revision and its own instructions, or restore original paths into
a disposable checkout with compatible dependencies. A restored artifact should match
its manifest hash exactly; remove only the archive's final added `.txt` suffix.

Do not restore all PR directories over one another. Their reports describe different
baselines and some intentionally accepted errors, incomplete signatures, rejected
policies or abandoned generators. The files remain text so normal project test/type
checking doesn't collect expected-error examples or execute historical policies.
The small #595/#602 fixtures in the parent evidence directory remain convenient entry
points; this archive is the complete fallback rather than a replacement specification.

No historical runtime/backend suites were rerun during archival, and closure means
research is superseded by consolidation—not that a proposed feature was implemented.

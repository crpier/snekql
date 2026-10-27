# CLI subprocess resource markers — 2026-10-27

Refs #572 / #536. Second bounded slice of the marker audit; neither issue is
completed. Independent of unmerged #586 (typing-marker work); no merge authorized.

## Revision and scope

Fetched main `3ed75324bbb12b189470f296e55faddf63d72b5b` includes #585's two new
pure insert cases. Candidate: `a906d7b782f28e50745de018a5ee81fcd2cfc3f2`. The subsequent report commit is
contributor documentation/evidence only.

The SSH agent refused a GitHub signing request. Fetch used the repository URL
queried through `gh` and an ephemeral gh HTTPS credential helper; no repository
remote or global authentication configuration was changed. This does not affect
source provenance or grant merge/publication permission.

Only **11 decorator literals** change `fast` → `slow`, covering **13 expanded
cases**:

| File | Changed definitions / cases | Cold permitted resources |
| --- | ---: | --- |
| `tests/test_docs_cli.py` | 9 / 11 | Real Python CLI processes; copied quick starts execute SQLite in child interpreters. Their source fixture reads README/getting-started or invokes agent-docs CLI. |
| `tests/test_runtime_selection.py` | 1 / 1 | A fresh Python process asserts optional backend runtime modules/drivers are not imported. The parent process is not a substitute. |
| `tests/testing/mariadb/test_cli.py` | 1 / 1 | Real Python CLI help. No native server starts, but the Python subprocess alone requires slow. |

No subprocess, example execution, type check, assertion, fixture, parameter, name,
property budget, default discovery, backend behavior or initialization contract
is removed/rewritten. No SDK, dependency, lock, runner/framework or workflow
change. No cached CLI stdout or fake parser/import environment substitutes for
cold execution.

Two deliberately retained fast controls construct/resolve config objects and
reject invalid/ambiguous inputs **in process**. Paths are values; neither opens
the database nor calls `initialize_runtime`. Native password-announcement/SIGINT
cases stay slow and byte-identical; existing docs type/copy-execution slow cases
also stay unchanged. Do not relabel an entire directory or equate “MariaDB” in a
name with actual server startup.

## Approved seam and red → green

Continue the previously confirmed public snektest file/node filters, `--mark`
and JSON-report seam. It observes routing and complete named execution, not an
OS resource sandbox or comprehensive dynamic resource proof. Resource truth
comes from reviewing the bodies and transitive fixtures. No new seam or
framework internals, maintained checker or recursive default-suite test.

One producer at a time: run the real fast group and reject its wrongly present
cases; change only its decorator; rerun fast with both pure controls healthy;
execute its exact cold named slow group, including all three source variants of
`documented_quick_start_runs`. Existing assertions pass on the routing-red side:
the failing independent expectation concerns selection, not a product defect.

| Same three-file inventory | Before | After |
| --- | ---: | ---: |
| Unfiltered unique names | 23 | 23 |
| Fast | 15 | 2 |
| Slow | 8 | 21 |

The two final fast names are independently specified, not inferred from current
labels. Fast/slow groups are disjoint and their union is exactly the unchanged
23-name set. AST and git audits separately establish body/parameter preservation
and no other pre-existing tracked-input changes at the executable candidate.
No production implementation-shape assertion is introduced.

To avoid same-sized edit/timestamp bytecode alias, every proof deletes only the
three owned test modules' pyc files and sets `PYTHONDONTWRITEBYTECODE=1`. Child
processes inherit that setting; source and product behavior are not patched.

## Calibration

In an owned private worktree at the executable candidate, the two calibrated
faults leave the selected cases passing but violate the independently specified
two-name fast contract:

| Private marker fault | Actual passing fast names | Routing expectation |
| --- | ---: | --- |
| Restore `docs_cli_prints_agent_docs` to fast | 3 | Reject the extra subprocess producer |
| Demote `runtime_config_resolution_returns_backend_configs` to slow | 1 | Reject the missing healthy in-process control |

The other pure control stays healthy under both faults. After each fault the
original source bytes are restored and the two-case fast group passes. An
independent cold named docs-CLI slow case passes after restoration. All three
test modules restore byte-for-byte; no live SDK or live test input was mutated.
The private worktree and owned temporary roots are removed after inactivity
checks. These are routing-oracle calibrations, not detected product defects or
a repository-wide mutation score.

## Fresh candidate validation and inventory provenance

- **4,269 fresh candidate full ordinary cases passed**; wall 353.181 s (validation context only).
- **23 affected parent forced-lazy cases passed**; wall 5.539 s (validation context only).

Zero failed/error/function/session teardown counts, empty stderr and clean frozen
source. Complete unfiltered inventory has **4,269 identical unique names** versus
the verified historical reference. Exactly **13** metadata entries change fast →
slow; every other case marker remains identical. The 23 parent-forced-lazy names
and markers match the ordinary affected group.

Typing, Ruff, formatting (635 files), generated-interface, lock, whitespace,
source-preservation and raw/archive integrity checks pass. Owned validation and
calibration directories are checked inactive, zero-byte uv-lock remnants accounted
for and removed; existing caller-owned reusable MariaDB data remains untouched.

Historical reference: #585's prior full report, not another execution by this
session. Its raw report, stderr and source snapshot match hashes published in
`docs/test-suite-reviews/2026-10-27-insert-compilation.json`. All **455 recorded
source paths** match this slice's frozen base; the three intentional candidate
marker edits are compared against their original bytes. The historical report
is used **only for name/marker comparison**, not borrowed candidate validation,
matched timing or a new baseline correctness claim.

This new candidate's own full normal execution establishes current correctness.
No other suite/build by this session runs concurrently. Temporary storage is a
private owned `/dev/shm` directory, unlike #586's Btrfs capture. The mount has
`usrquota`, and no `quota` utility is available: recorded free bytes and memory
are not per-UID quota/headroom guarantees. No mount/quota settings change. A
successful completed run qualifies only its actual workload, not all capacity
or future runs. Source remains frozen; normal signals and startup
`PYTHON_CONTEXT_AWARE_WARNINGS=1` apply.

**No marker speedup or cross-storage timing comparison.** This change removes no
unfiltered work. The #585 run on another session, #586 timings and this run are
not a matched benchmark. Parent forced-lazy mode does not imply that child CLI,
quick-start or checker interpreters inherit `-X`. No full forced-lazy, remote
matrix, native-release, long-duration or release qualification is claimed.

## Focused feedback and omissions

- `tests/test_runtime_selection.py --mark fast`: exactly two in-memory config
  controls; does not prove optional driver imports are absent in a fresh process.
- `tests/test_docs_cli.py --mark slow`: all 17 docs cases, including copied
  SQLite examples and checker subprocesses. No native MariaDB server required.
  Does not replace other typing batches or native execution/lifecycle coverage.
- Named optional-import check with `--mark slow`: actual cold interpreter,
  not observations of an already warmed parent's module registry.
- Named MariaDB CLI help with `--mark slow`: parser/output only. The complete
  MariaDB CLI file runs two additional real native-server/password/SIGINT cases
  and requires MariaDB tools. Never call the help case a native startup test.
- All three files unfiltered: 23 cases, preserving the complete original group.
  All remain included in default `snektest tests`; no marker exclusions by default.

Commands are in `docs/contributing.md` and exact argv/provenance/raw reports are
in the [checksum packet](2026-10-27-cli-resource-markers-data/README.md).

## Remaining audit and CI

#586's typing-marker slice remains separate/unmerged. No relabeling of native
medium fixtures, threaded SQLite, source-reading or unmarked tests is bundled
here; their cold paths still need reviewed follow-up. Global fast is **not** yet
certified resource-pure. Some marker counts are definitions, others expanded
cases; do not interchange them.

The prior initial CI overlap map remains documentation-only. Do not use slow as
a backend selector, omit shared/runtime native cases, drop platform/import-policy
coverage or enable/wait for intentionally disabled Actions. No workflow or
compatibility coverage changes, dependency/tool/action upgrade or new runtime
optimization. Migration/declaration work and #571 ownership remain separate.

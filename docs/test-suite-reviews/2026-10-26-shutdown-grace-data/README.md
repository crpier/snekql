# Shutdown-grace evidence — 2026-10-26

See [findings](../2026-10-26-shutdown-grace.md). Library defaults are unchanged;
this is a test-only public-context / real-POSIX-process / isolated-clock slice.

## Provenance

- Baseline: `63a6c72f0c66a26b2cb5e0aac534aa07a4a7de7d`.
- Clean executable candidate: `9422d1206508c6ea1f57de5aa70946282482871e`.
- `inputs.json`: preliminary environment, native-helper/source/lock hashes.
- `validation.json`: candidate source hashes, post-capture installed/native
  versions and exact static-check commands. Native binaries were observed on
  this host; this is not native-version matrix qualification.
- `source-audit.json`: every other named lifecycle test/control definition is
  AST-identical; all library and dependency files are unchanged.

## Raw evidence map

| Files | Meaning |
| --- | --- |
| `baseline.json`, `before-*` | Earlier unchanged uv-command observations; not the matched direct-interpreter sample |
| `red-missing-probe.*` | Initial parent integration test fails before the probe exists; not a library-defect reproduction |
| `matched.json`, `matched-[1-8]-*` | Exact commands, interpreter, clean revisions, startup environment, private TMPDIRs, load snapshots, case inventories, wall/case times, raw reports and statuses; B/A then A/B |
| `calibration.json`, `mutant-*` | Three intentional library-source faults in private copies; all rejected |
| `restored-green.*` | Copied library restored byte-for-byte and focused test passes |
| `watchdog-calibration.json`, `watchdog-*` | Probe KILL delivery withheld; actual watchdog rescue rejected; deliberate omission of its assertion makes a false positive pass; all restored afterward |
| `repeated-probes.json` | 20 ordinary and 20 direct forced-lazy independent OS/clock outcomes |
| `lazy-file*` | Complete 19-case forced-lazy parent-runner validation, not inferred child `-X` coverage |
| `cpu-quota-*` | Additional owned 5%-CPU scope correctness check after matched captures |
| `validation-*.stdout`, `validation-*.stderr` | Static/format/lock/diff command output |

The `watchdog-guard-omitted` **pass is a deliberate false-positive calibration**,
not successful helper cleanup. The direct rescued observation explicitly has
`watchdog_fired: true`; all its other success fields match. The restored test
requires that flag to be false. No mutant source is part of library/test code.

Original source/capture scripts are retained as `*.py.txt` for provenance, not as
a second maintained runner/checker or additional test discovery scope. They ran
from the checkout using the same absolute interpreter recorded in `matched.json`.
Before worktree and temporary native data are no longer needed to inspect the
raw results. The private calibration script copies package/test sources before
mutation and restores them after each fault. Local preliminary development
artifacts, including the superseded mutation of both waits, were retained outside
the repository and are not substituted for the calibrated first-wait mutation.

Temporary directories contained only owned processes/data; captures ran serially
with no concurrent suite/build by this agent. Other host/agent activity was not
isolated. Full-file timings are noisy and **do not demonstrate a speedup**; do not
combine preliminary and matched samples or extrapolate the focused result to the
whole suite. Default discovery still includes all 19 names; the changed subprocess
case correctly moves from `medium` to `slow`.

## Verify integrity

From this directory:

```sh
sha256sum -c SHA256SUMS
```

`SHA256SUMS` covers all other packet files, including empty stderr files; it does
not recursively hash itself. This packet and its findings are documentation only
and do not supersede the executable candidate's revision identity.

# CLI resource-marker evidence — 2026-10-27

[Findings](../2026-10-27-cli-resource-markers.md). Refs #572 / #536.

The executable candidate changes only 11 marker literals / 13 expanded cases.
Bodies, parameters, controls, default scope, SDK, dependencies and workflows are
unchanged. The final report commit is documentation/evidence only.

## Map

| Files | Meaning |
| --- | --- |
| `start.json`, `source-audit.json` | Fresh base/branch, SSH-to-ephemeral-HTTPS fetch note, exact marker-only preservation |
| `routing-tdd.json` | Eleven producer-specific wrong-routing reds / fast greens / cold named slow runs; unchanged 23 names, final 2 fast / 21 slow |
| `routing-calibration.json` | Three-name wrong-fast and one-name wrong-slow selections rejected by literal two-name oracle; restored sources/controls/cold CLI |
| `full-normal.json.gz`, `full-validation.json` | This session's fresh candidate 4,269-case ordinary run; exact name equality and only 13 expected marker differences |
| `cli-parent-forced-lazy.*` | This session's actual 23 affected parent-forced-lazy cases; not a claim about child interpreter flags |
| `upstream-full-normal.json.gz`, `upstream-full-source.json`, `upstream-provenance.json` | **Historical #585 inventory reference only**, byte/hash verified against its committed report; 455 recorded source hashes match frozen base, not a new baseline/candidate validation |
| `cli-transcripts.tar.gz`, `transcript-manifest.json` | Byte-preserving focused/TDD/fault/restored/static stdout/stderr plus actual one-off scripts; not default tests or a maintained policy engine |
| `static-validation.json` | Exact typing/lint/format/generated/lock/whitespace commands and statuses |
| `snektest-metadata.txt.gz`, `snektest-help.txt` | Installed authoritative marker meanings and public options |
| `environment.json`, `storage-preflight.txt`, `quota-readonly.txt` | Local environment/free-space/memory observations; usrquota enabled, no quota utility; not quota-headroom guarantees |
| `archived-reports.json` | Original full-report/METADATA bytes and hash plus gzip hash; origin/scope distinguishes current and historical captures |

Routing-red selected cases pass their original assertions. The separate routing
expectation rejects subprocess consumers still labeled fast. Both deliberate
marker faults likewise have passing CLI reports but rejected name sets. No
product defect is claimed and no live SDK/test source contains a calibration
fault. Empty-group success cannot satisfy the independently specified controls.

Marker-only edits can retain source size/timestamp, so proof commands clear only
the changed modules' owned pyc and disable bytecode writes. Source restores
byte-for-byte. Original CLI invocations and body assertions are not replaced.

Historical reference raw bytes were **copied read-only**, never mutated in the
other session's evidence directory. They are not this session's baseline run,
not fresh candidate validation and not a performance reference. This candidate's
fresh ordinary and affected forced-lazy commands are separate actual executions.

Validation uses owned tmpfs directories, normal signals and startup warning
context. Quota/mount settings are untouched. Successful observed workload is not
a guarantee of capacity, future headroom or uniqueness of physical allocation.
No concurrent suite/build by this session; unrelated host work remains unisolated.
No speedup or cross-storage timing comparison, inferred child flags, full forced-
lazy, remote matrix, native release or long-duration qualification.

The wider marker audit remains open. Global fast is not yet resource-certified;
slow is not a backend selector or OS sandbox. Intentionally disabled Actions and
all workflow/matrix/tool/dependency behavior remain unchanged.

## Integrity

```sh
sha256sum -c SHA256SUMS
gzip -cd full-normal.json.gz
gzip -cd upstream-full-normal.json.gz
tar -tzf cli-transcripts.tar.gz
```

Manifest covers every other packet file. Gzip decompression reproduces original
bytes/hashes in `archived-reports.json`, including METADATA's trailing blank line.
`transcript-manifest.json` checks each relative archive member and empty stderr.
Scripts stay inside the archive as provenance, not added default-suite discovery.

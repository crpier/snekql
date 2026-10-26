# Native-data copy evidence — 2026-10-26

See [findings](../2026-10-26-native-data-copy.md), #570 / #536 / PR #575.

## Source identities

- Baseline: `c7aee1611fdcef7c6ef92ffcf6489596fd7daa8b`.
- Clean executable candidate: `45441ad` (full identity/source hashes in `copy-static.json`).
- Subsequent report commit is documentation/evidence only. No library, defaults,
  application fixture, dependency/lock or migration changes.

## Evidence map

| Files | Scope |
| --- | --- |
| `inputs.json`, `environment.json` | Unchanged source/lock/package/binary environment and phase-diagnostic provenance |
| `baseline.json`, `before-*` | Earlier unchanged 16-case password / 9-case public-module commands, not the matched comparison |
| `phases.json`, `phase-summary.json`, `phases.py.txt` | Representative public reset/connect/real-replay/verify/close workflows; six instrumented samples and 18 actual replays |
| `red-data-copy.stdout.gz`, `.stderr`, `.status` | Raw non-JSON stdout collection failure before helper module exists; not a library-defect reproduction |
| `green-*` | First integration green and later restored guard greens |
| `copy-source-audit.json` | All four CLI cases' function AST unchanged; 12 Python parameterization/markers and original assertions unchanged |
| `copy-calibration.json`, `fault-copy-*` | Live seed, overwrite, symlink alias and hard-link faults, each rejected in private source copies; includes exact mutant text/hashes and inactive artifact accounting |
| `fault-copy-logs/*` | Byte-preserving gzip native logs retained before deleting inactive failed owned data; raw hashes/paths in calibration metadata |
| `copy-matched.json`, `copy-matched-[1-8]-*` | Clean B/A then A/B complete-file and single-node captures: commands, interpreter, cases, status, load and raw hashes |
| `copy-validation.json`, `full-normal.json.gz`, `native-forced-lazy.*`, `copied-restored.*` | Full ordinary 4,245-case validation; all 87 helper cases in forced-lazy parent; restored three-case source copy |
| `copy-diagnostic*` | Separate actual 12-case group observes one direct native installer, 25 helper-launched native servers and 12 independent copies; not an uninstrumented benchmark |
| `copy-static.json`, `copy-static-*` | Candidate source/package/native-version identity and exact static/lock/format/diff results |
| `archived-reports.json` | Compressed full report/nonempty stderr transcripts, with exact original byte sizes and SHA-256 values |
| `preliminary-selector-error.log` | Capture-script selector error before any command launched; corrected from the real named inventory and excluded |

The initial CLI collection error was printed as rich text to a filename originally
reserved for JSON; it is archived as raw stdout, not parsed or labeled as a valid
JSON test report. Its trailing whitespace is preserved byte-for-byte in gzip.

Scripts are retained as `*.py.txt` for provenance, not additional default test
discovery, a second checker framework or a new maintained runner. The source copy
used for fault calibration is restored; no mutation is in normal tests/library.
Case failures are protection evidence, never passing optimization measurements.

## Interpretation

- Whole-file comparisons retain the same original **16 cases**, including four
  cold CLI cases, and account for session setup/teardown. They do not include the
  three newly added default-scope regression cases. Full ordinary validation does
  execute all three. Do not extrapolate a full-suite percentage improvement.
- The batch file improves, **but the one-case cold command regresses in both
  pairings**. Copying/storage and the extra native seed start/stop are deliberate
  tradeoffs presented for review, not a guarantee of faster narrow feedback.
- Normal signals, startup warning context and fresh private Btrfs TMPDIRs. No
  concurrent suite/build by this agent during timing/validation captures; other
  host/agent work, frequency, caches and filesystem activity were not isolated.
- Per-case runner times can charge session setup to its first consumer and omit
  fixture teardown. Use matched command wall times, not inferred phase subtraction.
- The instrumented phase sample and cache-use check are separate from the clean
  uninstrumented timing commands. `st_blocks` can count COW-shared extents more
  than once; these are not unique physical bytes or quota-headroom estimates.
- Process counts observe the helper's direct subprocess launches, not descendants
  created internally by the native installer; no total process-churn claim.
- Forced-lazy helper validation exercises the new Python helper in its parent
  interpreter. Python subprocess CLIs do not automatically inherit `-X`.
- One unpaired normal full run is correctness evidence, not a new comparative
  full-suite baseline, remote matrix pass or release certification. Actions stay
  intentionally disabled. No merge/release/publication is implied.

## Integrity

From this directory:

```sh
sha256sum -c SHA256SUMS
```

The manifest covers every other packet file, including gzip bytes and empty
stderr. To inspect the complete report without changing bytes:

```sh
gzip -cd full-normal.json.gz
```

`archived-reports.json` verifies uncompressed size/hash, including the raw full
report hash referenced by `copy-validation.json`. The calibration manifest also
records raw native-log hashes; decompression reproduces those bytes exactly.

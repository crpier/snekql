# Typing resource-marker evidence — 2026-10-27

See [findings](../2026-10-27-resource-markers.md). Refs #572 / #536.

The executable candidate changes exactly 15 marker literals; no new default
tests, assertions, parameters, fixtures, budgets, library/dependency/workflow or
runner changes. The subsequent report commit is documentation/evidence only.

## Evidence map

| Files | Meaning |
| --- | --- |
| `source-audit.json`, `inventory-inputs.json` | Frozen base input hashes and exact marker-only AST preservation |
| `routing-tdd.json` | 15 sequential wrong-routing reds, fast greens and cold named-slow runs; final 61-name/8-fast/53-slow partition |
| `routing-calibration.json` | Private wrong-fast producer and wrong-slow pure control each rejected by routing oracle; restored 8/61 passes |
| `full-validation.json`, `full-{before,after}.json.gz` | Two actual complete default 4,267-case ordinary runs; exact unique-name equality and only the 21 expected marker differences |
| `typing-forced-lazy.*` | Actual 61-case parent forced-lazy run; not inferred to force child checker imports |
| `cli-transcripts.tar.gz`, `transcript-manifest.json` | Byte-exact focused/TDD/fault/restored/static stdout and stderr, plus preliminary failures; no hundreds of extra default test files |
| `main-profile*` | Fresh frozen-main local ranking; setup/teardown/reusable-data and host-activity limits are explicit |
| `initial-inventory.json`, `initial-definition-index.csv`, `inventory.py` in the transcript archive | All recognized decorated definitions and conservative call signals; source-review candidates, not an automatic resource proof |
| `snektest-metadata.txt.gz`, `snektest-help.txt` | Installed authoritative resource semantics and public CLI options |
| `environment.json`, `actions-permissions.json` | Local interpreter/native/storage snapshot; read-only confirmation Actions is disabled |
| `static-validation.json` | Exact static/generated/lock/format commands and statuses |
| `archived-reports.json` | Original full-report/METADATA byte size/hash and gzip hash |

Scripts are retained byte-for-byte inside the transcript archive for
reproducibility, not a maintained policy engine, second checker framework or
additional default-suite discovery. Raw
focused and full reports remain distinguishable from routing expectation results.

## Interpretation and retained errors

- Existing cases pass on the routing-red side. The independent selection
  expectation rejects checker consumers in fast; this is not a typing defect
  reproduction or a fabricated failed test count. The literal eight-case set is
  independently specified, not inferred from current marker labels.
- Both private fault CLI commands pass their selected tests but produce a wrong
  name set (nine or seven). The routing oracle rejects that selection. Restored
  source passes. The SDK/live test bodies never contain a mutation.
- `preliminary-bytecode-calibration/` in the transcript archive preserves the
  unusable restoration capture that read timestamp-valid stale bytecode after a
  same-sized marker edit. Final calibration clears only owned changed-module pyc
  and disables writes. `preliminary-routing-driver-error.log` happened on a
  fixture decorator before any command/source change; neither preliminary error
  is qualifying routing or product-defect evidence.
- Normal before/after are **scope/correctness**, not a runtime experiment. The
  before owned worktree starts with absent explicit reusable MariaDB data; the
  candidate checkout already has reusable data. No speedup follows from walls.
- Case-time sums can charge session setup to a first consumer and omit fixture
  teardown. Profile rankings are prioritization leads, not native phase proofs.
- No other suite/build was launched by this agent during captures; unrelated
  host/agent work, filesystem caches and CPU frequency were not isolated. Normal
  signals and startup `PYTHON_CONTEXT_AWARE_WARNINGS=1` apply.
- The wider marker audit remains open, including IO/thread/subprocess consumers
  still mislabeled elsewhere. Global marker filtering is not an OS sandbox or a
  backend-only selector. All checks remain in default unfiltered discovery.
- No Actions triggering/enabling/waiting, matrix coverage removal, tool/action
  upgrade, full forced-lazy suite or new remote/native-version qualification.

## Integrity

```sh
sha256sum -c SHA256SUMS
gzip -cd full-before.json.gz
gzip -cd full-after.json.gz
tar -tzf cli-transcripts.tar.gz
```

The checksum manifest covers every other packet file. `archived-reports.json`
checks original full-report/METADATA bytes; `transcript-manifest.json` checks each raw
archive member, including empty stderr. Archive members have safe relative names.

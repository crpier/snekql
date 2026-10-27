# Batched distinct typing probes — 2026-10-26

Tracking: #562 under #536, following static sharing in #560 / #561.

## Change and coverage mapping

The 80 nested-expression and 22 temporal cases retain their distinct expressions,
expected diagnostic rules, independently named tests, backend parameterizations,
`slow` markers, and six per-case diagnostic assertions. Each still requires a
clean positive control, exactly one negative diagnostic, the expected rule and
marked location, and conformance. These inputs are **not redundant** and are not
replaced by observations from the normal static assessment.

The checker CLI now accepts explicit manifests. Every request gets independent
positive/negative files; one real ty assessment handles each immutable group.
`tests/typing_variants.py` holds the original challenge declarations and two
ordinary session fixtures. The two dynamic test modules no longer import their
copied-checkout fixture from another test module. There is no persistent cache,
second runner or new parallel-test setting.

Previously repeated aggregate-exit checks move to two new group-completeness
checks in `tests/test_typing_batches.py`. They require actual successful CLI exit,
exact declared identity/backend sets, matching cardinality, aggregate conformance
and no unmapped errors. Named lookups require exactly one matching observation,
retain isolated views and do not turn another variant's nonconformance into a
healthy variant's failure. Infrastructure and unknown-scope errors remain global
failures, not invented per-case successes.

All 51 challenge declarations were compared with the originals. For all **102
backend/variant pairs**, actual rendered positive and negative source hashes were
verified against the original templates and source-construction expressions.
The diagnostic parser, checker configuration/invocation, environment collection
and report schema are unchanged. Normal static selectors and filenames remain
compatible; source/configuration mutation tests still run independently.

## Equivalent-command measurements

From main's `4ad6564543580e91fda16852964947cc4b14e7d5`, before source changes:

```sh
PYTHON_CONTEXT_AWARE_WARNINGS=1 uv run snektest \
  tests/test_nested_expression_families.py tests/test_temporal_typing.py \
  --json-output
```

| | Before run 1 / 2 | After run 1 / 2 |
| --- | ---: | ---: |
| Named cases passed | 102 / 102 | 102 / 102 |
| Command wall seconds | 36.428 / 34.048 | 1.135 / 1.139 |
| Mean wall seconds | 35.238 | 1.137 |

Every run had zero failures, errors or fixture/session-teardown failures and the
same named case inventory. The observed mean reduction is **96.8%**, approximately
**34.1 seconds for this unchanged command**. The new 14 batch-protocol and
completeness cases are additional default-suite coverage outside this timing
command, not replacements for its 102 cases.

Measurements used the same interpreter, locked tools, input templates and warning
setting on a nonexclusive workstation. Two sequential before samples followed by
two after samples are not an interleaved statistical benchmark or timing gate.
Per-case durations charge session setup to the first consumer and exclude
runner-managed teardown; command wall time is authoritative.

**No whole-suite percentage speedup is claimed.** Full runs below validate a
larger inventory and variable native setup costs; their wall times must not be
subtracted from older full-suite records as a controlled performance comparison.

## Focused behavior and cold-start tradeoff

Existing named selectors work. A cold named test prepares only its own group's
batch, not the static or other dynamic group's report:

| SQLite sample | Before wall seconds, two runs | After wall seconds, two runs |
| --- | ---: | ---: |
| Nested `eq_col` | 0.561 / 0.487 | 0.798 / 0.810 |
| Temporal `raw-datetime` | 0.453 / 0.447 | 0.515 / 0.509 |

Mean additional cold setup was approximately **0.28 seconds** for the nested
sample and **0.06 seconds** for the temporal sample. Before focused measurements
restored the original CLI and two consumers from the fixed base, then restored
all working files in `finally`. No source mutation ran during final full tests.

For the smallest checker request, `--manifest requests.json --name NAME
--backend sqlite` selects a specific pair. The [contributor guide](../contributing.md#explicit-checker-batches)
describes the manifest, independent paired sources, name/backend uniqueness,
filtering, exact-diagnostic responsibility and 0/1/2 exit semantics. Existing
`--case` / `--backend` static commands remain available. The entire assessment
retains its 90-second deadline.

## TDD and meaningful faults

- Red/green feature slices cover explicit manifest execution, duplicate request
  rejection, and focused name/backend selection. Further CLI cases retain
  malformed/empty input, incompatible mode and expected-marker error protection.
- A real-ty mixed batch includes one healthy variant, a polluted positive control
  and a missing rejection on the **same backend**. Aggregate exit is 1 while
  lookup preserves each variant's actual evidence and the healthy one remains
  conforming. Existing lookup checks retain missing/duplicate/unmapped protection.
- A controlled request-builder omission leaves a conforming but incomplete
  batch. The new completeness check fails, rather than accepting fewer probes.
- A controlled replacement of each negative with a different valid rejection
  still conforms at its marked line. The original named `eq_col` rule assertion
  fails. Batch conformance has not replaced the specific diagnostic protection.
- Both request-builder mutations were restored before measurements and complete
  validation. Failed intermediate integration attempts are retained locally but
  are not counted as successful validation.

## Complete local validation

The frozen code/test tree passed **194 typing/support cases normally and with
forced lazy imports**. Complete suite runs passed **4,187 cases normally** and
**4,187 with forced lazy imports**, both with zero test or fixture/session-teardown
failures. Their inventories match: all 4,173 prior cases remain, plus the 14 new
batch cases. Wall times were 413.777 and 455.337 seconds, recorded as validation,
not a full-suite speed comparison.

The same private short tmpfs root was used without deletion between the two full
commands. Each left only the same zero-byte uv lock, with no MariaDB or typing
artifacts. The root was removed after recording contents and confirming no live
owned processes. Caller-owned reusable database data was not swept.

A separate **direct `python -X lazy_imports=all` checker CLI** run assessed all 102
inputs and verified each exact rule, count, location and positive control. This
is direct CLI evidence, not an inference from the runner flag propagating into
subprocesses. Strict typing, lint, formatting and generated-interface checks
passed. GitHub Actions is disabled by the maintainer; all validation was local,
not certification of a remote platform/database matrix.

[Machine-readable evidence](2026-10-26-dynamic-typing-batches.json) records commands,
source/report hashes, environment, input/assertion mappings, focused timings and
full results. Raw reports are retained at
`/home/crpier/.cache/sq-dynamic-typing-V2hURzpc` (pointer:
`/tmp/snekql-dynamic-typing-latest`).


## Main integration before merge

Main subsequently merged #563 (`6891bfc`), adding two end-to-end attribution and
focused-selection proofs. Its only conflict was contributor prose; both guides
and all new tests were retained. The feature's five code/test source hashes are
unchanged. All **196 affected typing/support cases passed normally and with
forced lazy imports**, including both new proofs; strict typing, lint, formatting,
generated-interface and whitespace checks passed. The earlier 4,187-case full
runs remain pinned to the pre-integration tree; no fresh 4,189-case full run is
claimed. Integration reports and hashes are retained with the existing evidence.

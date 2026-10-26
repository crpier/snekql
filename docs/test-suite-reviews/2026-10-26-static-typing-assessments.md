# Shared static typing assessments — 2026-10-26

Tracking: #560, under #536. This follows the artifact-ownership work in #542.

## Scope and interfaces

Sixty compatible static checks now consume one real `--case all` report through
`tests/typing_assessment.py::provide_typing_assessment`, a runner-managed session
fixture. They keep independently named tests and their positive-control,
negative-count, rule, location and backend checks. Sharing is confined to one
runner execution; there is no persistent cache or alternative runner.

The approved seams are the existing checker CLI/JSON report using real ty, and
the shared lookup by case/backend. `TypingAssessment.cases()` requires exactly
one observation per requested case/backend and returns isolated copies. A
nonconforming case does not poison a healthy unrelated observation; the actual
aggregate exit status remains available and is checked by the full-report test.
Infrastructure failures and unmapped diagnostics cannot become vacuous success.

Nine existing static cases still execute independently through the CLI:
selected lifecycle/backend coverage, report metadata, explicit configuration,
missing input, three source mutations, and help. Mutation tests keep their
baseline and modified invocations. Source/configuration changes never borrow a
normal shared result. The 80 nested-expression and 22 temporal variant cases
are unchanged and continue to run their distinct probes.

## Controlled timing comparison

Both before runs and both after runs used the same interpreter, locked tools,
CLI/probe inputs, warning-context setting and command, on the same nonexclusive
workstation. The comparison source base is `2f442c8`; this change modifies only
the static test consumers and introduces their support module/tests. Input and
checker sources were verified unchanged. There were no retries hidden in the
successful counts.

```sh
PYTHON_CONTEXT_AWARE_WARNINGS=1 uv run snektest \
  tests/test_typing_compatibility.py tests/test_typing_guarantees.py \
  tests/test_nested_expression_families.py tests/test_temporal_typing.py \
  --json-output
```

| Scope | Cases | Before run 1 / 2 (s) | After run 1 / 2 (s) |
| --- | ---: | ---: | ---: |
| Complete four-file command, wall time | 171 | 44.57 / 49.02 | 31.92 / 32.76 |
| Static files, summed case durations | 69 | 15.22 / 16.89 | 2.24 / 2.45 |
| Unchanged nested/temporal files, summed case durations | 102 | 29.13 / 31.90 | 29.47 / 30.10 |

All four commands passed the **same 171 named cases**, without test errors,
failures or fixture teardown failures. Mean command wall time went from
**46.79 to 32.34 seconds**, an observed **30.9% reduction**. The static-file
reported-duration reduction is approximately 13.7 seconds; the unchanged
variant tests remain the dominant typing cost.

Wall time is authoritative. As in the original baseline, per-case durations
charge fixture setup to its first consumer and exclude runner-managed teardown.
The nearly zero standalone assertion time in `test_typing_guarantees.py` does
not mean its checker coverage disappeared: its setup was charged to the other
static file's first shared consumer.

This is a two-sample local comparison, sequential before then after, not an
interleaved statistical benchmark or timing gate. Host contention remains a
limitation. **No full-suite percentage speedup is claimed.** The nine new
lookup cases are additional coverage outside the unchanged 171-case timing
command; the full runs include them.

## Focused-run tradeoff

The existing named-test and checker CLI selectors remain available. A cold named
static test prepares the all-case report once, while the direct CLI can still
check only a selected case/backend:

```sh
uv run snektest 'tests/test_typing_guarantees.py::public_typing_contract_has_exact_diagnostic[select-all]'
uv run python scripts/check_typing_compatibility.py --case select-all --backend sqlite
```

For that named test, repeated wall times were **0.429 / 0.442 seconds before**
and **0.531 / 0.549 seconds after**: approximately 0.10 seconds more cold setup.
Before measurements temporarily loaded the original base-revision consumer at
the same path, restoring it afterward; CLI, inputs, interpreter and command were
otherwise identical. This tradeoff is explicit rather than presented as a
focused-run speedup.

## Protection and fault-injection accounting

- Existing test names, markers and parameterizations were preserved. The
  diagnostic assertions remain, with selected observations replacing per-test
  process execution. Repeated aggregate-success assertions move to the real
  full-report result; no synthetic per-case exit codes are manufactured.
- Nine new cases protect named/backend selection, missing observations,
  duplicates, view isolation, unavailable assessment evidence, unmapped errors,
  and a real-ty mixed healthy/broken-backend assessment.
- The real-ty fault probe adds an incompatible backend Config assignment to a
  private lifecycle template. The aggregate fails, MariaDB's control is broken,
  and SQLite's independently clean positive control and expected negative
  remain identifiable through lookup.
- A completeness hole was exposed: replacing `raw-closed` with a duplicate
  `metadata-readonly` entry in the CLI registry still produced 124 conforming
  observations and passed the intermediate count-only full-report check.
  Completeness now derives expected case/backend pairs from actual positive
  probe inputs, checking missing/extra pairs and cardinality. The same mutation
  now fails. The script was restored before timings and complete validation.
- Red/green evidence also covers missing/duplicate lookup rejection, consumer
  isolation, infrastructure errors, shared-fixture adoption and unmapped errors.

## Complete local validation

After the timing comparison, main's benchmark refresh `74c4216` was incorporated;
it did not alter the typing inputs or consumers. The final combined source tree
passed **4,173 cases normally** and **4,173 with forced lazy imports**, both with
zero test, function-fixture or session-fixture failures. All 180 typing/lookup
cases are included. The same private short `/dev/shm` root was used for both full
commands without deletion between them. Each left only a zero-byte uv lock;
no MariaDB artifacts remained. The outer root was removed only after recording
contents and confirming no live owned processes.

Strict typing, lint, formatting and generated-interface checks passed. GitHub
Actions was intentionally disabled by the maintainer; validation was local, not
a certification of a remote OS/database matrix. Full-run times are validation
records, not a comparison against earlier full-suite baselines.

[Machine-readable measurements](2026-10-26-static-typing-assessments.json) pin
commands, source/report hashes, grouped timings, coverage mappings, environments
and full-run results. Raw reports and fault probes are retained locally under
`/home/crpier/.cache/sq-typing-19X8N5` (pointer:
`/tmp/snekql-typing-consolidation-latest`).

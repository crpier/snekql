# Benchmark planning and native coverage — 2026-10-26

Tracking: #564 under #536. Base: `63a6c72f0c66a26b2cb5e0aac534aa07a4a7de7d`.

## Scope and interface

After maintainer confirmation of the pure planning and real CLI/fault seams,
extracted `benchmarks.comparison_plan.ComparisonPlan`. This frozen, keyword-only
source-checkout interface owns defaults, numeric/combined budgets, adapter
schedules and configuration/measurement labels. The CLI consumes that same plan;
no test-only renderer or alternative benchmark runner was introduced. The
[interface documentation](../../benchmarks/comparison.md#plan-without-running-a-database)
describes construction errors, immutable schedules and isolated metadata views.

Planning imports no native drivers and performs no database work. It does not
certify delivered rows, commits, prepared sessions, effective session policy,
latency or resource availability. Those remain real CLI/native observations.
The common MariaDB policy literal moved unchanged to an internal module so
planning need not import native adapters. Every native MariaDB function body is
unchanged; SQLite, transactions, pooling, diagnostics, fixtures, migrations and
library/package interfaces are unchanged.

This is deliberately a small startup-amortization slice, not a solution to the
native setup costs that dominate this test group. No success-report sharing,
persistent cache, dependency change, parallelism shortcut or default exclusion
was added. A focused adapter/backend still executes independently.

## Coverage map

All **88 original benchmark/fixture case identities remain**. Of the 25 original
comparative test functions, 23 retain identical function/decorator ASTs. Only the
following two functions change execution seam:

| Original protection | New pure protection | Retained real protection |
| --- | --- | --- |
| `comparison_rejects_invalid_bounds`: ten named numeric cases, usage exit, empty stdout and bounds diagnostic | Same names and values construct invalid plans and require `ValueError` with the bounds diagnostic | New `comparison_cli_rejects_individual_bounds_before_native_setup` checks exit 2, empty stdout and the exact pool-size bounds error with an empty tool PATH; all three existing combined-budget CLI cases stay unchanged |
| `comparison_rotates_adapter_order_between_trials`: nine round/adapter pairs across three rounds | Same name and independent nine-pair expected literal at `plan.schedule` | Unchanged `six_balanced_rounds_cover_every_adapter_permutation` verifies actual six-round order and positions; new nondefault reverse-order CLI check verifies dispatch/report wiring |

These **11 cases change from `slow` to `fast`**, because their bodies now perform
no IO. Nothing leaves default discovery. The three benchmark-fixture cases and
the other 74 original comparative cases retain their original bodies, parameters,
markers and native operation sizes. Their distinct protections include:

- Actual rows, identity sums and payload bytes for every adapter/backend;
  partial-final-batch consumption; incomplete/duplicate stream rejection and
  result-bearing `fetchall` prohibition.
- Indexed join projections, real bulk commit/readback, deliberately uncommitted
  writes and contention request accounting.
- Native session policy/drift, preparation of every capacity slot, wide payloads,
  pool diagnostics/counting warmup exclusion, scoped memory and heartbeat stalls.
- Real reproduction configuration, dependency/lock/hardware provenance,
  unavailable binaries failing rather than skipping, and retained owned startup
  diagnostics. No arbitrary temporary-data cleanup is introduced.

The new planning file adds **50 fast cases** for invalid intent, inclusive numeric
endpoints and ceilings, exact joint budgets, both write phases including row
allowance, schedule modes/cycles/single adapters, workload-dependent labels and
isolated policy views. Three additional subprocess cases cover early numeric
rejection, use without site-packages, and a nondefault real CLI round-trip. The
last checks explicit configuration/order/profile propagation **and actual** rows,
bytes, stream batches, latency count, prepared sessions and pool samples.

The final benchmark/fixture/planning group has **141 cases**: 61 fast, 77 slow and
three medium. The machine-readable audit lists every unchanged original function,
new case and main-integration case. Production AST checks also confirm unchanged
operation, measurement, heartbeat and environment bodies, native setup/artifact
scope, CLI defaults and MariaDB policy values.

## Repeated measurements

The unchanged selection contains **16 named cases**:

```sh
PYTHON_CONTEXT_AWARE_WARNINGS=1 uv run snektest \
  tests/test_comparative_benchmarks.py::comparison_rejects_invalid_bounds \
  tests/test_comparative_benchmarks.py::comparison_rejects_combined_resource_budgets_before_native_setup \
  tests/test_comparative_benchmarks.py::comparison_rotates_adapter_order_between_trials \
  tests/test_comparative_benchmarks.py::six_balanced_rounds_cover_every_adapter_permutation \
  tests/test_comparative_benchmarks.py::comparison_reports_reproduction_settings \
  --json-output
```

| Conditions | Before seconds, run 1 / 2 | After seconds, run 1 / 2 |
| --- | ---: | ---: |
| Initial untouched-base measurements, inherited default `/tmp` | 4.517 / 4.494 | 1.764 / 1.811 |
| Fresh owned short Btrfs TMPDIR per command, verification after full validation | 4.451 / 4.454 | 1.596 / 1.578 |

Initial before samples preceded all implementation at a clean base. The follow-up
restored the three original code/test files from the fixed base, ran twice, then
restored feature bytes in `finally` and ran twice. New unused module files and
documentation remained present: this was **restored benchmark input**, not a
pristine whole-checkout baseline. Recorded code/lock hashes pin both phases.
Frozen feature bytes were verified before and after this follow-up.

The observed mean reductions are **60.3%** for the initial pair and **64.4%** for
the owned-root verification: approximately **2.7–2.9 seconds saved for this
16-case command**. All eight reports have the same case inventory and zero test
or teardown failures. The 53 added default-suite cases are outside this timing
command; their cost is not subtracted from these savings.

The owned-root runs restore normal signal dispositions and use the same
interpreter, locked tools and context-aware warning setting. Each leaves only a
zero-byte uv lock; process/artifact accounting precedes removal of only that
run's root. No concurrent suite was launched by this session during timings.
The host is nonexclusive; sequential before/after pairs are neither an
interleaved statistical experiment nor a timing gate. Command wall time is
authoritative; runner per-case durations exclude managed teardown.

The earlier unchanged **88-case Btrfs** baseline from another checkout remains
useful provenance (340.15 / 360.05 seconds, identical benchmark/source/lock hashes
at the fixed base), not a comparison against the larger tmpfs validation below.
No benchmark throughput remeasurement or whole-suite percentage speedup is
claimed. Native setup still dominates the broader workload group.

### Cold focused checks

Two independent invocations per phase, using the inherited default TMPDIR:

| Named selection | Before wall seconds | After wall seconds |
| --- | ---: | ---: |
| `comparison_rejects_invalid_bounds[zero-workers]` | 0.515 / 0.472 | 0.197 / 0.184 |
| `comparison_reports_reproduction_settings` (retained real CLI) | 0.506 / 0.502 | 0.486 / 0.496 |

The numeric sample removes approximately 0.30 seconds of mean cold feedback.
The retained CLI control is effectively stable at this sample size, not evidence
of a native execution speedup. No shared batch setup or focused adapter poisoning
was introduced.

## TDD and calibrated faults

Vertical red/green slices established the public interface, numeric validation,
seed/INSERT/write budgets, schedules, configuration, measurement labels and
invalid-selector/Boolean rejection. Missing-interface and failed-assertion reports
are retained, along with subsequent green reports; intermediate failures are not
counted as successful validation.

Plausible mutations were tested in separately owned source snapshots, never in
the tree under full validation:

| Mutation | Observable result |
| --- | --- |
| Bypass numeric checks | Both the named pure bounds check and early-rejection CLI guard fail |
| Use the smaller write phase instead of the larger | Both measured-only and warmup-only oversized phase cases fail |
| Return the shared policy dictionary | Editing a report view contaminates policy and the isolation check fails |
| Report default configuration instead of the executed plan | Pure configuration remains healthy; retained real CLI reproduction check fails |
| Execute a default schedule instead of the requested plan | All three pure schedule mode cases remain healthy; nondefault real CLI wiring check fails |

These last two distinguish planning correctness from integration correctness.
No successful expected dictionary is supplied to the CLI or manufactured from a
native fault. The rejected native-startup mutation retains diagnostics inside its
explicitly owned evidence root; no owned process remains live. All failed and
intermediate evidence is preserved.

## Complete local validation

Frozen code/tests passed **4,242 cases normally and 4,242 with forced lazy imports**,
with identical inventories and zero test/errors or fixture/session-teardown
failures. Wall times were **358.247 / 359.494 seconds**, recorded only as validation.
Each includes the complete 141-case benchmark/fixture/planning group.

Inventory comparison preserves all 4,187 cases from the earlier dynamic-typing
full report, both subsequently merged #563 proofs, and exactly 53 new cases here.
The same private short tmpfs root was used without deletion between full runs.
Each left only the same zero-byte uv lock, not MariaDB data or logs. The owned
root was removed after both commands and process/artifact accounting; caller-owned
or reusable data was not swept.

A separate direct `python -X lazy_imports=all -S` invocation constructs and
serializes the pure MariaDB plan without site-packages. This certifies that
interface, **not** forced-lazy native/Core execution. Full-run CLI children use
ordinary import mode; the existing direct SQLAlchemy limitation in #558 remains
unchanged. Strict typing, lint, formatting, generated-interface and whitespace
checks passed. GitHub Actions remains intentionally disabled: these are local
checks, not certification of a remote platform/database matrix.

[Machine-readable evidence](2026-10-26-benchmark-planning.json) records commands,
source/report hashes, environment, inventories, calibrated faults and cleanup.
Raw reports and scripts are retained in the directory named there (pointer:
`/tmp/snekql-benchmark-planning-latest`).

# Immutable typing-assessment reuse — 2026-10-26

Tracking: [#536](https://github.com/crpier/snekql/issues/536),
[PR #563](https://github.com/crpier/snekql/pull/563).

## Integration with #561

Main independently merged the same static-sharing optimization in #561 at
`4ad6564543580e91fda16852964947cc4b14e7d5` before #563 was merged. The integrated
#563 **preserves main's support module and both consumer modules unchanged**,
including its defensive `TypingAssessment` lookup, actual aggregate exit status,
isolated report views, nine lookup regressions and stronger identity/cardinality
completeness assertion. It does not install a second cache or revert those checks.
The remaining code delta is the two end-to-end copied-checkout/focused-runner
proofs below. Both execute against main's retained implementation.

The scope description, comparison and 4,166-case full validation below are
**historical observations pinned to `94220e1...`**, not measurements or a full-suite
pass of the reconciled head. In that measured implementation, private reports were
parsed from immutable bytes; the integrated implementation instead retains main's
isolated report/observation views. See the integration validation record for exact
reconciled-source commands and results. No new performance claim is made at that
head, and #562's distinct dynamic probes are not changed by this PR.

## Historical measured scope

This slice changes test execution, not library declarations, typing templates,
the consumer-assessment CLI, dependencies, or API/migration semantics. It does
not complete the broader #536 programme.

At clean measured revision `94220e1eabb52a98e220f71bac17fed5efc08f79`,
60 existing named tests share one native CLI assessment of the same 124
backend/case pairs. The CLI already batches these callers; no new batch flag or
checker framework was needed. The session fixture retains immutable JSON bytes,
not mutable dictionaries, native processes, or materialized temporary callers.
Each consumer parses its own report and selects the native observations it needs.
The cache lasts only for that snektest process, not across source changes/runs.

Nine original CLI cases remain independent: the two lifecycle/backend selections,
three rejection-calibration cases, missing-input infrastructure failure,
environment/source provenance, explicit configuration, and help/selector scope.
The three rejection calibrations still run a clean control before changing their
owned copied inputs. The 80 nested-expression and 22 temporal challenge cases are
unchanged and still invoke their own copied CLI with independently mutated inputs.
A shared immutable assessment must never serve these mutable input checks.

## Retained protection

All **171 original case names** appear unchanged in every matched four-file run.
No property budget, default selection, checker policy, backend, or challenge was
removed. The two new end-to-end cases bring this focused inventory to 173.

| Original protection | Candidate mapping |
| --- | --- |
| Exact positive-control and negative diagnostic assertions | Same per-test assertions over native observations, including empty positive errors and the original expected count, rule, line and conformance checks |
| Backend coverage and observation cardinality | Selector checks exact backend identities and cardinality before returning observations; backend-specific constructor cases still select their original backend |
| Successful selected assessment, no foreign errors | Fixture accepts only usable exit 0/1 reports; consumers validate their selected conformance and reject unmapped errors |
| Full default assessment | Existing named full-report test still requires 124 conforming pairs and no unmapped errors |
| Real CLI selection, schema, environment, hashes, configuration, help and infrastructure exits | Nine existing independent CLI cases are retained |
| Mutated nested/temporal inputs | All 102 cases and their native checker executions are untouched |
| Independently named failures and focused parameter selection | Two new real copied-checkout/snektest proofs, described below |

A usable exit-1 report is not an infrastructure failure: it may contain one bad
contract and many good ones. Rejecting that status at session setup would turn
unrelated named tests into fixture errors. The fixture instead leaves conformance
to each selected test. Exit 2 and other infrastructure exits remain fixture errors;
missing/malformed report fields cannot establish conformance.

### Fault and focus proofs

The copied-checkout test changes five distinct native inputs in one assessment:

| Contract | Owned input fault | Expected named failure |
| --- | --- | --- |
| `temporal-domains` | Invalid assignment in its independent positive control | Broken control |
| `select-all` | Two unresolved `.all()` calls on the same marked line | Diagnostic count is two, not one |
| `readonly-scalar` | Assignment error on the marked line instead of the intended overload error | Wrong diagnostic rule |
| `exists-family` | Valid statement at the marked negative challenge | Missing rejection |
| `nullable-expression` | Valid marked statement, assignment error on the next line | Wrong diagnostic location |

The real focused runner reports exactly these **five named failures**, **12 good
contracts**, and no infrastructure/teardown errors. A second test selects only
`temporal-domains` while an unselected `select-all` control is broken; the selected
contract still passes as one named case. No library/test internals are mocked.

Three separate copied-source mutants were then calibrated: globally rejecting
exit 1, dropping the negative-count assertion, and dropping the expected-rule
assertion. The public end-to-end proof rejects each mutant. Restored copies pass
both proofs. The exact copied-source hashes, mutations, commands, statuses and
reports are retained in the evidence packet. These mutations are calibration,
not failing-before claims about historical library behavior.

## Matched focused measurements

Baseline: `74c4216032e55bfbfb45cab551926b1b96388179`.
Candidate: `94220e1eabb52a98e220f71bac17fed5efc08f79`.

| Existing workload | Cases | Before wall seconds | After wall seconds |
| --- | ---: | ---: | ---: |
| `test_typing_compatibility.py` + `test_typing_guarantees.py` | 69 | 16.92 / 18.10 | 2.67 / 2.76 |
| Those files + nested-expression + temporal challenges | 171 | 50.39 / 53.94 | 35.06 / 34.07 |

All observations pass, with identical case names and zero test, function-fixture,
or session-fixture failures. The two new regression cases are deliberately not
hidden in this like-for-like table; they remain in the default correctness suite.
Their separate reports and full-suite inclusion are retained.

The measurements support a focused reduction in repeated execution, not a
universal speedup or a whole-suite performance claim. Each profile used the order
before/after, then after/before, with a fresh process and private Btrfs TMPDIR.
The historical revision was checked out read-only in a temporary worktree. Both
used the same absolute interpreter and installed dependency environment, without
uv synchronization or changing editable-install metadata between worktrees.
Library sources and the CLI/templates are unchanged between the revisions.

`PYTHON_CONTEXT_AWARE_WARNINGS=1` was set at startup. The packet records exact
commands, revisions, names, platform, CPU affinity, load snapshots, source/lock
hashes and report hashes. No other suite/build was launched by this agent during
these captures. Unrelated host/worktree activity, CPU frequency and warm caches
were not isolated. Two observations per condition are not confidence intervals,
a stable percentile, or a cold-install benchmark.

Snektest charges session fixture startup to its first consumer. Consequently,
individual later test durations are not standalone execution costs; compare
combined command wall time, not the near-zero times of later cached consumers.

## Validation and excluded evidence

- Clean candidate full suite: **4,166 passed in 1018.83 seconds**, zero test,
  function-fixture or session-fixture failures. All 173 focused names are included.
  The tracked checkout was clean at both start and finish.
- Forced-lazy focused runner: **173 passed**, zero failures/errors. This exercises
  the test runner/helper in forced-lazy mode; fresh CLI children do not inherit
  `-X`, and this does not remediate or requalify the separate SQLAlchemy limitation.
- Typing, Ruff lint/format, generated-interface, lock and Git whitespace checks pass.
- The successful full run left only a zero-byte uv lock in its owned TMPDIR,
  with no native logs. Inactivity and artifact accounting were recorded before
  removing that root. This is cleanup evidence, not a leak-freedom claim.
- GitHub workflows remain intentionally disabled. Actions were not awaited or
  changed; no CI/platform/native-version matrix pass is claimed.


The initial tmpfs full attempt is **failed evidence**, not a pass:
**4,049 passed / 42 failed / 75 errors**, zero fixture/session teardown errors,
exit 1 after **274.46 seconds**. MariaDB repeatedly reported error **122** while
preallocating its 96 MiB redo log. `/tmp` has `usrquota`; filesystem-wide free
space did not establish per-user quota headroom. The report and installer error
text are retained, not replaced by the later disk-backed run. No standalone
native `.err`/`.log` remained in that root; its attempted log archive was empty.
After confirming inactivity, only this attempt's owned temporary root was removed.
No quota, host mount, unrelated process, or other worktree data was changed.

The full correctness rerun uses a short owned disk-backed TMPDIR and is **not** a
matched timing comparison with tmpfs or any historical full-suite run. No
whole-suite percentage improvement is claimed. Existing marker misclassifications
are intentionally left for the later #536 marker review.

A superseded multiple-`--case` CLI prototype and its exploratory red/green logs
remain in local scratch, excluded from final source, measurements and claims.
The final consumer CLI is byte-identical to the baseline CLI.

## Reproduce

```sh
PYTHON_CONTEXT_AWARE_WARNINGS=1 uv run snektest \
  tests/test_typing_compatibility.py tests/test_typing_guarantees.py \
  tests/test_nested_expression_families.py tests/test_temporal_typing.py \
  tests/test_typing_assessment_execution.py

PYTHON_CONTEXT_AWARE_WARNINGS=1 uv run snektest \
  'tests/test_typing_guarantees.py::public_typing_contract_has_exact_diagnostic[temporal-domains]'

# Narrow native assessment is still available without changing CLI semantics.
uv run python scripts/check_typing_compatibility.py \
  --case temporal-domains --backend sqlite
```

The explicit test selector collects one named test but initializes the complete
shared assessment once. For a narrower native assessment, use the unchanged CLI
command above. Mutation-based tests always own fresh copied inputs.

See [the evidence README](2026-10-26-typing-assessment-data/README.md) for raw
reports, input/inventory mapping, calibration and checksum verification.

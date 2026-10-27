# Shared declarations without importing named-query test owners

Date: 2026-10-27. Issue: #571 under #536. Sixth bounded slice, not completion of
the broader audit. This improves declaration locality/focused collection; no
runtime speedup or product defect is claimed.

## Authorization and scope

After explicit maintainer authorization, #585 was merged as
`3ed75324bbb12b189470f296e55faddf63d72b5b`. Its resulting main tree was verified
equal to the validated feature tree. This new branch starts from that freshly
fetched main with a clean worktree and continues this session's recorded #571
claim. Authorization to merge #585 does not authorize merging a future PR.

The already-approved seams are public Query Builder construction/compilation
and focused snektest selection. No new execution or materialization assertion is
introduced. Existing SQLite/native runtime checks are rerun, not replaced, and
no fixture lifetime or schema setup is changed. The native #570 checkpoint is
now closed; that does not grant permission to broaden this unit into fixture
optimization or take another session's work.

## Finding and chosen extraction

Four consumers import declarations from `tests/query/test_named_projection.py`:

- `tests/query/test_named_returning.py`
- `tests/runtime/test_named_projection.py`
- `tests/runtime/test_named_returning.py`
- `tests/runtime/test_output_labels.py`

This is actual reuse of the same declarations, not similar-looking schemas.
Move exactly five definitions into `tests/query/named_models.py`:

| Declaration | Distinct purpose retained |
| --- | --- |
| `Person` | SQLite table input with integer primary key and text name; Pending/Row declaration unchanged |
| `PersonSummary` | Two-field application result contract, not a table |
| `OptionalPersonSummary` | Separate result contract admitting outer-join NULL |
| `PeerRole` | Shared nominal role for the second occurrence of this Person |
| `WidePerson` | Nine independently named fields beyond positional overload limits |

All five complete class ASTs, including documentation, bases, fields, annotations,
field order and options, match their original definitions. Every affected caller
uses the shared definitions. The five classes' `__module__` naturally changes to
`tests.query.named_models`; this extraction does **not** claim that qualified
Python module paths remain unchanged. SQL names/shape, logical result contracts,
within-revision shared identity and unrelated owner/backend distinctions remain.

The support module owns no fixtures, migrations, Database configuration or live
state. It is not a canonical Person schema for the repository. In particular:

- Runtime `MariaPerson` remains in its existing module, with its native-family
  declaration and physical table name untouched.
- Query-returning `MariaRecord` remains a different model for capability guards.
- `tests/query/test_output_labels.py::Person` has `person_id`, not `id/name`; it
  remains independent. Other Person models, roles and codec declarations are
  likewise not unified by name or shape.
- The two `provide_people` / `provide_maria_people` fixture functions do not move.
  Their decorators, migration keys, `scaffold`, explicit `migrate`, seed rows,
  server fixture consumption, transaction scopes and teardown source are exact.
  ADR 0007's migration-only schema authority is retained.

## Contract accounting and structural inventory

No assertion or execution is removed or replaced. All 54 existing case bodies,
decorators and names/markers in the five-file group are unchanged: 17 public
construction/compilation cases and 37 real runtime cases. All 63 function source
segments—including nested validators, fixture functions and TYPE_CHECKING
helpers—are identical, not just equivalent after result-variable normalization.

The AST audit removes imports and the five moved owner definitions, then compares
all remaining top-level nodes exactly. All other classes and module-level
TYPE_CHECKING blocks remain intact. All 117 tracked SDK files and all other
pre-existing tracked inputs are byte-identical. Dependencies, property budgets,
default selection, readiness/error behavior, migrations, cancellation/deadlines
and native resource ownership are unchanged.

| Original contracts | Retained default-suite evidence |
| --- | --- |
| Named binding SQL/order, logical type compatibility, nullable joins/aggregates, missing/extra/ambiguous/root contracts, scalar/backend/scope guards and type aliases | Same 12 query projection cases and their exact expectations |
| INSERT RETURNING labels; backend capability, foreign-column and DoNothing guards; annotated result/cardinality/readiness helpers | Same five query returning cases and TYPE_CHECKING functions |
| Named row materialization, nullable aliases/scalars, wide rows, constraints with column validation disabled, grouped HAVING, validator replacement, streaming and optional cardinality | Same 13 runtime projection cases, including real MariaDB |
| Single/bulk/empty cardinality, both backends, readiness transitions, deleted/updated values, named-to-positional replacement, wide results and upserts | Same 13 runtime returning cases |
| Labeled UUID/JSON codecs, validation exactly once, scalar/aggregate NULL, native JSON validation, nullable arithmetic, COALESCE and CASE | Same 11 runtime output-label cases |

Fixed-base cross-test `from`-import inventory (file count / statements / consumers
/ targets): **331 / 115 / 69 / 40 → 332 / 111 / 67 / 39**. The four imports no
longer target a test owner. The owner itself now imports support. Runtime fixture
imports and other semantic owners are deliberately retained. These numbers are
candidate/maintenance evidence, not a duplication verdict, reduced execution
count or measured startup saving.

## Red/green and focused independence

The query returning consumer first imports nonexistent support and fails
collection with `ModuleNotFoundError`; extracting only `Person` and
`PersonSummary` makes all five cases pass. The runtime projection consumer then
imports the incomplete support module and fails on the missing optional result
contract; adding the remaining exact declarations makes the owner's 12
compilation/construction checks pass. The remaining consumer changes are imports
only; the complete 54-case group validates their existing real execution paths.

The corrected calibration contains **16 commands**:

- Corrupt common SELECT/RETURNING aliases: the same three positive compilation
  cases reject the fault before/after, with 14 healthy cases; restored runs pass.
- Remove logical-domain/nullability binding checks: the same incompatible-column,
  left-join-nullability and nullable-SUM negatives reject the fault before/after,
  with 14 healthy cases. An independent healthy INSERT RETURNING selection still
  passes; restored runs pass.
- Remove the former query owner in source copies: the original five-case query
  consumer aborts collection with `ModuleNotFoundError`; the revised five cases
  pass without that file. Four independently attempted consumer-module imports
  fail before and all succeed after. Restoring the file yields five passes for
  both snapshots. Runtime import probes establish collection independence, not
  substitute database-execution evidence; the real 54-case group remains intact.
- All 17 query cases pass with an empty executable search path. This checks lack
  of executable search in that selection, not comprehensive absence of I/O.

Seeded SDK test failures are named `AssertionFailure`s with zero report errors
or teardown failures. Missing-module collection/import failures are separately
classified, not fabricated as JSON test results. Every SDK mutation is restored
and rerun successfully in its owned copy. The live SDK is never mutated. This
preserves sensitivity, rather than claiming the extraction adds SQL coverage or
constitutes a repository-wide mutation score.

The initial calibration wrapper incorrectly attempted to decode a textual
collection failure as JSON. That attempt, its partial records and raw output are
retained under `faults-initial`; the wrapper was corrected to recognize non-JSON
collection failures. No SDK or test input was changed to make evidence pass.
The corrected calibration runs after the full suite rather than concurrently.
Initial red collection results are expected failures, not passing validation.

## Validation and reproducibility

- Before/after query group: **17 passed each**; complete five-file group:
  **54 passed each**, including 37 existing real runtime cases.
- Forced-lazy-parent combined group: **54 passed**, names/markers identical to
  normal. Query directory **675 passed before/after**, and **675 forced-lazy
  query passes**, likewise identical.
- Fresh frozen normal full suite: **4,269 passed**, zero test/errors or
  fixture/session teardown failures; wall **429.974534726 seconds**.
  Every full case name/marker matches the previous validated #585 tree. Final
  source hashes/path inventory match this fresh run; the historical report is
  only an inventory comparison, not borrowed validation.
- No full forced-lazy or direct forced-lazy native/Core child-interpreter run is
  claimed. Parent lazy flags do not certify child Python interpreters.

Examples, with `PYTHON_CONTEXT_AWARE_WARNINGS=1` and normal signal dispositions:

```sh
PYTHON_CONTEXT_AWARE_WARNINGS=1 uv run snektest \
  tests/query/test_named_projection.py tests/query/test_named_returning.py \
  tests/runtime/test_named_projection.py tests/runtime/test_named_returning.py \
  tests/runtime/test_output_labels.py --json-output
PYTHON_CONTEXT_AWARE_WARNINGS=1 uv run python -X lazy_imports=all \
  scripts/run_lazy_tests.py tests/query --json-output
PYTHON_CONTEXT_AWARE_WARNINGS=1 uv run snektest tests --json-output
```

Native/full commands use private owned tmpfs roots. Only zero-byte uv locks
remained; process audits found no live owned processes before their removal.
Three inaccessible pre-existing process environments are recorded as audit
limits, alongside readable command-line/start-time checks. Caller-owned
`.snektest/mariadb-data` remains untouched; no stale-artifact sweep or global
per-test environment mutation is introduced.

Typing, lint, formatting (637 files), generated-interface and whitespace
checks passed:

```sh
uv run ty check
uv run ruff check .
uv run ruff format --check .
uv run python scripts/generate_query_overloads.py --check
git diff --check
```

Actions remains intentionally disabled; there is no remote-matrix claim. The
host was nonexclusive. No other suite from this session ran during the full
command; corrected fault calibration and combined lazy validation ran afterward.
No timing comparison or performance extrapolation is made.

The paired JSON contains source/mapping hashes, exact commands, calibration and
cleanup records. Raw artifacts are retained at
`/home/crpier/.cache/sq571-named-kTs2naHy` (pointer:
`/tmp/snekql-named-audit-latest`).

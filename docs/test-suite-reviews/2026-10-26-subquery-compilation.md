# Subquery compilation contracts and shared declarations

Date: 2026-10-26. Issue: #571, under #536. Third bounded slice; the broader
behavioral audit remains open. This is not a runtime optimization.

## Scope and findings

Base: `a12eb4d2e4f173cff16a68b39380970243b4d6be`, after #575, #576, #580,
and #581. The maintainer requested continued work within the already-approved
public Query Builder construction/`compile()` and focused snektest seams.
Native setup/lifecycle work reserved under #570 is not changed.

Two limitations were found in `tests/query/test_subqueries.py`:

1. `subqueries_are_backend_portable` applied a MariaDB codec to SQLite query
   state. It checked MariaDB-style SQL, but did not construct a public MariaDB
   outer/inner query. The replacement retains its literal SQL and `(100,)`
   expectation, constructs both sources through `mariadb.select()`, and also
   asserts the compiled backend.
2. The module promises textual parameter ordering across nested queries, but its
   original fast cases bind at most one value each. They cannot distinguish
   reversed outer/inner bindings. Two new, separately named cases require exact
   SQL, `(1, 100, "ca")` bindings, and the owning backend: one SQLite and one
   MariaDB. The values occur before, inside, and after an IN subquery.

These are local test-evidence gaps, not demonstrated SDK defects or claims that
no other repository test protects the affected code. The current SDK satisfies
both new examples. Fault results below apply to their named selections, not a
whole-suite mutation score.

## Changes and retained contracts

All 17 original subquery case names/markers remain. Ten direct compilation
calls move from a private codec to public `.compile()`; none is removed or
replaced by a shared observation. The two new cases add two compilations.

| Original area | Retained protection |
| --- | --- |
| Column comparison | Qualified joined operands; rejection of a comparison to an unscoped table |
| IN / NOT IN | Nested SQL and bindings, negation, single-column construction constraint |
| EXISTS / NOT EXISTS | Correlation and qualified outer reference, negation, rejection of an unavailable outer table |
| Scalar subqueries | Projection and comparison SQL, empty binding tuples, single-column requirement, invalid projection anchors |
| MariaDB inspection | Same nested SQL and `(100,)`, now using MariaDB-owned models and verbs; additional backend assertion |
| Four real SQLite execution cases | Membership filtering, correlated EXISTS, per-row scalar aggregate, empty scalar decoding to `None` |

The source/AST audit records every original case and verifies its original
assertions, expected SQL assignments, decorators, and builder expressions. The
portability builder has the explicit namespace/model mapping described above;
other builders match without it. The three construction-case bodies and all
four runtime-case bodies are unchanged. No decoder, migration-backed setup,
foreign-key scope, or empty-result protection is replaced with compilation.

`tests/query/subquery_models.py` holds the **exact original class ASTs** of the
SQLite `User`/`Order` pair genuinely shared by the subquery tests and
`test_cte_boundaries.py`. Both consumers now import those same declarations from
support, rather than having one test module own the other's inputs. Their
FK relationship is retained. Similar-looking declarations in other
modules remain distinct and unchanged.

The support module also declares minimal MariaDB inspection inputs: an outer
ID/country and an inner FK/amount. They are not runtime fixtures, native schema
snapshots, or evidence of execution. No model factory, compiler wrapper, cached
result, or alternative runner is introduced.

All four CTE-boundary function bodies/decorators and all six mixed-backend
rejection tests remain unchanged. The deliberate corrupted-CTE-cycle test is
kept: public immutable builders cannot construct that corruption, and a public
success case would not replace its fail-closed guard.

The fixed-base mechanical cross-test import inventory is:

| Inventory | Before | After |
| --- | ---: | ---: |
| Python test/support files scanned | 330 | 331 |
| Imports targeting `test_*` module paths | 116 | 115 |
| Consumer files | 69 | 69 |
| Target test modules | 41 | 40 |

This counts AST import statements, including absolute/relative module-path
imports, not every support import or unique graph edge. The CTE-boundary module still
imports its separate CTE declarations from `test_ctes`; it remains a consumer.
The inventory is candidate discovery, not a verdict that remaining imports or
repeated executions are bad.

All 117 tracked SDK files and all other pre-existing tracked inputs are
byte-identical to the base at the code-audit checkpoint. Only two existing test
files change, alongside the new declaration module and this report/data. No
runtime helper, dependency input, Hypothesis budget, or default selection changes.

## Red/green and fault calibration

The CTE correlation tracer first rejected missing support, then passed with the
original model pair. The MariaDB portability tracer rejected missing MariaDB
declarations, then passed with minimal backend-correct inputs. The new SQLite
binding test first ran against a reversed-binding fault in an owned source
snapshot and failed; restoring the compiler made it pass. The new MariaDB
binding case rejected the absent country field, then passed after that field was
added. The live checkout's SDK was never mutated.

Further calibration uses owned source snapshots and real installed snektest:

| Fault / selection | Original result | Revised result |
| --- | --- | --- |
| Public result tagged SQLite | 13 fast cases pass | Two MariaDB cases fail; 13 others pass |
| Public result changes MariaDB quotes to SQLite quotes | 13 fast cases pass | Same two fail retained literal SQL; 13 pass |
| Public result reverses bindings | 13 fast cases pass | Exactly the two new binding cases fail; 13 pass |
| Common predicate compiler reverses bindings | 13 fast cases pass | Exactly the same two new cases fail; 13 pass |
| Select healthy IN case alone under either ordering fault | Not needed for replacement | One selected case passes despite unselected failures |
| Omit nested backend guard | Six mixed-backend negatives fail; two valid controls pass | Same result |
| Omit column scope guard | Two original subquery negatives and CTE capture negative fail; four valid/other guards pass | Same result |
| Remove former owner `test_subqueries.py`; select CTE boundaries | Collection aborts with `ModuleNotFoundError` | All four CTE cases pass independently |
| Miswire revised portability case to SQLite sources | Not applicable | Literal SQL rejects wrong namespace; restoration passes |
| Run all revised fast subquery cases with empty `PATH` | Not a public MariaDB check | 15 pass without executable search |

All 31 calibration commands are retained, including restored reruns for every
SDK mutation and independent healthy selection under both binding faults. Every
reported seeded fault failure is an `AssertionFailure`, with zero report errors
or teardown failures. The expected original missing-owner collection abort is a
separate diagnostic, not a JSON report; the red missing-declaration tracers also
abort collection. The expected missing-country tracer is an `AttributeError`.
Those raw failures and the capture metadata are retained rather than counted as
passing validation. Empty `PATH` proves no executable search is needed for these
selected inspections, not native execution or comprehensive absence of all I/O.

## Keep-as-is and subsequent candidates

- `test_distinct.py` is not consolidated. Model/scalar/tuple/join projections
  have different result contracts even where SQL happens to match. Its
  order-independence/idempotence comparisons complement independent literal SQL
  controls and real deduplication execution. Cheap repeated compilation alone
  is not a reason to remove a case or conflate model identities.
- `test_sql_repr.py::bare_select_repr_renders_sql` contains self-comparisons of
  `repr` and `str`; its `SELECT` assertion provides narrower independent
  evidence. This is a future oracle-quality candidate, not a change in this
  slice. The separately inspected privacy/logging/error controls in
  `test_safe_inspection.py` provide distinct protection and remain untouched.
  Confirm the additional public formatting/inspection seams before adding tests
  there; the current approval covers construction/compilation and focused runs.
- Native fixture/data-copy imports, packaging paths, properties and plan/runtime
  internals remain outside this bounded implementation. This is not completion
  of the remaining 115-import inventory or of #571.

## Validation and reproducibility

- Before/after focused selection: **27 / 29 passed**. All original names/markers
  remain; only the two ordering cases are added.
- Before/after query directory: **671 / 673 passed**. Forced-lazy query selection:
  **673 passed**, identical names/markers to normal.
- Frozen normal full suite: **4,267 passed**, zero failures/errors or fixture/
  session teardown failures; wall **355.597182871 seconds**. This is validation,
  not matched performance evidence. All 673 focused query cases retain their
  names/markers in the full report. Source hashes match before/after the run.
- No full forced-lazy run is claimed for this branch; other branches' historical
  full runs do not certify it. Runner flags do not certify native children.

Commands use `PYTHON_CONTEXT_AWARE_WARNINGS=1`, normal signal dispositions, and
explicit selections (`tests` for the full run). Full validation used one private
owned tmpfs root, `/dev/shm/sqa-h85qe9r7`. Only a zero-byte uv lock remained;
process checks verified no live owned process before removing that lock/root.
Three inaccessible pre-existing process environments are recorded as an audit
limit; their readable command lines did not contain the owned root. Reusable
`.snektest/mariadb-data` was left untouched. No stale-artifact sweep or global
per-test environment mutation is introduced.

Focused reproduction (use the real default runner, not a local substitute):

```sh
PYTHON_CONTEXT_AWARE_WARNINGS=1 uv run snektest \
  tests/query/test_subqueries.py tests/query/test_cte_boundaries.py \
  tests/query/test_subquery_backends.py --json-output
PYTHON_CONTEXT_AWARE_WARNINGS=1 uv run snektest tests/query --json-output
PYTHON_CONTEXT_AWARE_WARNINGS=1 uv run python -X lazy_imports=all \
  scripts/run_lazy_tests.py tests/query --json-output
PYTHON_CONTEXT_AWARE_WARNINGS=1 uv run snektest tests --json-output
```

Static/generated/whitespace validation passed:

- `uv run ty check`
- `uv run ruff check .`
- `uv run ruff format --check .` (633 files)
- `uv run python scripts/generate_query_overloads.py --check`
- `git diff --check`

Actions is intentionally disabled. No remote matrix or runtime-speedup claim is
made. The host was not exclusive; no other suites from this session ran during
the full command.

The paired JSON contains source hashes, contract mapping, fault summaries and
report hashes. Raw scripts, source snapshots, reports and expected failures are
retained under `/home/crpier/.cache/sq571-query-7FCBi0T7`; the convenience pointer
is `/tmp/snekql-query-audit-latest`. Fault snapshots contain ordinary copies of
source, not reusable database data.

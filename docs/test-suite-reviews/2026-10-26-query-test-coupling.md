# Query-test coupling: a first behavioral-audit slice

Date: 2026-10-26. Issue: #571, under the #536 test-suite review.

**Status: partial audit and bounded maintenance change, not completion of #571.**
This slice removes four imports of shared declarations from a test module and
moves five join-compilation checks to public Query Builder compilation. It
removes no tests, assertions, parameter cases, or database executions. It makes
**no runtime-speedup claim**.

## Fixed inputs and approved seams

The branch started after #574 at `3f47603b4c8786544721e63e68a374f6bd8c1012`.
Before baseline runs or edits, it fast-forwarded to current main
`c7aee1611fdcef7c6ef92ffcf6489596fd7daa8b`, which includes #573's shutdown-grace
work. None of that lifecycle code changes here.

The maintainer confirmed these seams before test changes:

1. Public Query Builder construction and `query.compile()`: exact SQL and
   binding results, with independently retained valid/invalid scope and identity
   controls. This does not prove database execution or Materialization.
2. Existing focused snektest selections: independently named feedback and test
   discovery. This does not replace the complete native suite.

The implementation changes only test support and tests. All 114 tracked files
under `snekql/` are byte-identical to the fixed base. Dependency inputs, property
budgets, runtime fixtures, cancellation/deadline checks, migration replay, and
native/backend coverage are unchanged.

## Inventory and selective disposition

The initial mechanical inventory at `3f47603` scanned 325 Python files under
`tests/`. At the fixed base after #573, it scans 326; the additional file is
shutdown support, not another cross-test-module dependency.

| Import-inventory measure | Fixed base | This slice |
| --- | ---: | ---: |
| Python files scanned under `tests/` | 326 | 327 |
| Import statements targeting `test_*` modules | 120 | 116 |
| Consumer files containing those statements | 72 | 69 |
| Target test modules | 42 | 41 |

These are **import-statement counts**, not necessarily unique graph edges or
proof of duplicate behavior. They include `from`/`import` statements whose module
path names a `test_*` module, not imports of ordinary support modules. The [JSON companion](2026-10-26-query-test-coupling.json)
contains the fixed-base inventory and exact removed imports.

Candidate dispositions are based on protection, not syntax or lower counts:

| Candidate | Distinct protection / maintenance finding | Disposition |
| --- | --- | --- |
| Join compilation models and four consumers | One genuinely shared SQLite `User`/`Order` pair lives in a collected test module. The five rendering checks use a private codec shortcut even though the public compilation interface can observe the same contracts. | Extract only this pair; retain all five checks at the public seam. |
| Raw execution, named-codec, and raw-lifecycle hubs | Respectively 17, 10, and 6 importing statements. Their support includes both models and fixtures; independent database ownership, decoder policy, contention, deadlines, and cancellation distinguish their executions. | Leave unchanged. Future locality work must not silently widen fixture lifetime or share native success. This slice does not take over #570's work. |
| Query arithmetic, CTE, recursive CTE, and column-protocol hubs | Five importing statements each. Reused declarations/roles connect different expression, binding, ownership, and decoder contracts; a reused symbol is not duplicate protection. | Preserve checks. Group-specific support extraction remains a candidate, not justification for a universal model factory. |
| Callable/defaulted FK declaration imports | Runtime consumers reuse declarations that also carry static positive/negative contracts. Similar `Account` names need not identify the same model or relationship. | Keep runtime and typing protection. Do not fold declarations solely by their fields. |
| Direct distributions, bundled documentation, rebuilds, and isolated installs | A direct wheel, sdist contents, rebuilt wheel away from the checkout, installed resources, and deliberately incomplete source inputs test different paths. Bundled-doc tests already share a session artifact fixture. | Keep distinct paths. Similar `uv build` commands alone do not justify sharing their results. |
| Compilation properties | `compilation_is_deterministic` deliberately compiles twice for each generated query; its 200-example budget and the separate 300-example placeholder property have different contracts. | Keep both real compilations and all Hypothesis budgets. Do not compare a cached result with itself. |
| Codec/plan and metadata assertions | `test_query_codec.py` exercises internal adapter routing/materialization; public SQL inspection does not exercise every private execution-plan policy. Conversely, the join rendering checks need not name a private codec. | Replace only the join shortcut. Do not blanket-delete internal adapter tests or classify every metadata assertion as brittle. |

This is not a repository-wide semantic classification of every assertion or
execution. The remaining 116 imports and other brittle-test candidates still
belong to #571's continuing audit. No subsequent extraction is authorized by
this report.

## Bounded change and contract mapping

`tests/query/join_models.py` owns the two shared declarations. Their class ASTs
are identical to the original `User` and `Order` definitions, including generic
lifecycle state, Row declarations, generated defaults, field options and FK
binding. There is no fixture, model factory, database state, or new test runner.

The four consumers change **only their import source**:

| Consumer | Retained cases | Protection retained |
| --- | ---: | --- |
| `test_aggregate_scope.py` | 14 | Group keys, hidden aggregates, correlated scalar/HAVING reads, valid row filtering, deep correlation, and MariaDB compilation controls |
| `test_join_predicates.py` | 14 | ON-prefix scope, boolean composition, later-join rejection, binding order, codecs and nested correlation |
| `test_table_aliases.py` | 17 | Role/name independence, collisions, original-model stability, ownership, invalid write/schema/backend use, and metadata immutability; static `assert_type` controls remain |
| `test_physical_name_scope.py` | 5 | Distinct declarations with colliding SQL names rejected for both backends; valid reuse of one declaration retained |

The five checks in `test_join_compilation.py` retain their function names,
`fast` markers, identical Query Builder expressions and expected values:

| Check | Retained assertion |
| --- | --- |
| `inner_join_renders_qualified_columns_and_on_clause` | Complete qualified SELECT/FROM/INNER JOIN/ON SQL; empty bindings |
| `left_join_emits_left_join_keyword` | LEFT JOIN/ON clause with both qualified columns |
| `cross_table_where_and_order_by_are_qualified` | Complete qualified SQL with WHERE/ORDER BY; exact `("a@b.c", "x")` binding order |
| `projection_join_selects_only_the_projected_columns` | Complete two-column projection join; empty bindings |
| `projection_join_filters_a_joined_but_unprojected_table` | Complete single-column projection and joined-table filter; exact `("x",)` binding |

Each former `SQLITE_CODEC.compile_select_sql(query)` becomes `query.compile()`;
assertions read `compiled.sql`/`compiled.params`. The number of compilations is
unchanged. Expected SQL remains independent literal text, not generated by the
implementation under test. The AST audit normalizes only these result-access
expressions and confirms every original assertion remains equivalent.

**Keep separate:** `test_join_validation.py` still owns its different
`User`/`Order` declarations and `Item`'s FK to that `Order`. Similar table names
and fields do not make distinct declaration objects interchangeable. Its five
construction-time rejection cases remain byte-identical, as does the existing
`Item` import in `test_join_predicates.py`. This bounded extraction does not
claim to remove every test-to-test import in the join area.

The focused six-file selection retains exactly **60** names/marker sets;
`tests/query` retains exactly **671**. No new decorated tests are added.

## Red/green and calibrated faults

The first tracer changed the existing inner-join case to compile the shared
support declarations through the public interface. It first rejected the
missing support module, then passed after the identical declarations were
provided. The remaining rendering checks moved to the same public interface;
all existing cases stayed green.

Further checks ran in explicitly owned source snapshots with the actual installed
snektest interpreter, not mocks or edits left in the validation checkout:

| Seeded fault / structural control | Fixed-base result | Revised result |
| --- | --- | --- |
| Remove `"user".` qualification in the common SELECT compiler | All five rendering assertions reject | All five rendering assertions reject |
| Remove the distinct-declaration collision guard, retaining alias-role checks | Four physical-name negative cases reject; 56 other focused cases pass | Same four reject; same 56 pass, including valid reuse |
| Corrupt SQL only in the public compilation result | All five codec-based cases pass | All five rendering assertions reject |
| Reverse bindings only in the public compilation result | All five codec-based cases pass | Only `cross_table_where_and_order_by_are_qualified` fails; four others pass |
| Select the healthy inner-join case alone under that binding fault | Not needed as a replacement proof | One selected case passes despite the unselected contaminated case |
| Delete `test_join_compilation.py` and select each consumer separately | Each of four commands aborts collection on the missing import | All four independently pass: 14, 14, 17 and 5 cases |

Every SDK mutation was restored inside its snapshot and the corresponding
five-case or 60-case command passed again. Native fixtures were not involved.
The owner-absence control deliberately removes a test file only inside owned
snapshots; default-suite discovery in the real checkout remains unchanged.

Two evidence-harness corrections are retained rather than counted as successful
runs. First, snektest classifies the existing bare Python `assert` in the LEFT
JOIN case as an `AssertionError`/`error`, whereas `assert_eq` produces a
`failed` framework assertion. The five-assertion SQL rejection is therefore
**four failed assertions plus one assertion error**, not five framework failures
or an infrastructure failure. Second, collection failure prints a diagnostic
instead of the requested JSON report. The corrected capture records that
explicitly; it does not invent a successful/empty JSON report. The initial
baseline-record script also expected a nonexistent `summary` key; unchanged raw
reports supplied the corrected totals, and original records remain available.

## Validation and timing limits

Before editing, the fixed-base focused command passed all 60 cases and the
query directory passed all 671. Afterward both commands passed the identical
inventories. The earlier 55-case five-file cluster had about 0.009 summed test
seconds in #564's full report; that is only a ranking aid. Fresh single-run
focused walls were approximately 0.23 seconds and query-directory walls
approximately 1.07 seconds. These are feedback/validation observations, **not a
repeated equivalent-condition performance comparison**.

The refreshed normal full report ranks comparative benchmark case durations at
48.484 seconds and native password-literal cases at 20.209 seconds; the five
query files above sum to about 0.00916 seconds. Per-case durations exclude managed
teardown and cannot establish wall-time shares or savings. This supports a
maintenance-first, not execution-amortization, disposition for this slice.

The final frozen code/test tree passed:

| Validation | Passed | Failures / errors / teardown failures | Wall seconds |
| --- | ---: | --- | ---: |
| Normal full suite | 4,242 | 0 / 0 / 0 | 445.5146 |
| Forced-lazy full suite | 4,242 | 0 / 0 / 0 | 423.5760 |

Both full runs have identical case names and markers; all 4,242 names from the
prior #564 full report are also retained. The walls above are validation only,
not a whole-suite performance comparison. Source hashes before/after each run
match the final code and tests. Strict typing, Ruff lint, formatting (622 files),
generated-interface and whitespace checks passed.

Both full commands used the same private tmpfs root, `/dev/shm/sqa-9thh2sbh`,
without deletion between runs. Each left only one zero-byte uv lock. After both
commands exited and owned-process checks found no remaining live process, that
root was removed. Three pre-existing user processes had unreadable environments;
the audit records that limitation and checks their readable command lines and
pre-validation start times instead of claiming those environments were inspected.
Caller-owned/reusable `.snektest/mariadb-data` was left untouched.

GitHub Actions is intentionally disabled; these results are not a passed remote
matrix. Forced-lazy runner validation also does not imply that ordinary child
interpreters ran with forced-lazy flags.

## Evidence and reproducibility

The JSON companion records fixed-base imports, source/contract audits, report
hashes, per-fault outcomes and completed validation. Raw reports, scripts,
initial failed captures, source snapshots and frozen-source hashes are retained
in `$HOME/.cache/sq571-JQ2jejW6`, also named by
`/tmp/snekql-behavioral-audit-latest` on the validation machine. Those paths are
local evidence, not required runtime inputs or a portable published artifact.

Focused reproduction from a source checkout:

```sh
PYTHON_CONTEXT_AWARE_WARNINGS=1 uv run snektest \
  tests/query/test_join_compilation.py \
  tests/query/test_aggregate_scope.py \
  tests/query/test_join_predicates.py \
  tests/query/test_table_aliases.py \
  tests/query/test_physical_name_scope.py \
  tests/query/test_join_validation.py --json-output
PYTHON_CONTEXT_AWARE_WARNINGS=1 uv run snektest tests/query --json-output
```

No cleanup here sweeps arbitrary temporary data or caller-owned/reusable
MariaDB directories. Source snapshots and failed-capture diagnostics remain
explicitly owned evidence. Broader duplication/brittleness dispositions and any
future execution-amortization claims require their own mapping and validation.

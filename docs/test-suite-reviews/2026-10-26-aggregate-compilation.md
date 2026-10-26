# Aggregate inspection through the owning Backend Namespace

Date: 2026-10-26. Issue: #571, under #536. This is a second bounded slice,
not completion of the repository-wide audit and not a runtime optimization.

## Scope and finding

Base: `c7aee1611fdcef7c6ef92ffcf6489596fd7daa8b`. The branch starts from
main independently of the still-open #576 join-test extraction; it does not
include that PR's changes or claim combined validation.

The maintainer asked to continue #571. This slice stays at the already-approved
public Query Builder construction/`compile()` and focused snektest seams.
It does not change native setup/fixture work reserved under #570.

The three `*_is_backend_portable` cases in `test_aggregates.py`,
`test_group_by.py`, and `test_having.py` previously applied `MARIADB_CODEC` to
SQLite query state. That usefully checked COUNT/GROUP BY/HAVING rendering with
MariaDB quoting/placeholders, but it did **not** construct a public MariaDB
query. This is a limitation of the old test evidence, not a demonstrated SDK bug
or a claim that the old rendering assertions were worthless.

The revised cases use `mariadb.select()` with a small, shared MariaDB declaration
in `tests/query/aggregate_models.py`. Their original SQL expectations stay
unchanged. They additionally require `compiled.backend == "mariadb"` and exact
bindings: `()`, `()`, and `(5,)` respectively. The model is an inspection input,
not a database fixture, universal schema, or evidence of executed work.

The related SQLite checks also use public `query.compile()` instead of a private
codec shortcut. No wrapper compiler, cached result, model factory, or runner is
introduced. This is a maintenance/inspection-contract improvement, **not a
runtime-speedup claim**.

## Contract accounting and keep-as-is decisions

| Area | Changed cases | Retained contract |
| --- | ---: | --- |
| Scalar aggregates | 5 | COUNT(*), COUNT(column), all four SUM/AVG/MIN/MAX SQL expectations, filtered SUM SQL/bindings, native-namespace COUNT inspection |
| GROUP BY | 6 | WHERE/GROUP BY/ORDER BY ordering, mixed projection, joined qualification, aggregate ordering, native-namespace inspection, ungrouped-projection rejection |
| HAVING | 5 | Clause and binding order, aggregate and grouped-column operands, joined SUM qualification, native-namespace inspection |

All **31** original cases retain their names and markers. **19 real compilations
remain 19**; none is replaced by a copied observation. Original SQL/binding
expectations and exception assertions are retained, with six additional
backend/binding assertions across the three portability cases.

The AST/source audit establishes:

- All six existing SQLite `User`/`Order` class declarations are unchanged and
  keep their separate identities; no FK/owner scopes are folded together.
- All **15 other case bodies** are unchanged, including nine SQLite execution
  cases and six additional construction checks. Real migration-backed setup,
  empty-result behavior, per-group results, validation and decoding are retained.
- For the replaced calls, Query Builder expressions match after the explicitly
  documented `select`/`User` to `mariadb.select`/`MariaUser` mapping in the three
  native-namespace cases. The other expressions match without that mapping.
- All 114 tracked `snekql/` files, other tests, helpers, dependency inputs,
  Hypothesis budgets and default-suite scope are unchanged.

Repeated-looking value/type assertions remain intentional. For example,
`7.0 == 7`; value equality alone cannot prove SUM still decodes to `int`.
Likewise, `(2.0, 6.0, 3) == (2, 6, 3.0)` cannot prove the promised COUNT/SUM/AVG
result types. The existing decoder type guards are meaningful protection, not
incidental implementation-shape assertions to remove.

A mechanical inventory of direct `SQLITE_CODEC`/`MARIADB_CODEC` calls in test
source counts `compile_select_sql` sites at **76 before / 57 after**. The 39
write-compilation, ten direct materialization, and four plan-compilation sites
are unchanged. These counts omit indirect calls and subprocess-source strings;
they are candidates for review, not blanket duplication/brittleness verdicts.
The inventory is based on main and does not subtract #576's pending changes.

## Red/green and fault calibration

The existing native COUNT case first rejected the missing shared declaration;
it passed when the minimal MariaDB model was provided. The grouped case then
rejected the missing grouping column and passed when that column was declared.
The HAVING case reused that input without speculative extra fields.

Owned source snapshots exercised real installed snektest commands. The live
validation checkout never contained an SDK mutation.

| Fault / control | Original cases | Revised cases |
| --- | --- | --- |
| Public result incorrectly tagged SQLite | Three portability cases pass | All three fail their backend assertion |
| Public MariaDB SQL incorrectly double-quoted | Three portability cases pass | All three fail their retained SQL assertion |
| Public result loses HAVING bindings | Three portability cases pass | Only HAVING fails; COUNT and GROUP BY remain healthy |
| Public result reverses binding order | All 22 fast cases pass | Only `having_renders_between_group_by_and_order_by` fails; 21 pass |
| Select a healthy grouped case alone under that fault | Not needed for replacement proof | One selected case passes despite unselected contaminated evidence |
| Common compiler emits invalid SUM(*) instead of COUNT(*) | Two COUNT(*) cases fail; 20 fast cases pass | Same two fail; same 20 pass |
| Common compiler reverses WHERE/HAVING bindings | One named case fails; 21 fast cases pass | Same result |
| Common compiler omits grouping validation | Ungrouped-projection negative fails; 21 fast cases pass | Same result, including valid grouped controls |
| Wire the revised portability cases to SQLite instead | Not applicable | All three reject the wrong namespace's SQL |
| Run only revised portability cases with empty PATH | Not a MariaDB public-query check | Three pass with no executable search path |

All SDK-mutant rejections are expected framework assertion failures, with zero
infrastructure errors. Each SDK mutation and the wrong-namespace wiring were
restored, then the same selection passed. This compares the named selections,
not hypothetical whole-suite fault-detection rates; other tests may independently
protect the same public interface.

The initial AST audit needed a normalizer correction for inline
`select(...).compile().sql` versus the old codec tuple index. Its failed audit
script is retained. Test/source expectations were not loosened to satisfy it.

## Validation

Unchanged and revised three-file commands each passed **31** cases with identical
names/markers. The query directory passed **671** unchanged cases before edits,
then **671 normally and 671 forced-lazy** afterward. No tests were added or
removed.

The frozen normal full suite passed **4,242** cases, with zero failures,
errors, fixture teardown failures or session teardown failures. All case names
and markers from the previous full inventory are retained. The 361.8037-second
wall is validation only; it is not speedup evidence. Final code/test hashes
match that run. Strict typing, lint, formatting (622 files), generated-interface
and whitespace checks passed.

No full forced-lazy run is claimed for this second branch; the 671-case
forced-lazy query run is the stated lazy-validation scope. Results from #576's
separate branch must not be represented as validation of this tree.

The full command used private tmpfs root `/dev/shm/sqa-r5_ijmh8` and left only a
zero-byte uv lock. After the runner exited and owned-process checks found no
remaining live process, the root was removed. Three pre-existing user processes
had unreadable environments; the audit records that limitation and verifies their
readable command lines/start times rather than claiming those environments were
inspected. Caller-owned/reusable `.snektest/mariadb-data` was left untouched.

Single focused walls (about 0.32 / 0.30 seconds) are feedback observations, not
repeated matched benchmarks. No saved execution or whole-suite performance
improvement is claimed. Actions is intentionally disabled; there is no remote
matrix claim.

## Evidence and reproduction

The [JSON companion](2026-10-26-aggregate-compilation.json) records the contract
map, source hashes, calibrated outcomes and validation. Raw reports, snapshots,
audit/capture scripts and development-red evidence remain locally under
`$HOME/.cache/sq571-aggregate-5BbMMqzE`, named by
`/tmp/snekql-aggregate-audit-latest`. They are evidence, not runtime dependencies.

```sh
PYTHON_CONTEXT_AWARE_WARNINGS=1 uv run snektest \
  tests/query/test_aggregates.py tests/query/test_group_by.py \
  tests/query/test_having.py --json-output
PYTHON_CONTEXT_AWARE_WARNINGS=1 uv run snektest tests/query --json-output
PYTHON_CONTEXT_AWARE_WARNINGS=1 uv run python -X lazy_imports=all \
  scripts/run_lazy_tests.py tests/query --json-output
```

These inspection checks do not replace actual backend execution, native-driver
coverage, migration replay, cancellation or deadline checks. The broader #571
audit, including the remaining codec/import candidates, stays open.

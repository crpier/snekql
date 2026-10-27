# Public insert compilation and batch-conflict binding oracles

Date: 2026-10-27. Issue: #571 under #536. Fifth bounded slice; not completion of
the broader audit. This is maintenance/test-fidelity work, not a runtime speedup.

## Reservation, seams and baseline

This session continues its recorded #571 reservation after the maintainer's
explicit authorization to merge #584 and request to pick up another improvement.
#584 was squash-merged as `e8eda1ab0f7b1c27c9fc34433e678ee9f9f1c89c`; main's
complete tree matches its validated feature tree. This new branch starts at that
freshly fetched main with a clean worktree. Approval to merge #584 does not
approve merging the next PR.

The previously approved seams apply: public Query Builder construction,
`compile()`, and focused snektest selection. They catch SQL, backend identity,
parameter encoding/order and construction/compilation rejection. They do not
prove database execution, conflict resolution by a live server, materialization,
transaction effects or isolation. Native fixture/lifetime work under #570 is not
part of this unit.

The two-file baseline is 20 fast cases: nine bulk/RETURNING and 11 conflict
cases. Their independent SQL literals, exact binding tuples, construction
negatives and compilation-error types already provide useful coverage. They are
not redundant merely because they all compile INSERTs. Baseline query selection:
673 cases. No benchmark comparison or whole-suite timing improvement is claimed.

## Findings and implementation

1. `bulk_returning_columns_lists_only_named_columns_once` checks the SQL but
   discards its parameters. A RETURNING-projection-specific binding reversal
   escapes all original 20 selected cases. Add the exact four-value tuple and
   owning backend, while retaining the original SQL literal and query inputs.
2. Thirteen calls go through private `DialectQueryCodec` shortcuts rather than
   the public compilation result. Replace them with 13 `.compile()` calls on the
   identical queries. Nine original positive cases additionally pin backend
   identity. This is not a judgment against codec tests at their actual adapter
   seam: `test_query_codec.py` remains byte-identical.
3. This focused selection has no batch combining attempted-row bindings with a
   literal conflict assignment. Add separate SQLite and MariaDB cases, each
   through its own namespace/model declarations. Do not fake portability by
   applying a foreign codec to another family's query.

Each new case inserts two three-column rows, mixes `name.to_inserted()` with
`status.to("active")`, and requires full dialect SQL, its owning backend and:

```python
(
    "a@example.com",
    "Alice",
    "inactive",
    "b@example.com",
    "Bob",
    "invited",
    "active",
)
```

The last value must bind **once, after both rows**, not once per row or before
row values. Distinct values make order and cardinality observable. These cases
complement the existing single-row MariaDB mixed-assignment check and real
bulk-upsert execution controls; they are not evidence the entire repository
lacked ordering coverage.

Implementation changes only `tests/query/test_bulk_insert_compilation.py` and
`tests/query/test_insert_conflict.py`. All 20 names/markers remain; two names are
added. All 15 original model class ASTs, including separate backend and local
owner identities, are retained; the new cases add two deliberately separate
family-specific declarations. Seven original construction-case bodies and their
decorators remain identical. No declaration extraction or generic helper is
introduced. No formatting method is needed for the new checks.

## Contract accounting

The source audit normalizes only the intentional compiler seam/result-variable
change, strips the explicitly added assertions, then compares each entire
original function AST including decorators, query inputs, model declarations,
literal expectations, error types and assertion order. All 20 match. Original
codec selection is recorded by the saved sources; retained namespace/model ASTs
establish owning-family inputs at the public seam. This is not broad AST
normalization that ignores builders, literals or expected exceptions.

| Original protection | Retained or strengthened default-suite evidence |
| --- | --- |
| Single INSERT whole-model / selected-column RETURNING | Same two names, declaration-order SQL and exact bindings; public result and SQLite backend |
| Bulk selected-column RETURNING | Same name/SQL and one RETURNING clause; now exact row-major bindings and backend too |
| Plain bulk and whole-model RETURNING | Same two names, multi-row SQL, flattened bindings and one RETURNING clause; public result/backend |
| Returning foreign column, mixed models, forged uninitialized Pending | Same three complete construction-case bodies |
| Heterogeneous present columns | Same name, input rows and `QueryCompilationError`, through public compile |
| SQLite conflict update / DoNothing | Same two names, SQLite syntax and exact values; public result/backend |
| MariaDB conflict update / DoNothing | Same two names, native syntax and exact inserted/action values; public result/backend |
| DoNothing + RETURNING, conflict on default-values insert, inserted-value regular UPDATE | Same three names and exact compilation-error class at the public seam |
| Empty action, missing target, foreign target, foreign assignment | Same four complete construction-case bodies |
| Batch row values before one bound conflict assignment | Two additional separately named dialect cases; no original execution substituted |

All 29 original assertion/context-manager sites remain after this narrow
normalization. Ten assertions are added to original cases (nine backend checks
and the missing projection binding tuple). The two new cases add six assertions.
Thirteen compilations are retained, two added: no cached/shared observation,
removed execution or default-scope reduction. Removing two support imports does
not establish a reduction in cross-*test-module* imports; no such count is claimed.

## TDD and calibrated rejection

Fifteen sequential tracer cycles use owned source snapshots and actual installed
snektest: first the missing bulk projection bindings, then each remaining public
compilation/guard replacement, then the SQLite batch-action case and its MariaDB
counterpart. Each first rejects its seeded SDK fault with one named assertion
failure and then passes with the SDK restored. The live checkout SDK is never
mutated. No mocks, local substitute runner or internal collaborator assertions
are introduced in committed tests.

A subsequent 48-command calibration compares identical original/revised
selections, restores every mutation and reruns the same selection:

| Seeded fault | Original 20-case selection | Revised 22-case selection |
| --- | --- | --- |
| Public result wrong backend / broken SQL | All 20 pass for each fault | 11 positive cases fail; 11 negative controls remain healthy |
| Public result reverses bindings | All 20 pass | Nine cases fail; two single-value DoNothing controls and 11 negatives remain healthy |
| Common compiler reverses projected bulk RETURNING bindings only | All 20 pass | Exactly the strengthened projection case fails; 21 healthy |
| Common compiler places bound conflict action before batch rows | All 20 pass | Exactly two new batch cases fail; 20 healthy |
| Common compiler repeats action bindings per batch row | All 20 pass | Exactly two new batch cases fail; 20 healthy |
| Common compiler places action first for all inserts | Original MariaDB mixed-assignment case fails; 19 healthy | Same case plus two new batch cases fail; 19 healthy |
| Missing heterogeneous-column, DoNothing/RETURNING, default-values/conflict, or regular-UPDATE inserted-value guard | Each named original negative rejects its fault; 19 healthy | Same negative rejects each fault; 21 healthy |

The heterogeneous-column guard bypass reaches a `KeyError`; the existing
`assert_raises(QueryCompilationError)` rejects that wrong error class before and
after. It is not described as successful compilation or a current product bug.
All seeded report failures are `AssertionFailure`, with zero report errors or
fixture/session teardown failures.

Three independently selected healthy controls still pass under unselected
failures: foreign-column construction under wrong public backend, single-value
DoNothing under reversed public bindings, and the single-row MariaDB mixed
assignment under the batch-only fault. All 22 cases also pass with empty `PATH`.
That demonstrates no executable search is needed by these selected checks, not
comprehensive absence of I/O or native extension loading.

The SDK currently passes every new oracle. These are local protection gaps and
fault calibrations, not a demonstrated SDK defect or repository-wide mutation
score. Other compilation/execution tests already reject some seeded paths.

## Keep-as-is and ownership boundaries

- Both real bulk-upsert RETURNING controls in
  `tests/sqlite/test_upsert_runtime.py` and `tests/mariadb/test_upsert_runtime.py`
  are unchanged. Database execution proves different behavior from SQL inspection.
- `tests/test_insert_many.py` retains native/SQLite materialization, generated IDs,
  backend-specific encoding, empty no-op behavior, erased-input guards and typed
  result contracts. The private empty-batch no-SQL plan remains distinct from
  public `.compile()` raising because no statement exists (ADR 0013).
- Conflict namespace/model declarations remain local and separate. Similar shape
  is not a reason to unify owner identities or backend families (ADRs 0003/0014).
- Existing readiness and runtime guards are preserved (ADRs 0016/0021); the new
  tests inspect no private state or execution plans.
- All 117 tracked SDK files and all other pre-existing tracked inputs remain
  byte-identical. Dependencies, property budgets, migrations, deadlines,
  cancellation, native fixture lifetimes and default discovery remain untouched.

## Validation

- Focused group **20 → 22 passed**, preserving every original name/marker and
  adding exactly the two batch-conflict cases.
- Query directory **673 → 675 passed**; forced-lazy query selection **675 passed**
  with identical names/markers to normal.
- Fresh frozen full normal suite **4,269 passed**, zero failures/errors
  or fixture/session teardown failures; wall **348.492783708 seconds**.
  Every prior full-suite name/marker remains, with exactly the two additions.
  Final code/source-path inventory matches this fresh run's inputs. Historical
  #584 evidence is used only for inventory comparison, not borrowed validation.
- No fresh full forced-lazy or direct forced-lazy native/Core child-interpreter
  evidence is claimed. Actions is intentionally disabled.

Commands set `PYTHON_CONTEXT_AWARE_WARNINGS=1` and preserve normal signal
dispositions:

```sh
PYTHON_CONTEXT_AWARE_WARNINGS=1 uv run snektest \
  tests/query/test_bulk_insert_compilation.py tests/query/test_insert_conflict.py \
  --json-output
PYTHON_CONTEXT_AWARE_WARNINGS=1 uv run snektest tests/query --json-output
PYTHON_CONTEXT_AWARE_WARNINGS=1 uv run python -X lazy_imports=all \
  scripts/run_lazy_tests.py tests/query --json-output
PYTHON_CONTEXT_AWARE_WARNINGS=1 uv run snektest tests --json-output
```

Full validation used private owned tmpfs `/dev/shm/sqa-vlkv4px7`. Only a zero-byte
uv lock remained; it/root were removed after process checks found no live owned
process. Three unreadable pre-existing process environments are an audit limit,
recorded alongside readable command-line/start-time checks. Caller-owned
`.snektest/mariadb-data` was left untouched. No stale-artifact sweep or global
per-test `TMPDIR` mutation is introduced.

Typing, lint, formatting (635 files), generated-interface and whitespace
checks passed. An initial report Markdown tuple-format rejection is retained;
Ruff formatting corrected the documentation, without modifying frozen code.

```sh
uv run ty check
uv run ruff check .
uv run ruff format --check .
uv run python scripts/generate_query_overloads.py --check
git diff --check
```

The host was not exclusive. No other suite from this session ran during the full
command. Wall time is validation context, not a matched speed comparison; no
runtime-speedup, remote matrix, default-scope reduction or product-bug claim.

The paired JSON records mappings, commands, source hashes and results. Raw
snapshots/reports/scripts remain at
`/home/crpier/.cache/sq571-write-A5UVVgkZ` (pointer:
`/tmp/snekql-write-audit-latest`). Expected fault failures are retained rather
than counted as successful validation.

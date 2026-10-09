# Python 3.15 native-contract evaluation

Date: 2026-10-09. Base: `1e7d926` (merged Python 3.15 migration and ty-only
cleanup). Tracking: #443. Compatibility preservation is deliberately out of
scope; retain features only where they provide a concrete benefit.

## Decisions

| Candidate | Decision | Demonstrated benefit |
| --- | --- | --- |
| `TypeForm[T]` raw validation | Keep | Both backend factories preserve union, literal, and `Annotated` result types instead of silently returning object results. An ordinary value supplied as a type contract is rejected by ty. |
| Native sentinels | Keep | Remove the generated-value singleton class and settings sentinel class; name the framework marker. Generated-field annotations name the exact sentinel, and ty narrows identity checks. |
| `frozendict` column metadata | Keep | Prevent callers from deleting or replacing published model/alias column entries independently of their still-bound descriptors. Expose read-only `Mapping` annotations. |
| Native closed/extra-items `TypedDict` | Keep as supported contracts and coverage | Installed Pydantic already supports these declarations. No replacement validation engine is needed: prove exact typing, extra-column preservation/rejection, and redacted database failures. |
| `typing.disjoint_base` on backend roots | Drop | Actual mixed-root declarations are already rejected by the incompatible metaclasses and backend witnesses. Trial decorators passed valid-model typing but only changed diagnostics for the mixed-root probe; no additional supported use or missing rejection was demonstrated. |

No import, dependency, interpreter, or CI installation changes are needed for
these improvements. No speedup, benchmark, or performance certification is
claimed. Unpacking comprehensions, immutable JSON defaults, profiling, and
cancellation rewrites remain out of scope without a demonstrated problem.

## Raw type contracts

Replace the public `type[T]`/`object` pair with one `TypeForm[T]` overload,
keeping the unvalidated mapping/tuple overloads. The existing runtime factory
still validates SQL, row modes, parameters, and Pydantic schema construction.
No compatibility fallback is added. Dynamic erasure is not a static guarantee;
the runtime may still accept dynamically supplied Pydantic declarations.

The new paired callers exercise both namespaces with clean independent
positive controls and one marked negative operation:

- `raw-typeform`: unions, `Annotated` tuples, literals, and TypedDict results;
  reject `validate=42` with `invalid-type-form`.
- `raw-closed`: closed and extra-items contracts; reject a closed constructor's
  undeclared field with `invalid-key`.
- `metadata-readonly`: mapping lookup and iteration; reject published column
  replacement with `invalid-assignment`.

Existing lifecycle callers also prove native-sentinel identity narrowing.
An equivalent guard with the removed singleton class leaves `int |
PendingGeneration` in ty and fails an `int` return annotation; the native
sentinel guard narrows the remaining value to `int` without a cast.
The full assessment contains 62 cases per backend, or 124 paired observations.
These are observations, not 124 independent guarantees about SQL correctness.

## Sentinel and validation separation

`PendingGeneration` is removed from every live import/export and annotation.
Use `PENDING_GENERATION` in annotations and compare with `is`. Both backend
namespaces export the same canonical sentinel defined in `snekql.storage`.
Copy, deepcopy, and pickle regressions preserve identity through re-exports;
the old singleton already preserved identity, so this is simplification rather
than a repair of broken serialization.

Pydantic 2.14.0 still raises `PydanticSchemaGenerationError` for a direct native
sentinel union. Column validation therefore continues to intercept the marker
before validating ordinary logical values. Pending input may omit a generated
field; complete Row snapshots and fetched values may not contain an unavailable
marker. No arbitrary-types workaround or disabled validation is introduced.

## Published metadata

Build model columns in a mutable local dictionary, then publish a `frozendict`.
Readers accept `Mapping`; alias query-source mappings are frozen too. Dictionary
membership is immutable immediately, while descriptor declaration guards and
the once-only deferred foreign-key coordinator retain their separate jobs.
A callable target may resolve later without adding/removing mapping entries.

This is shallow mapping immutability, not protection against deliberately
replacing class internals. It does not make stored primary keys or generated
columns unassignable in SQL, freeze nested application values, or add a public
finalization verb.

## Validation

Public regressions were run red before their implementations: exact Annotated
result typing, native-sentinel identity/type, and model metadata deletion.
Closed/extra-items runtime behavior already existed in Pydantic, so those tests
are compatibility coverage rather than claims of a new validation engine.

Environment: Linux x86-64, GIL-enabled CPython 3.15.0, ty 0.0.84, Pydantic 2.14.0,
managed SQLite 3.53.1, privately extracted MariaDB 12.3.3 binaries. Final full-suite
runs use isolated uv 0.13.0 on PATH; the global uv installation is unchanged.
Test execution uses `PYTHON_CONTEXT_AWARE_WARNINGS=1`.

| Check | Final result |
| --- | --- |
| `uv run snektest tests` | **3,711 passed**, 324.68 s, exit 0 |
| Forced-lazy full suite through `scripts/run_lazy_tests.py` | **3,711 passed**, 323.65 s, exit 0 |
| Unfiltered forced-lazy packaging, raw validation, public exports/sentinels, and settings | **122 passed**, 2.26 s, exit 0 |
| Paired ty consumer assessment | **124/124 conform**, clean positives and challenge-line negatives |
| Repository ty | Passed |
| Ruff lint and format | Passed |
| Generated interfaces and lock checks | Passed |
| Wheel/sdist build and isolated wheel SQLite/MariaDB checks | Passed, including forced-lazy smoke and two native driver tests |
| Local documentation targets and whitespace | 419 targets resolve; `git diff --check` passed |

The first complete run exposed a duplicate API-index entry after removing the
sentinel class: 3,710 tests passed and that documentation consistency test failed.
The index was corrected, its regression passed, and the complete suite was rerun
successfully; the failed run is not counted as passing validation. An early
targeted native run lacked the private MariaDB binary PATH; the configured rerun
passed without a library or system-package change.

Native database suites ran sequentially. Only task-owned, verified-stopped
private-server data was retired to keep temporary space available, preserving
error logs. Validation logs and reports remain under
`.git/python315-native-contracts/`; no system services were changed.

Full forced-lazy execution retains the migration's narrowly documented test-only
Hypothesis/OpenTelemetry SDK filters. Library imports remain explicitly lazy;
no new exclusions are added. Local results do not certify other platforms,
MariaDB versions, free-threaded Python, other event loops, or performance.

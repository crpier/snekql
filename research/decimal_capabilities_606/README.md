# Storage-aware Decimal operations: bounded experiment (#606)

**2026-11-08 — partial feasibility, not a production change or selected API.**

Refs #603. Baseline: `5f4dd8189c529a99713b629a71e60088c6974204`
(fetched `origin/main`, including merged #604). Python 3.15.0, ty 0.0.84.

## Answer

A separate static storage coordinate **can be carried through a real descriptor,
label and public CTE output**, while fetched values remain `Decimal`. On the tested
path it lets ty distinguish native numeric operations from canonical decimal-text
equality/membership. The label token is sufficient; the whole CTE need not acquire
a typed field-to-storage map.

But the stronger goal is **not proved**: ordinary `Col[Decimal] = Storage()`
declarations erase the storage distinction. This overlay needs an explicit second
annotation argument. Worse, class-body declarations accept a false capability
claim even when the constructor's specialized return type contradicts it. The
experiment therefore demonstrates conditional propagation, **not automatic or
soundly verified discovery of storage capabilities**.

Do not adopt these spellings, remove runtime guards, or claim the redesign is
implemented. No SQLite decimal recipe is selected.

## The confirmed public seams

1. Ordinary class-body columns and their public operations, with native MariaDB
   `DECIMAL` versus SQLite canonical decimal text. Preserve construction/read types.
2. A public CTE, reached through `label()`, `project(...).cte(...)` and
   `cte.column(token)`, with the same operation restrictions and exact fetch types.

MariaDB canonical-text storage is also included beside native decimal in the **same
model and same CTE**. This prevents backend identity alone from faking a solution.
`CanonicalDecimal` is existing Annotated metadata over Python `Decimal`; it is not
a different Python value class. The probes assert ordinary constructor values and
query results through public consumer interfaces.

## Baseline and isolated change

Baseline class access, label and CTE output all retain the value/comparison domains
and backend family, but no independent storage capability. See the preliminary
[source review](derived-source-review.md) and its
[original consumer probe](original-derived-probe.py.txt).

`make_overlay.py` copies the **real package** into a temporary directory. It adds:

- A phantom capability coordinate to `Attr` and `FKAttr`, carried through descriptor
  class-access overloads. Backend `Col` aliases accept that coordinate explicitly.
- A read-only structural witness, separate from value, owner and backend types.
- ty-only `Intersection` receiver constraints on the tested ordered/numeric methods.
- Propagation through label tokens, CTE token contracts and CTE output references.
- Specialized capability return annotations on the tested storage constructors.

Illustrative **research-only** declarations:

```python
amount: mariadb.Col[Decimal, Literal["numeric"]] = mariadb.Decimal(12, 2)
text: mariadb.Col[mariadb.CanonicalDecimal, Literal["text"]] = mariadb.Text()
```

The literals are a deliberately coarse two-case probe, not a general capability
model. They repeat information from storage declarations and do not solve the
Python-type-plus-storage mapping for arbitrary types or custom representations.
Existing runtime builders, guards and execution paths are not replaced. The copied
package is checked, **not imported or executed**; this is not a runtime implementation
of new generic aliases or Pydantic annotation handling.

## Observed consumer results

Eight focused snektest checks pass:

- Baseline ordinary declarations accept the tested text ordering/numeric operations.
- Replaying the full negative matrix against the unmodified package accepts **44
  storage-forbidden calls** and still rejects all six wrong-value comparisons.
- The overlay rejects those **44 calls** at exactly their marked lines and with
  exactly the expected diagnostic code: 11 methods on each of SQLite/MariaDB text
  columns, directly and through CTE outputs. The methods are `gt`, `gte`, `lt`, `lte`,
  `between`, `asc`, `desc`, `min`, `max`, `sum` and `avg`.
- All **six wrong-value controls** continue to reject strings where Decimal is
  required. There are no additional diagnostics in that negative consumer.
- The clean positive consumer has no diagnostics: native ordering/ranges/extrema/
  sums/averages pass; text equality/membership/count pass. Explicit type assertions
  retain constructor values, predicate/aggregate types, `list[Decimal]` fetches,
  `list[Decimal | None]` aggregate fetches and named projection results.
- The CTE tracer passes native operations while rejecting both text cases.
- Known failures/bypasses below are deliberately characterized, not hidden.

No consumer fixture uses `Any`, casts or diagnostic suppressions to obtain success.
The existing package has its own erased implementation types; exact fetch-type
assertions, independent bad-value controls and the same-backend pair prevent
mistaking broad type erasure for consumer success.

### Red/green sequence and negative evidence

1. The first consumer expected text `.gt()` to fail on the original package. It
   failed its assertion because ty emitted **no diagnostic**. Preserved in
   [red-direct.txt](runs/red-direct.txt).
2. Adding the direct storage coordinate and receiver restriction passed that
   consumer, using the explicit experimental annotation.
3. The CTE tracer against the direct-only overlay failed: the CTE lost the witness,
   so even valid native ordering was rejected. Preserved in
   [red-derived.txt](runs/red-derived.txt).
4. Carrying the coordinate through labels and CTE outputs passed the tracer.
5. Expanded controls exposed a separate failure: two deliberately false class-body
   capability claims were **not rejected**. The original failing expectation is
   preserved in [false-claim-rejection-failed.txt](runs/false-claim-rejection-failed.txt).
   This was not fixed or relabeled as sound enforcement; the counterexamples now
   live explicitly in `known_holes.py.txt`.

Historical failure logs retain their then-current line numbers/test names; terminal
trailing-space padding was stripped for archival. Final fixtures evolved afterward;
the logs are evidence, not golden test expectations.

## Important failures and limits

`known_holes.py.txt` is a replayable counterexample consumer:

- **False declarations pass:** a class-body numeric-capability annotation assigned
  `sqlite.Text()` is accepted, and `.gt()` then passes. The reverse false native
  declaration passes too. Ordinary assignment outside the model body rejects the
  conflicting constructor return type. Constructor annotations alone therefore do
  not enforce consistency at the actual model declaration seam.
- **Original spelling is not preserved:** `Col[Decimal]` has unknown capability in
  the overlay and rejects native `.gt()`. The RHS does not supply that information
  to subsequent class access. Explicit annotations are a real ergonomic cost.
- **Other ordinary columns regress too:** the receiver constraints are global,
  while other existing descriptors default to unknown capability. An ordinary
  `sqlite.Col[int] = sqlite.Integer()` rejects both `.gt(1)` and `.sum()` in the
  overlay, although both pass on the unchanged baseline. An independent audit
  identified this broader regression; it is now part of the counterexample probe.
- **Column-comparison bypasses remain:** direct and derived text `.gt_col()` calls
  still pass through unchanged overloads. Do not call this complete enforcement.
- **Aggregate predicates regress:** native `.sum().gt(...)` is rejected because this
  narrow witness does not propagate into `Aggregate`. A successful `.sum()` factory
  call and exact fetch type are not proof that every downstream aggregate operation
  remains usable.
- **Native Decimal arithmetic is not added:** existing `.add()` overloads support
  int/float, not Decimal; direct and derived native Decimal addition are rejected.
  The unmodified baseline rejects the same two additions while accepting the native
  aggregate predicates above. Numeric aggregation in this report must not be read
  as proof of binary arithmetic.
- Only the token-selected CTE path was proved. Outer joins/null extension, aliases,
  mixed/widened tokens, recursive/compound queries, scalar expressions and
  user-defined representations are not covered. The ordinary integer regression
  above is demonstrated, not merely an untested area.
- Full copied-package typing is **not clean**: two new `invalid-argument-type`
  diagnostics remain in `_output_provenance.py` where erased internal Attr values
  call `.sum()`/`.asc()`. See
  [overlay-package-diagnostics.json](runs/overlay-package-diagnostics.json). These
  are integration blockers, not suppressed errors. Consumer checks alone would
  miss them.

The unchanged repository passes `ty check`; that is **not** a claim that the copied
experimental package passes whole-package checking.

## Replay

From the repository root, with the existing locked development environment:

```bash
uv run snektest tests/experimental/test_decimal_storage_capabilities_606.py
uv run ty check
uv run ruff check .
uv run ruff format --check .
```

The suite copies each `.py.txt` consumer into a temporary `.py` file. Those suffixes
keep expected-error examples out of normal type checking/test discovery. It invokes
installed ty with the repository's all-errors policy and checks exact diagnostic
lines/codes, not just an exit status or count. It never imports the consumers or
executes a query. The JSON decoding cast in the test harness describes the external
checker's output; it does not cast the consumer's types.

To inspect the overlay separately (this whole-package check is expected to fail):

```bash
work=$(mktemp -d)
uv run python research/decimal_capabilities_606/make_overlay.py "$work" --derived
uv run ty check --project "$work" --python "$PWD/.venv" \
  --python-version 3.15 --error all --ignore missing-override-decorator \
  "$work/snekql"
```

Omit `--derived` to build only the direct-column slice. The builder checks source
anchors but is revision-sensitive; future changes may require an explicit update.

## Decision this enables

The CTE is not the first obstacle: a capability can travel through the existing
label-token route. The unresolved architectural choice is **how storage information
enters a trustworthy static declaration without an unpleasant second source of
truth**. Decide what annotation/declaration cost is acceptable before expanding the
proof into a framework. Separate downstream propagation and implementation gaps
must also be resolved before considering production changes.

No database execution, backend suites, precision/round-trip tests, dependency
changes or production modifications were performed. Static acceptance proves
neither actual database semantics nor lossless writes.

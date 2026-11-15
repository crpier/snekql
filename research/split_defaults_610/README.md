# Split defaults with explicit pending: real-package typing proof — #610

**2026-11-15. Static feasibility result, not a production implementation.**

**Current tracking: issue #603 / draft PR #609 only.** Former #610/#611 are
provenance, not separate ongoing queues. Original source/context is preserved in
the [consolidation archive](../../docs/design-evidence/redesign-consolidation-2026-11-15/README.md).

The maintainer accepted separate Python `default`/`default_factory` and SQL
`server_default` channels on existing constructors, retaining Col/GenCol,
Pending/Row, the Row witness and explicit pending defaults (#603 / PR #609).
The user then confirmed two seams before tests: model declaration/construction,
and public query-result typing. This report tests those seams, not databases.

## Result in plain language

**The three chosen forms work with real package declarations in the tested cases.**
They do not need a wrapper, a required-input flag, a new descriptor coordinate,
per-model generated constructors or callable-intersection tricks.

```python
# Python omission supplies a concrete value; SQL has an independent fallback.
state: db.Col[str] = db.Text(default="draft", server_default="queued")

# Python input remains required despite the SQL fallback.
state: db.Col[str] = db.Text(server_default="queued")

# Python omission leaves a pending value; SQL may supply the result later.
state: db.GenCol[str] = db.Text(default=db.PENDING_GENERATION, server_default="queued")
```

These are separate model declarations, not repeated fields in one model. Here
`db` is each actual backend namespace, SQLite and MariaDB. **Do not copy this
syntax into current applications: server_default is not implemented.**

The main implementation fact is modest: existing dataclass-transform handling
already recognizes `default`/`default_factory`. An optional, independent SQL
parameter does not need to change that constructor-typing machinery. Preserving
explicit pending avoids the special omission mechanism from the older experiment.

## What was changed in the experiment

Baseline: `5f4dd8189c529a99713b629a71e60088c6974204`, Python 3.15.0, ty 0.0.84.

`make_overlay.py` copies the actual `snekql/` package to a temporary directory,
ignoring bytecode. It adds an optional `server_default` argument to **only the
seven existing Text overloads and their implementation signature**, in:

- `snekql/storage.py`, exported by SQLite;
- `snekql/mariadb/storage.py`, exported by MariaDB.

No body, return type, field-specifier registration, descriptor, model, query or
transaction declaration is replaced. The complete patch is
[`runs/overlay.patch`](runs/overlay.patch), recorded as a zero-context diff. Existing implementation-return Any
annotations and other internal erasure are inherited unchanged; no consumer uses
Any, casts or suppression. Exact `assert_type` checks would fail if result types
became Any. The harness's single cast describes ty's external JSON response only.

**The modified implementation signature is not an implementation of the new
argument. Its body ignores it. The copied package and consumer models are never
imported/executed.** Only the checker reads them. This is deliberately not runtime
conformance evidence.

The provisional SQL argument type admits existing scalar literal families
(`str`, `int` including `bool`, `None`) and the existing CurrentTimestamp marker.
It does not infer the logical Python type or pretend to validate SQL compatibility.
The implementation signature additionally admits EllipsisType for its omitted
argument sentinel; consumer overloads do not expose that option.

This is a minimal extension, **not a full rewrite of default typing**. Existing
legacy `default=LiteralDefault(...)` / `default=CurrentTimestamp` overloads remain
in the copied package. That compatibility is inherited, not a recommendation that
those markers stay in the new Python-only channel. Their removal/rejection and
migration behavior remain unproved and unimplemented.

## Evidence at the agreed seams

All model sources import real backend declarations. A separate importing module
constructs models or inspects public query-result types. No local substitute Model,
Col, Transaction or constructor definitions stand in for the library.

### 1. Model declaration and construction

- `Col[str]` with Python and SQL defaults permits omission, yields a Pending model,
  and exposes `str` for both Pending and Row values.
- `Col[str]` with only a SQL default requires explicit input. Strings are accepted;
  None, integers and pending markers are rejected.
- `GenCol[str]` with an explicit pending default permits omission and explicit
  string/pending overrides. Pending exposes `str | PENDING_GENERATION`; Row exposes
  `str`. None and integers are rejected.
- `GenCol[str]` without a Python default stays required **both with and without** a
  SQL fallback. Explicit string/pending inputs remain valid. This rules out making
  every GenCol or every server-default field optional.
- A `str` Python factory can coexist with a SQL fallback and permits omission,
  preserving exact value types and explicit string overrides.
- A wrong Python default, a factory returning the wrong type, a factory requiring
  an argument, and simultaneous default/default_factory are rejected. No broad
  implementation signature is used as an overload escape hatch.

"Omission permits/requires" and "yields/exposes" in this report mean **static
constructor and attribute types**. No factory was called or object constructed.
The proof cannot establish which runtime value omission actually produces.

### 2. Public query-result typing

On Python-defaulted, required-SQL-defaulted, explicit-pending and source-less fields:

- SELECT whole models preserves `list[Model[Row]]`.
- SELECT scalar fields preserves `list[str]` even when Pending values admit the marker.
- Fetch-one of the generated model is exactly `Model[Row]`; fetch-one-or-none adds
  only outer None. Their fields do not retain the pending marker.
- A tuple projection preserves `list[tuple[str, str]]`.
- Single INSERT RETURNING through `Transaction.execute` preserves `Model[Row]` or
  scalar `str`, not a list. Row input is rejected by INSERT.
- Deliberately asserting Pending whole-model results or marker-bearing scalar results
  is rejected. These controls check that exact result assertions are sensitive.

No query, INSERT or Transaction method was executed. This covers declared result
shapes/cardinality, not actual SQL validity, row counts, affected rows or driver values.

## Red/green history and replay

1. Wrote an imported model/consumer test expecting the first anchor to type-check
   against the untouched package copy. Both backends failed at the declaration with
   `no-matching-overload`, not an import failure. Recorded in
   [`runs/red-python-default.txt`](runs/red-python-default.txt) (terminal trailing
   whitespace removed; historical harness line numbers are retained).
2. Added only the Text signature argument above. The same positive checks passed.
3. Added constructor/required-input controls, then factory/default controls, then
   query-result controls, one slice at a time. Existing annotations handled these
   without further package changes. Some controls were already green; no artificial
   implementation change was introduced to create a red result.
4. Added a replayable baseline check requiring the original rejection on its exact
   source line, and clean-positive runs with negative lines blanked (line numbers
   preserved). All marked negative diagnostics are then required exactly, with no
   unmarked errors accepted.

The harness initially requested a nonexistent ty JSON format; that harness failure
was corrected to GitLab JSON **before** recording the semantic red above. An early
query fixture also wrongly called fetch_all for mutations and assumed list-shaped
single INSERT results. It was corrected against the existing public execute
contract, not by altering library types. Neither harness mistake is presented as a
library blocker or green implementation step.

Replay from the repository root:

```bash
uv run snektest tests/experimental/test_split_defaults_610.py
uv run ty check
uv run ruff check .
uv run ruff format --check .
git diff --check
```

The focused suite has **10 parameterized checks** (five per backend). It checks the
baseline rejection, the clean anchor, and paired positive/negative construction,
factory and query controls. The modified-package cases reject **50 marked negative
diagnostic sites** across both backends (25 each), in addition to the two expected
unmodified-baseline rejections. The final focused output is in
[`runs/green.txt`](runs/green.txt). A separate read-only evidence audit independently
replayed all 10 checks and found no consequential missing control or overclaim. All consumer diagnostics use an all-error policy with
only the repository's existing missing-override-decorator exception. Expected
filename, line, code, multiplicity and checker exit status must match. Unmarked
errors in either imported declarations or consumer code fail the test.

### Copied-package audit—not just consumer checks

The complete copied `snekql/` tree was checked separately under the same policy.
It produced **zero diagnostics**, recorded in
[`runs/overlay-package-diagnostics.json`](runs/overlay-package-diagnostics.json).
That is separate from the repository's ordinary clean check; no copied-library
errors were hidden to get a green consumer result.

Replay it without executing the copy:

```bash
uv run python - <<'PY'
from pathlib import Path
from tempfile import TemporaryDirectory
import subprocess
import sys

from research.split_defaults_610.make_overlay import build_overlay

with TemporaryDirectory(prefix="snekql-610-audit-") as directory:
    root = Path(directory)
    build_overlay(root)
    result = subprocess.run(
        [sys.executable, "-m", "ty", "check", "--python", sys.executable,
         "--output-format", "gitlab", "snekql"],
        cwd=root, capture_output=True, text=True, check=False,
    )
    print(result.stdout)
    print(result.stderr)
    assert result.returncode == 0
PY
```

## Boundaries and next step

This result removes a **narrow static-feasibility uncertainty** around the accepted
explicit-pending form. It does not adopt new syntax (the maintainer decision is
recorded separately), implement runtime defaults, or authorize production changes.

Not proved here:

- SQL default metadata/DDL, schema verification, factory invocation or INSERT omission;
- model validation/runtime construction or driver-to-Pydantic interpretation;
- physical-nullability overrides, nullable server defaults, database clocks or Decimal
  runtime behavior;
- all other storage constructors/options, foreign keys, inheritance, aliases,
  arbitrary input/read type splits or every query composition;
- sound storage-capability discovery, broader precision guarantees or replacing
  runtime operation guards. The separate #606/#607 limitations still apply.

**Proposed next step, not started:** settle the remaining default/nullability
contract and migration behavior before a narrowly scoped runtime implementation.
The accepted explicit-pending cost does not need another workaround or redesign.

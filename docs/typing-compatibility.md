# Type-checker compatibility

Only **ty 0.0.77** is supported for the class-body model interface. Pyright and
mypy fail required positive controls. This supersedes the earlier limited
Pyright consumer support assessment for the two-coordinate model API.

## Tested versions and scope

Assessment updated 2026-09-25 on CPython 3.14.2, Linux x86-64. The current suite
has 42 cases on each backend, producing 84 positive/negative pairs. Reports
record dependency versions, commands, revision and dirty status, and SHA-256
hashes of every rendered caller. A dirty checkout is not a clean-revision claim.

| Tool | Version | Result |
| --- | --- | --- |
| ty | 0.0.77 | Supported; 84/84 pairs, plus native repository typing validation |
| Pyright CLI | 1.1.414 | Not supported for this interface; 14/84 pairs |
| mypy | 2.3.1 | Not supported for this interface; 4/84 pairs |
| Pylance | Not assessed | No editor conformance claim |

All tools target Python 3.14 and use the project interpreter's dependencies.
These results do not certify older Python, other checker versions, every API
combination, or a complete secondary-checker analysis of library internals.

A static rejection counts only with a clean independent positive control and
an error at the marked invalid operation. The new migration cases also assert
one expected challenge-line diagnostic with its expected rule. `Any`/`Unknown`
results, malformed controls, unrelated errors, checker crashes, and runtime
rejection do not establish a static guarantee.

## Contracts covered

The paired callers exercise both namespaces through their public APIs:

- Pending/Row generated-field types and Pending-only constructors.
- Explicit batch destination, row state, backend and source checks; rejection of
  sequences by single-row `insert`.
- Scoped read helpers, optional-row eligibility, closed reads through `ready`,
  read readiness/backend checks and generic Pending INSERT RETURNING results.
- Both-owner comparisons, nullable operands, scalar subqueries and alias roles.
- Shallow frozen fields in Pending and Row states, without prohibiting SQL
  assignments or nested JSON mutation.
- Bare model sources versus instances and structural lookalikes, with native
  aliases, CTEs, joins and mutation RETURNING in the positive controls.
- Positional width, named results, nullable model joins, raw query contracts,
  and defaulted typed foreign keys.

The templates and native typing tests contain exact `assert_type` controls.
The 84 observations are paired backend cases, not 84 independent API guarantees.

## Remaining limits

Ty still accepts all 24 audited explicit Pending/Row-specialized source calls
across six builders and both backends. Runtime builders reject them. Deliberate
Any/callable erasure can also hide evidence. These are not static guarantees.

Both-owner comparison typing can reject valid enclosing-table correlation in a
nested JOIN ON. Native runtime behavior is preserved, but that caller currently
needs a typing escape. General correlation typing is not redesigned.

Witness consistency, `complete` keyword schemas, some FK domains, named binding
labels and domains, and SQL validity still require runtime checks. `is_complete`
narrows the true branch only; it does not prove persistence. Freezing is shallow.
See the [migration guide](class-body-migration.md) for application examples.

Pyright passes the lifecycle, positional-width, raw-contract, defaulted-FK and
three frozen-field pairs. It fails required model constructor, helper, batch,
comparison and source controls, often rejecting nominal evidence or losing
results to Unknown. Mypy passes only the lifecycle and raw-contract pairs.
Extra errors on invalid callers with failing controls do not establish support.
No weakened annotations or checker-specific escapes were added to certify them.

## Reproduce

From the locked development environment:

```sh
uv sync --locked --all-extras
uv run ty check --exclude scratchpad
uv run python scripts/check_typing_compatibility.py > ty-report.json
uv run python scripts/check_typing_compatibility.py --checker pyright > pyright-report.json
uv run python scripts/check_typing_compatibility.py --checker mypy > mypy-report.json
```

Historical scratchpad experiments target old interfaces and are not the native
typing gate. The Pyright and mypy assessment commands currently exit 1. Exit 0
means all selected pairs conform. Exit 2 means the assessment could not run
reliably, such as missing inputs, malformed diagnostics, or a checker deadline.
Never count exit 2 as a successful rejection.

Use `--backend sqlite|mariadb` and `--case <name>` to select narrower checks.
Defaults cover all 42 cases on both backends. The CLI checks types; it does not
execute callers or connect to a database. Templates live in
[`typing_probes/`](../typing_probes/) as `.py.txt` files so ordinary checking does
not include intentional errors.

Secondary tools run in version-pinned `uv tool run` environments, not runtime
dependencies. They need cached tools or network access; Pyright also needs
Node.js. Both receive explicit strict configurations. Ty uses the repository's
all-errors policy with the existing missing-override-decorator exception.
Ambient `TY_CONFIG_FILE` cannot override the assessment configuration.

Current reports:

- [ty](../typing_probes/results/2026-09-25-class-body/ty.json)
- [Pyright](../typing_probes/results/2026-09-25-class-body/pyright.json)
- [mypy](../typing_probes/results/2026-09-25-class-body/mypy.json)

The reports under `typing_probes/results/2026-09-20/` describe the old interface,
not current compatibility. Temporary paths in report commands identify removed
caller files; rerun the CLI to render fresh callers with comparable source hashes.

## Editor guidance

Select the application's Python 3.14+ environment with snekql and Pydantic
installed. Keep ty as the project gate and use its editor integration for matching
diagnostics. Pylance, PyCharm and other engines have no conformance guarantee from
this assessment. When an editor disagrees, reproduce with the pinned checker and
correct interpreter rather than silencing a ty failure for an unassessed editor.

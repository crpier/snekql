# Typing support and validation

Use **ty 0.0.84** to check snekql applications. It is the only supported type
checker, and the consumer assessment CLI always runs ty. Static guarantees in
the documentation refer to ty. For application annotations, see the
[typing reference](typing.md).

## Tested version and scope

The 2026-10-09 Python 3.15 migration validates ty 0.0.84 on CPython 3.15.0
with Pydantic 2.14.0: all 118 positive/negative pairs conform and repository
typing passes. See the [migration review](dependency-reviews/2026-10-09-python315.md).

The native-contract follow-up validates all 124 paired cases on the same
interpreter and checker versions; see the [feature evaluation](python315-native-contracts.md).
The suite now has 62 cases on each backend, producing 124 positive/negative pairs.
Reports record dependency versions, commands, revision and dirty status, and
SHA-256 hashes of every rendered caller. A dirty checkout is not a clean-revision
claim. The assessment targets Python 3.15 and uses the project interpreter's
dependencies. These results do not certify other checker versions or every API
combination.

A static rejection counts only with a clean independent positive control and
an error at the marked invalid operation. Migration and typing-sweep cases also
assert one expected challenge-line diagnostic with its expected rule. Erased
results, malformed controls, unrelated errors, checker crashes, and runtime
rejection do not establish a static guarantee.

## Contracts covered

The paired callers exercise both namespaces through their public APIs:

- Pending/Row generated-field types and Pending-only constructors.
- Explicit batch destination, row state, backend and source checks; rejection of
  sequences by single-row `insert`.
- Scoped read helpers, optional-row eligibility, closed reads through `ready`,
  immediate SELECT execution, write readiness, backend checks, and generic Pending
  INSERT RETURNING results. SELECT `.all()` is rejected as a removed method.
- Both-owner comparisons, nullable operands, scalar subqueries and alias roles.
- Shallow frozen fields in Pending and Row states, without prohibiting SQL
  assignments or nested JSON mutation.
- Bare model sources versus instances and structural lookalikes, with native
  aliases, CTEs, joins and mutation RETURNING in the positive controls.
- Read-only scalar comparison domains, exact scalar results through `ready`,
  nullable computed comparison inputs, validation-aware RETURNING results, and
  backend-pinned nested-query factories.
- Backend identity through scalar comparisons, EXISTS, IN membership, named
  projections, FK columns, and expression helper annotations. An additional 80
  native checker tests cover operator composition, aliases, CTEs, compound output
  tokens, generated columns, and positional projection widths.
- Nominal UTC/local comparison domains and concrete temporal result types through
  aliases, CTEs, optional fields, aggregates, and scalar subqueries. Another 22
  exact-line challenges cover typed helper boundaries and incompatible inputs.
- Positional width, named results, nullable model joins, raw query contracts,
  and defaulted typed foreign keys.
- TypeForm union/literal/Annotated inference, native closed/extra-items TypedDict
  rows, rejection of non-type raw contracts, and read-only column metadata.

The templates and native typing tests contain exact `assert_type` controls.
The 124 observations are paired backend cases, not 124 independent guarantees.

## Remaining limits

Ty still accepts all 24 audited explicit Pending/Row-specialized source calls
across six builders and both backends. Runtime builders reject them. Deliberate
Any/callable erasure can also hide evidence. These are not static guarantees.

Ty can also accept an inline `fetch_all(select(...))` with an unjoined projected
column when a scalar subquery is among the fields. Binding that SELECT to a local
first preserves the tested scope rejection. This contextual-inference gap also
exists before `.all()` removal; runtime scope validation still rejects the query.
See [#433](https://github.com/crpier/snekql/issues/433). The `scalar-outer-scope`
control tests the bound-query form, not the inline form.

Both-owner comparison typing can reject valid enclosing-table correlation in a
nested JOIN ON. Native runtime behavior is preserved, but that caller currently
needs a typing escape. General correlation typing is not redesigned.

Nested expressions now retain a private family witness after construction and
through public helpers. Ordinary typed callers cannot use a MariaDB scalar,
EXISTS predicate, or IN query in SQLite, or the reverse. Erased types and dynamic
callers still require compilation checks. Correlated references also retain
runtime scope checks; family compatibility alone does not prove SQL scope.

Witness consistency, `complete` keyword schemas, some FK domains, named binding
labels and domains, and SQL validity still require runtime checks. `is_complete`
narrows the true branch only; it does not prove persistence. Freezing is shallow.
See the [migration guide](class-body-migration.md) for application examples.

## Reproduce

From the locked development environment:

```sh
uv sync --locked --all-extras
uv run ty check
uv run python scripts/check_typing_compatibility.py > ty-report.json
```

Exit 0 means all selected pairs conform. Exit 1 means at least one selected
pair does not conform. Exit 2 means the assessment could not run
reliably, such as missing inputs, malformed diagnostics, or a checker deadline.
Never count exit 2 as a successful rejection.

Use `--backend sqlite|mariadb` and `--case <name>` to select narrower checks.
Defaults cover all 62 cases on both backends. The CLI checks types; it does not
execute callers or connect to a database. Templates live in
[`typing_probes/`](../typing_probes/) as `.py.txt` files so ordinary checking does
not include intentional errors.

The assessment uses the development environment's installed ty, without fetching
another tool. It uses the repository's all-errors policy with the existing
missing-override-decorator exception.
Ambient `TY_CONFIG_FILE` cannot override the assessment configuration.

The 0.0.84 upgrade retains the all-errors policy. Source-local suppressions cover
incorrect narrowing through `finally` and task-shared state, defensive runtime
checks, and mismatches in dependency annotations. These do not establish stronger
static guarantees for those internal paths. Intentional invalid callers retain
specific expected diagnostics, including abstract expression constructors.

Historical ty reports:

- [2026-09-26 temporal contracts](../typing_probes/results/2026-09-26-temporal-contracts/ty.json)

These pre-migration reports are historical evidence, not Python 3.15 certification.
Run the assessment command above to record the current environment.

The reports under `typing_probes/results/2026-09-26-remove-select-all/` retain
the 116-pair baseline before concrete temporal values.
The reports under `typing_probes/results/2026-09-26-select-readiness/` retain
the 114-pair baseline before SELECT `.all()` removal.
The reports under `typing_probes/results/2026-09-26-expression-families/` retain
the previous read-acknowledgment contract. The current `readiness` pair accepts
bare reads and rejects unscoped DELETE; `ready-write` replaces the obsolete
`ready-incomplete` pair and rejects writes at the read-helper boundary.
The reports under `typing_probes/results/2026-09-26-typing-sweep/` retain the
102-pair assessment before nested expression family propagation.
The reports under `typing_probes/results/2026-09-26-ty/` retain the checker-upgrade
baseline of 84 pairs. The reports under
`typing_probes/results/2026-09-25-class-body/` retain the previous ty 0.0.77
assessment. The reports under `typing_probes/results/2026-09-20/` describe the old
interface, not current compatibility. Temporary paths in report commands identify removed
caller files; rerun the CLI to render fresh callers with comparable source hashes.

## Editor guidance

Select the application's Python 3.15+ environment with snekql and Pydantic
installed. Keep ty as the project gate and use its editor integration for matching
diagnostics. When an editor disagrees, reproduce with ty and the correct
interpreter rather than silencing a ty failure for an unassessed editor.

[All guides](README.md)

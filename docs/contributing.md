# Work on snekql

Use the repository's [AGENTS.md](../AGENTS.md) for the contribution workflow.
Keep changes on a branch, reference the relevant issue, and test behavior through
public APIs. Do not merge or publish without maintainer approval.

## Set up and check a checkout

```sh
uv sync --locked --all-extras
PYTHON_CONTEXT_AWARE_WARNINGS=1 uv run snektest tests
uv run ty check
uv run ruff check .
uv run ruff format --check .
uv run python scripts/generate_query_overloads.py --check
```

Select `tests` explicitly so discovery does not enter dependency test suites
inside `.venv`. The startup environment flag makes warning capture context-local;
validated raw SQL depends on it. Read snektest's installed package metadata for
its current runner and fixture documentation.

MariaDB integration tests start local servers. Install `mariadbd`,
`mariadb-install-db`, and `mariadb` before running the full suite.
[Temporary MariaDB servers](testing-mariadb.md) explains how the fixtures work.

For a quicker pass:

```sh
PYTHON_CONTEXT_AWARE_WARNINGS=1 uv run snektest tests --mark fast
uv run python -m examples.basic_app
uv run ty check examples/typed_queries.py
```

The fast group does not replace the full SQLite/MariaDB suite.

For measured suite costs, timing limitations, and safe temporary-artifact ownership,
see the [2026-10-25 test-suite baseline](test-suite-reviews/2026-10-25-baseline.md).
Use equivalent environments and repeated measurements before claiming a speedup.
The [artifact-ownership verification](test-suite-reviews/2026-10-26-artifact-ownership.md)
records successful-run cleanup, explicit error retention, and its validation limits.

## Focused typing checks

```sh
uv run snektest tests/test_typing_compatibility.py tests/test_typing_guarantees.py
uv run snektest 'tests/test_typing_guarantees.py::public_typing_contract_has_exact_diagnostic[select-all]'
uv run python scripts/check_typing_compatibility.py --case select-all --backend sqlite
```

Compatible static tests share one real all-case assessment per runner execution,
while keeping independently named diagnostic assertions. A cold named test
prepares that report; the direct CLI retains narrow case/backend execution.
Source-mutation and special-configuration tests remain independent. The
[static typing assessment review](test-suite-reviews/2026-10-26-static-typing-assessments.md)
records measured savings and coverage accounting.

The 80 nested-expression and 22 temporal checks keep their distinct inputs,
markers and independently named diagnostic assertions, but now share one real
batch assessment per immutable group:

```sh
uv run snektest tests/test_nested_expression_families.py tests/test_temporal_typing.py
uv run snektest 'tests/test_nested_expression_families.py::nested_expression_rejects_foreign_family[sqlite, eq_col]'
```

A cold named check prepares its group's report, not the other groups' reports.
The [dynamic typing batch review](test-suite-reviews/2026-10-26-dynamic-typing-batches.md)
records group savings and the small additional focused setup cost. Challenge
names, expression strings and expected rules live in `tests/typing_variants.py`.

### Explicit checker batches

The repository-only checker script also accepts a JSON manifest, for example
`requests.json`:

```json
{
  "schema_version": 1,
  "cases": [
    {
      "name": "assignment",
      "backend": "sqlite",
      "positive": "value: int = 1\n",
      "negative": "wrong: str = value  # expect-error\n"
    }
  ]
}
```

```sh
uv run python scripts/check_typing_compatibility.py --manifest requests.json
uv run python scripts/check_typing_compatibility.py --manifest requests.json --name assignment --backend sqlite
```

`positive` is a complete positive-control template; `negative` is a fragment
appended to its rendered contents in a separate file, not a second standalone
module. Positive templates may use `__BACKEND__` and `__OTHER_BACKEND__`, as in
the static probes. The combined negative source must contain exactly one
`# expect-error` marker. Every request gets independent paired files and source
hashes; source modules are type-checked, never executed.

The manifest must have schema version 1 and a nonempty `cases` list. Each request
requires a nonempty name, one explicit `sqlite` or `mariadb` backend, and both
source strings; unknown fields are rejected. Duplicate name/backend keys are
invalid even when outside a requested filter. Labels do not become filesystem
paths. `--case` and `--manifest` are mutually exclusive; `--name` requires a
manifest. `--backend` filters manifest requests, and an empty selection is an
error rather than a vacuous pass.

Exit 0 means every selected positive control is clean and every selected
negative has errors only on its marked line. It does **not** replace callers'
exact diagnostic count/rule assertions. Exit 1 emits a complete nonconforming
report, retaining independently attributable observations and unmapped errors.
Exit 2 reports usage, malformed/missing input, timeout or checker-infrastructure
failure on stderr without a success report. The existing 90-second assessment
deadline, checker configuration and normal static selectors are unchanged.

## Find the code

| Area | Start here |
| --- | --- |
| Models, states, and column declarations | `snekql/model.py`, `snekql/storage.py` |
| Predicates, query builders, and compilation | `snekql/expressions.py`, `snekql/query.py`, `snekql/_query_*.py` |
| Connections, transactions, and query execution | `snekql/runtime.py`, backend runtime and pool modules |
| Schema SQL and verification | `snekql/_schema_*.py`, backend schema modules |
| Public exceptions | `snekql/errors.py` |
| Type-checking examples | `tests/test_public_typing.py`, `typing_probes/` |
| Project terminology | [CONTEXT.md](../CONTEXT.md) |

Application code imports from `snekql.sqlite` or `snekql.mariadb`, not these
implementation modules. Preserve that boundary when editing examples.

## Review dependencies

Follow [dependency maintenance](dependency-maintenance.md) for the agent-run
review, commands, compatibility holds, and validation report. Updates are
maintainer-triggered, roughly every two weeks, rather than bot PRs.

## Maintain bundled documentation

`docs/` remains the authoring source. Add a guide to
[the release index](release-index.md) to opt it into package builds. Keep that
index limited to current consumer documentation; do not add proposals, ADRs,
internal reviews, or contributor instructions.

The build hook stages the selected guides at `snekql/docs/`, stamps the index with
the release version, and includes linked recipe sources, the changelog, and the
security policy. Prose links are adapted for offline navigation. References to
excluded repository material become explicit repository-only references; fenced
examples and inline code remain unchanged. No generated copies need committing.

Source archives contain the prepared resources, so wheel rebuilds do not require
the original `docs/` tree. Packaging tests compare direct wheels, source archives,
and rebuilt wheels, and exercise installed resources outside the checkout:

```sh
uv run snektest tests/packaging
```

## Maintain the packaged Agent Skill

Edit `snekql/.agents/skills/snekql/SKILL.md` for the consumer skill discovered by
`library-skills`. Keep its frontmatter compatible with the Agent Skills format
and its workflow focused on reading the included docs and validating consumer
changes. API examples and detailed contracts belong in `docs/`, not in the skill.

Packaging tests verify the skill resource in direct wheels, source archives, and
rebuilt wheels, and execute its retrieval command outside the checkout. When
changing the layout or frontmatter, also check real discovery and installation
in a temporary consumer environment with `uvx library-skills scan --json` and
`uvx library-skills`. Skill availability and successful retrieval do not prove
that an agent will activate it or follow it correctly.

## Check packages before release

Follow the [release checklist](adoption.md#release-checklist). Build and test an
isolated wheel rather than relying only on imports from an editable checkout.
Publication, tagging, and merging are separate maintainer actions.

For test coverage claims and supported environments, see the
[failure inventory](failure-matrix.md). Benchmarks and resource-soak runs are
separate from the ordinary correctness checks.

[All guides](README.md)

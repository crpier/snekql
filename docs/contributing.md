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

The [typing-assessment reuse review](test-suite-reviews/2026-10-26-typing-assessment.md)
records unchanged case/diagnostic coverage and matched focused timings. Immutable
contracts share one native report per test session; copied-input challenges and
representative CLI checks remain independent. A focused named test still works:

```sh
PYTHON_CONTEXT_AWARE_WARNINGS=1 uv run snektest \
  'tests/test_typing_guarantees.py::public_typing_contract_has_exact_diagnostic[temporal-domains]'
```

That selector collects one test and initializes the shared full assessment once.
For a narrower native assessment, use the unchanged CLI's `--case` and `--backend`
options. The full suite still includes all checks by default.

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

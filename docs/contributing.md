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

## Check packages before release

Follow the [release checklist](adoption.md#release-checklist). Build and test an
isolated wheel rather than relying only on imports from an editable checkout.
Publication, tagging, and merging are separate maintainer actions.

For test coverage claims and supported environments, see the
[failure inventory](failure-matrix.md). Benchmarks and resource-soak runs are
separate from the ordinary correctness checks.

[All guides](README.md)

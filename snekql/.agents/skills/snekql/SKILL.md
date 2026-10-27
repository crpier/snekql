---
name: snekql
description: >-
  Use when adding, changing, debugging, or reviewing snekql models, queries,
  transactions, connection lifecycles, migrations, or type annotations.
  Consult the included, release-matched docs and backend contracts.
---

# Work with snekql

snekql is an async typed query builder and runtime for SQLite and MariaDB. This
skill is for consumer applications. The included documentation is the API source
of truth for the installed release.

## 1. Establish the project context

Use the consumer project's Python environment and identify its SQLite or MariaDB
backend, existing model declarations, database lifecycle, and validation commands.
Read the installed documentation before choosing APIs or adapting examples.

## 2. Read the included docs

The package includes an offline index and curated guides under `snekql/docs/`.
Read the index with the project's Python runner (`uv run python` below; substitute
the project's runner if it uses another tool):

```sh
uv run python -c 'from importlib.resources import files; print(files("snekql").joinpath("docs", "README.md").read_text())'
```

The index identifies the release and routes tasks to guides for models, queries,
results, transactions, migrations, typing, backend support, and application
recipes. Read the guides relevant to the task by replacing `README.md` in that
command with the guide filename. Resolve links relative to the guide resource,
including links to packaged examples.

Resolve docs from the installed package, independently of this skill's location:
it may have been symlinked or copied into the project. If the package cannot be
imported, check the selected environment. For an editable install without bundled
resources, use the matching source checkout's `docs/README.md`.

## 3. Implement against the documented contracts

Before editing, identify the documented operations, result types, and backend
support needed for the change. Consult the typing and backend references when
annotations or SQLite/MariaDB differences affect it. Use the installed release's
contracts rather than conventions from another query builder.

For schema changes, identify the existing runner family first: read `migrations.md`
for raw-SQL history, or `recorded-migrations.md` and `recorded-migration-recovery.md`
for experimental packages/lifetime joins. Review the explicit SQL or frozen
package alongside application changes. Preserve the chosen ownership boundary;
do not convert histories or share deployment targets between runner families.
Repository-only references require a matching source checkout; use the bundled usage guides for API decisions.

## 4. Validate in the consumer project

Run the project's relevant tests and typing checks using its existing commands.
Exercise changed database behavior against the configured backend when available.
For lifecycle or migration changes, cover the affected transaction, cleanup, or
schema behavior rather than only checking generated SQL.

Finish with the changed operations supported by the consulted guides and the
relevant validation results. Report any unavailable database checks or unresolved
contract questions explicitly.
